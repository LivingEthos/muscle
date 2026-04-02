"""
Review Controller - Orchestrates the code review loop.

Main orchestrator that combines:
1. Static analysis (Ruff, ESLint, etc.)
2. M2.7 semantic review
3. Automatic fix generation and verification
4. Handoff plan generation for complex issues
5. Learning from reviews via ReviewKB

Architecture Decision Record (ADR):
- Follows LoopController patterns for consistency
- Modes: review-only, auto-fix, plan-only, hybrid
- Configurable severity thresholds
- Self-learning via ReviewKB
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from ..m27_client import M27Client
from .code_reviewer import CodeReviewer, _read_file_cached
from .fix_generator import FixGenerator
from .handoff_generator import HandoffGenerator
from .review_kb import GlobalReviewKB, ReviewKB
from .static_analyzer import StaticAnalyzer
from .types import (
    HandoffPlan,
    IssueCategory,
    PressureFocus,
    ReviewConfig,
    ReviewEvent,
    ReviewIssue,
    ReviewMode,
    ReviewResult,
    ReviewStats,
    Severity,
)

logger = logging.getLogger(__name__)

MAX_PARALLEL_FILE_REVIEWS = 5
MAX_PARALLEL_FIXES = 3


@dataclass
class ReviewContext:
    session_id: str
    config: ReviewConfig
    stats: ReviewStats
    issues: list[ReviewIssue] = field(default_factory=list)
    handoff_plan: HandoffPlan | None = None


class ReviewController:
    def __init__(
        self,
        config: ReviewConfig,
        m27_client: M27Client,
        event_callback: Callable[[ReviewEvent, dict], None] | None = None,
        use_kb: bool = True,
        kb_path: str | None = None,
    ):
        self.config = config
        self.m27_client = m27_client
        self.event_callback = event_callback

        self.static_analyzer = StaticAnalyzer(
            target_path=config.target_path,
            language=config.language,
            include_patterns=config.include_patterns,
            exclude_patterns=config.exclude_patterns,
        )
        self.code_reviewer = CodeReviewer(m27_client)
        self.fix_generator = FixGenerator(m27_client)
        self.handoff_generator = HandoffGenerator(m27_client)
        self.review_kb = ReviewKB(kb_path) if use_kb else None
        self.global_review_kb = GlobalReviewKB() if use_kb else None

        self._review_context: ReviewContext | None = None

    def _emit(self, event: ReviewEvent, data: dict) -> None:
        if self.event_callback:
            self.event_callback(event, data)
        logger.debug(f"Review Event: {event.value} - {data}")

    def run(self) -> ReviewContext:
        ctx = ReviewContext(
            session_id=str(uuid.uuid4())[:8],
            config=self.config,
            stats=ReviewStats(),
        )
        self._review_context = ctx

        self._emit(ReviewEvent.REVIEW_START, {"session": ctx.session_id})

        if self.config.mode == ReviewMode.PLAN:
            return self._run_plan_mode(ctx)

        if self.config.mode == ReviewMode.REVIEW:
            return self._run_review_mode(ctx)

        if self.config.mode == ReviewMode.AUTO_FIX:
            return self._run_auto_fix_mode(ctx)

        if self.config.mode == ReviewMode.PRESSURE:
            return self._run_pressure_mode(ctx)

        return self._run_hybrid_mode(ctx)

    def _run_review_mode(self, ctx: ReviewContext) -> ReviewContext:
        static_results = self.static_analyzer.analyze()
        self._emit(ReviewEvent.STATIC_ANALYSIS_COMPLETE, {"tools": len(static_results)})

        all_static_issues = []
        for result in static_results:
            for issue in result.issues:
                all_static_issues.append(
                    {
                        "file_path": issue.file_path,
                        "line_number": issue.line_number,
                        "severity": issue.severity,
                        "message": issue.message,
                        "category": issue.category,
                        "rule_id": issue.rule_id,
                    }
                )

        semantic_issues, summary = self.code_reviewer.review(
            self.config.target_path, all_static_issues
        )
        ctx.issues = self._filter_by_severity(semantic_issues)
        ctx.stats.valid_issues = len(ctx.issues)

        self._emit(ReviewEvent.SEMANTIC_REVIEW_COMPLETE, {"issues": len(ctx.issues)})

        if ctx.issues:
            self._generate_handoffs(ctx)

        self._emit(
            ReviewEvent.REVIEW_COMPLETE,
            {
                "session": ctx.session_id,
                "issues": len(ctx.issues),
                "stats": {
                    "critical": sum(1 for i in ctx.issues if i.severity == Severity.CRITICAL),
                    "high": sum(1 for i in ctx.issues if i.severity == Severity.HIGH),
                    "medium": sum(1 for i in ctx.issues if i.severity == Severity.MEDIUM),
                },
            },
        )

        return ctx

    def _run_auto_fix_mode(self, ctx: ReviewContext) -> ReviewContext:
        ctx = self._run_review_mode(ctx)

        fixable_issues = [i for i in ctx.issues if i.auto_fixable and i.suggested_fix]
        ctx.stats.total_issues = len(fixable_issues)
        issues_to_fix = fixable_issues[: self.config.max_fixes_per_round]

        fix_lock = Lock()
        fixed_count = 0

        def apply_single_fix(issue: ReviewIssue) -> tuple[bool, ReviewIssue]:
            result = self.fix_generator.apply_fix_from_suggestion(issue)
            return result.success, issue

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FIXES) as executor:
            futures = {executor.submit(apply_single_fix, issue): issue for issue in issues_to_fix}

            for future in as_completed(futures):
                try:
                    success, issue = future.result()
                    if success:
                        with fix_lock:
                            fixed_count += 1
                        self._emit(
                            ReviewEvent.FIX_APPLIED,
                            {"file": issue.file_path, "line": issue.line_number},
                        )
                        if self.review_kb:
                            self.review_kb.record_fix_attempt(issue.title, True, 0)
                except Exception as e:
                    logger.warning(f"Fix application failed: {e}")

        ctx.stats.fixed_issues = fixed_count

        if ctx.stats.fixed_issues > 0:
            re_review = self.static_analyzer.analyze()
            self._emit(ReviewEvent.FIX_VERIFIED, {"remaining_issues": len(re_review)})

        return ctx

    def _run_plan_mode(self, ctx: ReviewContext) -> ReviewContext:
        ctx = self._run_review_mode(ctx)

        if ctx.issues:
            ctx.handoff_plan = self.handoff_generator.generate_handoffs(
                ctx.issues, ctx.session_id, self.config.target_path
            )
            ctx.stats.handoffs_generated = len(ctx.handoff_plan.issues)
            self._emit(ReviewEvent.HANDOFF_GENERATED, {"count": ctx.stats.handoffs_generated})

        return ctx

    def _run_hybrid_mode(self, ctx: ReviewContext) -> ReviewContext:
        ctx = self._run_review_mode(ctx)

        critical_high = [i for i in ctx.issues if i.severity.value >= Severity.HIGH.value]
        if critical_high:
            plan = self.handoff_generator.generate_handoffs(
                critical_high, ctx.session_id, self.config.target_path
            )
            ctx.handoff_plan = plan
            ctx.stats.handoffs_generated = len(plan.issues)

        fixable = [
            i for i in ctx.issues if i.auto_fixable and i.severity.value <= Severity.MEDIUM.value
        ]
        issues_to_fix = fixable[: self.config.max_fixes_per_round]

        fix_lock = Lock()
        fixed_count = 0

        def apply_single_fix(issue: ReviewIssue) -> tuple[bool, ReviewIssue]:
            result = self.fix_generator.apply_fix_from_suggestion(issue)
            return result.success, issue

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FIXES) as executor:
            futures = {executor.submit(apply_single_fix, issue): issue for issue in issues_to_fix}

            for future in as_completed(futures):
                try:
                    success, issue = future.result()
                    if success:
                        with fix_lock:
                            fixed_count += 1
                except Exception as e:
                    logger.warning(f"Fix application failed: {e}")

        ctx.stats.fixed_issues = fixed_count

        return ctx

    def _run_pressure_mode(self, ctx: ReviewContext) -> ReviewContext:
        static_results = self.static_analyzer.analyze()
        self._emit(ReviewEvent.STATIC_ANALYSIS_COMPLETE, {"tools": len(static_results)})

        pressure_focus = self.config.pressure_focus or PressureFocus(
            design_tradeoffs=True,
            failure_modes=True,
            race_conditions=True,
            auth_security=True,
            data_loss=True,
        )

        target = Path(self.config.target_path)
        if target.is_file():
            files_to_review = [target]
        else:
            lang = self.config.language or "python"
            ext_map = {
                "python": ".py",
                "javascript": ".js",
                "typescript": ".ts",
                "go": ".go",
                "rust": ".rs",
            }
            ext = ext_map.get(lang, ".py")
            files_to_review = list(target.rglob(f"*{ext}"))

        issues_lock = Lock()
        found_issues: list[ReviewIssue] = []

        def review_single_file(file_path: Path) -> list[ReviewIssue]:
            issues = []
            try:
                cached_content = _read_file_cached(str(file_path))
                if cached_content is not None:
                    pressure_result = self.code_reviewer.pressure_review(
                        str(file_path),
                        cached_content,
                        pressure_focus,
                    )
                    findings = pressure_result.get("pressure_findings", [])
                    for finding in findings:
                        severity_str = finding.get("severity", "MEDIUM")
                        severity = self._parse_pressure_severity(severity_str)
                        if severity.value >= self.config.severity_threshold.value:
                            issues.append(
                                ReviewIssue(
                                    file_path=finding.get("file_path", str(file_path)),
                                    line_number=finding.get("line_number", 0),
                                    severity=severity,
                                    category=IssueCategory.BEST_PRACTICE,
                                    cwe_id=None,
                                    title=finding.get("title", "Pressure finding"),
                                    description=finding.get("description", ""),
                                    code_snippet=finding.get("code_snippet", ""),
                                    suggested_fix=finding.get("suggested_approach"),
                                    auto_fixable=False,
                                )
                            )
            except Exception as e:
                logger.warning(f"Pressure review failed for {file_path}: {e}")
            return issues

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FILE_REVIEWS) as executor:
            futures = {executor.submit(review_single_file, fp): fp for fp in files_to_review}

            for future in as_completed(futures):
                try:
                    issues = future.result()
                    with issues_lock:
                        found_issues.extend(issues)
                except Exception as e:
                    logger.warning(f"Pressure review failed: {e}")

        ctx.issues = found_issues
        ctx.stats.valid_issues = len(ctx.issues)
        self._emit(ReviewEvent.SEMANTIC_REVIEW_COMPLETE, {"issues": len(ctx.issues)})

        if ctx.issues:
            self._generate_handoffs(ctx)

        self._emit(
            ReviewEvent.REVIEW_COMPLETE,
            {
                "session": ctx.session_id,
                "issues": len(ctx.issues),
                "stats": {
                    "critical": sum(1 for i in ctx.issues if i.severity == Severity.CRITICAL),
                    "high": sum(1 for i in ctx.issues if i.severity == Severity.HIGH),
                    "medium": sum(1 for i in ctx.issues if i.severity == Severity.MEDIUM),
                },
            },
        )

        return ctx

    @staticmethod
    def _parse_pressure_severity(s: str) -> Severity:
        s = s.upper()
        mapping = {
            "CRITICAL": Severity.CRITICAL,
            "HIGH": Severity.HIGH,
            "MEDIUM": Severity.MEDIUM,
            "LOW": Severity.LOW,
        }
        return mapping.get(s, Severity.MEDIUM)

    def _filter_by_severity(self, issues: list[ReviewIssue]) -> list[ReviewIssue]:
        return [i for i in issues if i.severity.value >= self.config.severity_threshold.value]

    def _generate_handoffs(self, ctx: ReviewContext) -> None:
        if not ctx.issues:
            return

        high_severity = [i for i in ctx.issues if i.severity.value >= Severity.HIGH.value]
        if high_severity:
            ctx.handoff_plan = self.handoff_generator.generate_handoffs(
                high_severity, ctx.session_id, self.config.target_path
            )
            ctx.stats.handoffs_generated = len(ctx.handoff_plan.issues)

    def get_review_result(self) -> ReviewResult | None:
        if not self._review_context:
            return None

        ctx = self._review_context
        return ReviewResult(
            session_id=ctx.session_id,
            target_path=self.config.target_path,
            issues=ctx.issues,
            files_reviewed=0,
            lines_reviewed=0,
            critical_count=sum(1 for i in ctx.issues if i.severity == Severity.CRITICAL),
            high_count=sum(1 for i in ctx.issues if i.severity == Severity.HIGH),
            medium_count=sum(1 for i in ctx.issues if i.severity == Severity.MEDIUM),
            low_count=sum(1 for i in ctx.issues if i.severity == Severity.LOW),
            info_count=sum(1 for i in ctx.issues if i.severity == Severity.INFO),
            auto_fixed_count=ctx.stats.auto_fixed,
            fixed_issues=[],
            unfixed_issues=ctx.issues,
        )
