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

import json
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, cast

from ..m27_client import M27Client
from ..project_memory import ProjectMemory
from .code_reviewer import CodeReviewer, _read_file_cached
from .committee_reviewer import CommitteeReviewer
from .fix_generator import FixGenerator
from .handoff_generator import HandoffGenerator
from .review_artifacts import ReviewArtifactStore, review_issue_to_dict
from .review_kb import GlobalReviewKB, ReviewKB
from .review_scope import ReviewScopeClassifier, ScopeInputs
from .review_workflows import ReviewWorkflowEngine, ReviewWorkflowLoader, ReviewWorkflowNode
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
    ReviewScope,
    ReviewStats,
    Severity,
)
from .verification_loop import VerificationLoop
from .worktree_manager import GitWorktreeManager, WorktreeSession

if TYPE_CHECKING:
    from ..optimization.context_budgeter import ContextBudgeter


# --- Workflow condition DSL --------------------------------------------------
# Fix: RC-04. A tiny, explicit vocabulary for ``ReviewWorkflowNode.when``.
# Adding a new predicate type means adding a constant + branch here and
# documenting it alongside ``review_workflows.py``.
WORKFLOW_CONDITION_AGENT_ENABLED = "agent_enabled:"
WORKFLOW_CONDITION_MODE = "mode:"
_WORKFLOW_CONDITION_PREFIXES: tuple[str, ...] = (
    WORKFLOW_CONDITION_AGENT_ENABLED,
    WORKFLOW_CONDITION_MODE,
)


def _workflow_condition_allows(
    *,
    condition: str | None,
    scope_agents: set[str] | list[str] | tuple[str, ...],
    active_mode: str,
) -> bool:
    """Evaluate a workflow ``when`` clause against the current review scope."""
    if condition is None or condition == "":
        return True
    if condition.startswith(WORKFLOW_CONDITION_AGENT_ENABLED):
        agent_name = condition.split(":", 1)[1]
        return agent_name in scope_agents
    if condition.startswith(WORKFLOW_CONDITION_MODE):
        return active_mode == condition.split(":", 1)[1]
    logger.warning(
        "Unknown workflow condition %r; expected one of %s",
        condition,
        _WORKFLOW_CONDITION_PREFIXES,
    )
    return True


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
    raw_issues: list[ReviewIssue] = field(default_factory=list)
    fixed_issues: list[ReviewIssue] = field(default_factory=list)
    unfixed_issues: list[ReviewIssue] = field(default_factory=list)
    artifact_dir: str | None = None
    scope_summary: dict | None = None
    agent_findings: dict[str, list[ReviewIssue]] = field(default_factory=dict)
    worktree_path: str | None = None
    base_branch: str | None = None
    sync_summary: dict | None = None
    applied_back_files: list[str] = field(default_factory=list)
    cleanup_status: str | None = None


class ReviewController:
    def __init__(
        self,
        config: ReviewConfig,
        m27_client: M27Client,
        event_callback: Callable[[ReviewEvent, dict], None] | None = None,
        use_kb: bool = True,
        kb_path: str | None = None,
        verification_loop: VerificationLoop | None = None,
        correction_signal_callback: Callable[..., None] | None = None,
        project_path: str | None = None,
        context_budgeter: ContextBudgeter | None = None,
        lesson_resolver: object | None = None,
    ):
        self.config = config
        self.m27_client = m27_client
        self.event_callback = event_callback
        self.correction_signal_callback = correction_signal_callback
        self.project_path = project_path or self._resolve_project_path(config.target_path)
        self.context_budgeter = context_budgeter
        self.lesson_resolver = lesson_resolver
        self.project_memory: ProjectMemory | None = None
        try:
            self.project_memory = ProjectMemory(self.project_path)
        except Exception as exc:
            logger.warning("Could not initialize project memory for %s: %s", self.project_path, exc)

        self.static_analyzer = StaticAnalyzer(
            target_path=config.target_path,
            language=config.language,
            include_patterns=config.include_patterns,
            exclude_patterns=config.exclude_patterns,
        )
        self.code_reviewer = CodeReviewer(
            m27_client,
            context_budgeter=context_budgeter,
            project_path=self.project_path,
            lesson_resolver=lesson_resolver,
        )
        self.committee_reviewer = CommitteeReviewer(self.code_reviewer)
        self.fix_generator = FixGenerator(
            m27_client,
            context_budgeter=context_budgeter,
            project_path=self.project_path,
            lesson_resolver=lesson_resolver,
        )
        self.handoff_generator = HandoffGenerator(
            m27_client,
            context_budgeter=context_budgeter,
            project_path=self.project_path,
            lesson_resolver=lesson_resolver,
        )
        self.review_kb = ReviewKB(kb_path) if use_kb else None
        self.global_review_kb = GlobalReviewKB() if use_kb else None
        self.verification_loop = verification_loop or VerificationLoop(m27_client)
        self.scope_classifier = ReviewScopeClassifier()
        self.workflow_loader = ReviewWorkflowLoader()
        self.workflow_engine = ReviewWorkflowEngine()
        self._fix_locks: dict[str, Lock] = {}
        self._fix_locks_guard = Lock()

        self._review_context: ReviewContext | None = None
        self._worktree_cleanup_failures: int = 0

    def _record_external_lesson_outcome(
        self,
        session_id: str,
        *,
        stages: list[str],
        success: bool,
        outcome: str,
    ) -> None:
        if self.project_memory is None:
            return
        try:
            self.project_memory.apply_transferred_lesson_outcomes(
                project_path=self.project_path,
                session_id=session_id,
                stages=stages,
                outcome=outcome,
                success=success,
            )
        except Exception as exc:
            logger.warning(
                "Failed to record external lesson outcome for review session %s: %s",
                session_id,
                exc,
            )

    def _emit(self, event: ReviewEvent, data: dict) -> None:
        if self.event_callback:
            self.event_callback(event, data)
        logger.debug(f"Review Event: {event.value} - {data}")

    def _get_fix_lock(self, file_path: str) -> Lock:
        with self._fix_locks_guard:
            return self._fix_locks.setdefault(str(Path(file_path).resolve()), Lock())

    def run(self) -> ReviewContext:
        # Fix: RC-01. Validate target containment up front so downstream fix
        # writes, worktree maps, and file reads cannot escape the project root.
        self._assert_path_within_project(self.config.target_path)

        if self._should_use_isolated_worktree():
            return self._run_in_isolated_worktree()

        started_at = perf_counter()
        ctx = ReviewContext(
            session_id=str(uuid.uuid4())[:8],
            config=self.config,
            stats=ReviewStats(),
        )
        self._review_context = ctx

        self._emit(ReviewEvent.REVIEW_START, {"session": ctx.session_id})

        workflow_name = self._resolve_workflow_name()
        if workflow_name:
            try:
                result = self._run_structured_workflow(ctx, workflow_name)
                result.stats.duration_seconds = perf_counter() - started_at
                return result
            except Exception as e:
                logger.warning(f"Structured review workflow failed, falling back: {e}")

        if self.config.mode == ReviewMode.REVIEW:
            result = self._run_review_mode(ctx)
            result.stats.duration_seconds = perf_counter() - started_at
            return result

        if self.config.mode == ReviewMode.AUTO_FIX:
            result = self._run_auto_fix_mode(ctx)
            result.stats.duration_seconds = perf_counter() - started_at
            return result

        if self.config.mode == ReviewMode.PLAN:
            result = self._run_plan_mode(ctx)
            result.stats.duration_seconds = perf_counter() - started_at
            return result

        if self.config.mode == ReviewMode.PRESSURE:
            result = self._run_pressure_mode(ctx)
            result.stats.duration_seconds = perf_counter() - started_at
            return result

        result = self._run_hybrid_mode(ctx)
        result.stats.duration_seconds = perf_counter() - started_at
        return result

    @staticmethod
    def _resolve_project_path(target_path: str) -> str:
        target = Path(target_path).resolve()
        return str(target.parent if target.is_file() else target)

    def _assert_path_within_project(self, target_path: str) -> Path:
        """Ensure ``target_path`` resolves within the project root.

        Fix: RC-01. Reject symlink traversal, ``..``-escapes, and absolute
        paths that point outside the project root so adversarial prompts or
        config cannot drive review/fix operations against arbitrary locations.
        """
        resolved = Path(target_path).resolve()
        project_root = Path(self.project_path).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(
                f"Target path {resolved} is outside project root {project_root}"
            ) from exc
        return resolved

    def _should_use_isolated_worktree(self) -> bool:
        return self.config.execution_mode == "worktree" and self.config.mode in {
            ReviewMode.AUTO_FIX,
            ReviewMode.HYBRID,
        }

    def _run_in_isolated_worktree(self) -> ReviewContext:
        manager = GitWorktreeManager(self.project_path)
        if not manager.is_available():
            msg = "Worktree execution requires the target to be inside a git repository."
            raise RuntimeError(msg)

        session_id = str(uuid.uuid4())[:8]
        session = manager.create(session_id)
        if session is None:
            msg = "Failed to create isolated git worktree for review execution."
            raise RuntimeError(msg)

        cleanup_status = "pending"
        try:
            sync_result = manager.sync_local_changes(session, self.config.target_path)
            mapped_target = manager.map_target(session, self.config.target_path)
            baseline_snapshot = manager.capture_snapshot(session, self.config.target_path)

            def remap_event(event: ReviewEvent, data: dict) -> None:
                self._emit(event, self._remap_event_data_from_worktree(session, data))

            child_config = replace(
                self.config,
                target_path=mapped_target,
                execution_mode="local",
                worktree_enabled=False,
            )
            child_controller = ReviewController(
                config=child_config,
                m27_client=self.m27_client,
                event_callback=remap_event,
                use_kb=self.review_kb is not None,
                verification_loop=self.verification_loop,
                correction_signal_callback=self.correction_signal_callback,
                project_path=self.project_path,
                context_budgeter=self.context_budgeter,
            )
            child_ctx = child_controller.run()

            delta = manager.collect_delta(session, self.config.target_path, baseline_snapshot)
            applied_back_files = manager.apply_delta(session, delta)
            mapped_ctx = self._remap_context_from_worktree(session, child_ctx)
            mapped_ctx.config = self.config
            mapped_ctx.worktree_path = session.worktree_path
            mapped_ctx.base_branch = session.base_branch
            mapped_ctx.sync_summary = sync_result.to_dict()
            mapped_ctx.applied_back_files = applied_back_files
            self._review_context = mapped_ctx
            cleanup_status = "success"
            return mapped_ctx
        except Exception:
            cleanup_status = "failed"
            raise
        finally:
            if self._review_context is not None:
                self._review_context.cleanup_status = cleanup_status
            try:
                manager.cleanup(session)
            except Exception:
                self._worktree_cleanup_failures += 1
                logger.warning("Failed to clean up review worktree", exc_info=True)

    def _remap_context_from_worktree(
        self,
        session: WorktreeSession,
        ctx: ReviewContext,
    ) -> ReviewContext:
        ctx.issues = [self._remap_issue_from_worktree(session, issue) for issue in ctx.issues]
        ctx.raw_issues = [
            self._remap_issue_from_worktree(session, issue) for issue in ctx.raw_issues
        ]
        ctx.fixed_issues = [
            self._remap_issue_from_worktree(session, issue) for issue in ctx.fixed_issues
        ]
        ctx.unfixed_issues = [
            self._remap_issue_from_worktree(session, issue) for issue in ctx.unfixed_issues
        ]
        ctx.agent_findings = {
            agent_name: [self._remap_issue_from_worktree(session, issue) for issue in issues]
            for agent_name, issues in ctx.agent_findings.items()
        }
        ctx.scope_summary = self._remap_scope_summary_from_worktree(session, ctx.scope_summary)
        return ctx

    def _remap_issue_from_worktree(
        self,
        session: WorktreeSession,
        issue: ReviewIssue,
    ) -> ReviewIssue:
        return replace(issue, file_path=self._remap_path_from_worktree(session, issue.file_path))

    def _remap_scope_summary_from_worktree(
        self,
        session: WorktreeSession,
        scope_summary: dict | None,
    ) -> dict | None:
        if scope_summary is None:
            return None

        remapped = dict(scope_summary)
        for key in ("changed_files", "source_files", "doc_files", "test_files"):
            values = remapped.get(key)
            if isinstance(values, list):
                remapped[key] = [self._remap_path_from_worktree(session, value) for value in values]
        return remapped

    def _remap_event_data_from_worktree(
        self,
        session: WorktreeSession,
        data: dict,
    ) -> dict:
        remapped: dict = {}
        for key, value in data.items():
            if key == "file" and isinstance(value, str):
                remapped[key] = self._remap_path_from_worktree(session, value)
            else:
                remapped[key] = value
        return remapped

    @staticmethod
    def _remap_path_from_worktree(session: WorktreeSession, path: str) -> str:
        worktree_root = Path(session.worktree_path).resolve()
        candidate = Path(path).resolve()
        try:
            relative = candidate.relative_to(worktree_root)
        except ValueError:
            return path
        return str(Path(session.repo_root) / relative)

    def _resolve_workflow_name(self) -> str | None:
        if self.config.workflow_name:
            if self.config.workflow_name == "legacy":
                return None
            return self.config.workflow_name
        if self.config.mode == ReviewMode.PRESSURE:
            return "pressure-review"
        if self.config.mode in {ReviewMode.AUTO_FIX, ReviewMode.HYBRID}:
            return "review-fix-verify"
        if self.config.review_profile == "comprehensive":
            return "review-comprehensive"
        if self.config.mode in {ReviewMode.REVIEW, ReviewMode.PLAN}:
            return "review-smart"
        return None

    def _runtime_target_type(self) -> str:
        if self.context_budgeter is not None:
            return self.context_budgeter.infer_target_type(self.config.target_path)
        target = Path(self.config.target_path)
        if target.is_file():
            return "file"
        if target.is_dir():
            return "directory"
        return "unknown"

    def _runtime_complexity(self, ctx: ReviewContext | None = None) -> str:
        if ctx and ctx.scope_summary and ctx.scope_summary.get("complexity"):
            return str(ctx.scope_summary["complexity"])
        return "unknown"

    def _configure_verification_runtime(self, ctx: ReviewContext) -> None:
        self.verification_loop.configure_runtime(
            project_path=self.project_path,
            session_id=ctx.session_id,
            workflow_name=self._resolve_workflow_name(),
            review_mode=self.config.mode.value,
            language=self.config.language,
            complexity=self._runtime_complexity(ctx),
            target_type=self._runtime_target_type(),
        )

    def _run_structured_workflow(self, ctx: ReviewContext, workflow_name: str) -> ReviewContext:
        workflow = self.workflow_loader.load(workflow_name)
        artifact_store = ReviewArtifactStore(self.project_path, ctx.session_id)
        ctx.artifact_dir = artifact_store.artifact_dir

        static_results = self.static_analyzer.analyze()
        all_static_issues = self._flatten_static_issues(static_results)
        self._emit(ReviewEvent.STATIC_ANALYSIS_COMPLETE, {"tools": len(static_results)})

        scope = self.scope_classifier.classify(
            ScopeInputs(
                target_path=self.config.target_path,
                workflow_name=workflow_name,
                mode=self.config.mode,
            )
        )
        ctx.scope_summary = scope.to_dict()
        artifact_store.write_scope(scope)
        self._configure_verification_runtime(ctx)

        def should_run(node: ReviewWorkflowNode, outputs: dict[str, object]) -> bool:
            # Fix: RC-04. Workflow gate DSL parsed via named constants so the
            # supported vocabulary is explicit in one place.
            return _workflow_condition_allows(
                condition=node.when,
                scope_agents=scope.review_agents,
                active_mode=self.config.mode.value,
            )

        fix_payload: dict = {
            "applied": [],
            "failed": [],
            "verified": 0,
            "remaining_issues": len(all_static_issues),
        }
        validation_payload: dict = {
            "performed": False,
            "remaining_issues": len(all_static_issues),
            "status": "not-run",
        }
        artifact_store.write_fixes(fix_payload)
        artifact_store.write_validation(validation_payload)

        def handle_classify(
            _node: ReviewWorkflowNode,
            _outputs: dict[str, object],
        ) -> dict[str, object]:
            return scope.to_dict()

        def handle_review_agent(
            node: ReviewWorkflowNode,
            _outputs: dict[str, object],
        ) -> list[ReviewIssue]:
            issues = self.committee_reviewer.run_agent(
                node.agent or "",
                self.config.target_path,
                all_static_issues,
                scope,
                self.config.pressure_focus,
                ctx.session_id,
                workflow_name,
                self.config.mode.value,
                self.config.language,
                self._runtime_complexity(ctx),
                self._runtime_target_type(),
            )
            ctx.agent_findings[node.agent or node.id] = issues
            ctx.stats.tokens_used += self.committee_reviewer.consume_agent_tokens(
                node.agent or node.id
            )
            return issues

        def handle_synthesize(
            _node: ReviewWorkflowNode,
            outputs: dict[str, object],
        ) -> list[ReviewIssue]:
            agent_findings: dict[str, list[ReviewIssue]] = {}
            for node in workflow.nodes:
                if node.node_type != "review_agent" or node.id not in outputs:
                    continue
                output_value = outputs[node.id]
                if not isinstance(output_value, list):
                    continue
                agent_findings[node.agent or node.id] = cast(list[ReviewIssue], output_value)
            synthesized = self.committee_reviewer.synthesize(agent_findings)
            ctx.raw_issues = [issue for issues in agent_findings.values() for issue in issues]
            ctx.issues = self._filter_by_severity(synthesized)
            ctx.stats.total_issues = len(synthesized)
            ctx.stats.valid_issues = len(ctx.issues)
            artifact_store.write_agent_findings(ctx.agent_findings)
            artifact_store.write_synthesis(
                ctx.issues,
                self.committee_reviewer.summarize(ctx.issues),
            )
            self._emit(ReviewEvent.SEMANTIC_REVIEW_COMPLETE, {"issues": len(ctx.issues)})
            return ctx.issues

        def handle_fix(
            _node: ReviewWorkflowNode,
            outputs: dict[str, object],
        ) -> dict[str, object]:
            synthesized_output = outputs.get("synthesize", [])
            synthesized_issues = synthesized_output if isinstance(synthesized_output, list) else []
            fix_result = self._apply_workflow_fixes(ctx, synthesized_issues, scope)
            fix_payload.update(fix_result)
            artifact_store.write_fixes(fix_payload)
            return fix_payload

        def handle_validate(
            _node: ReviewWorkflowNode,
            _outputs: dict[str, object],
        ) -> dict[str, object]:
            nonlocal validation_payload
            validation_payload = self._validate_post_fix_state(ctx)
            artifact_store.write_validation(validation_payload)
            if validation_payload["performed"]:
                self._emit(
                    ReviewEvent.FIX_VERIFIED,
                    {"remaining_issues": validation_payload["remaining_issues"]},
                )
            return validation_payload

        def handle_gate(
            _node: ReviewWorkflowNode,
            outputs: dict[str, object],
        ) -> str:
            validation_output = outputs.get("validate", validation_payload)
            validation_result = (
                validation_output if isinstance(validation_output, dict) else validation_payload
            )
            summary_markdown = self._build_summary_markdown(
                workflow_name=workflow_name,
                scope=scope.to_dict(),
                synthesized_issues=ctx.issues,
                fix_payload=fix_payload,
                validation_payload=validation_result,
            )
            artifact_store.write_summary(summary_markdown)
            return summary_markdown

        handlers = {
            "classify": handle_classify,
            "review_agent": handle_review_agent,
            "synthesize": handle_synthesize,
            "fix": handle_fix,
            "validate": handle_validate,
            "gate": handle_gate,
        }
        self.workflow_engine.execute(workflow, handlers, should_run)

        if self.config.mode == ReviewMode.PLAN and ctx.issues:
            ctx.handoff_plan = self.handoff_generator.generate_handoffs(
                ctx.issues,
                ctx.session_id,
                self.config.target_path,
                workflow_name=workflow_name,
                review_mode=self.config.mode.value,
            )
            ctx.stats.handoffs_generated = len(ctx.handoff_plan.issues)
            self._emit(ReviewEvent.HANDOFF_GENERATED, {"count": ctx.stats.handoffs_generated})
        elif self.config.mode in {ReviewMode.HYBRID, ReviewMode.REVIEW, ReviewMode.PRESSURE}:
            self._generate_handoffs(ctx)

        self._emit(
            ReviewEvent.REVIEW_COMPLETE,
            {
                "session": ctx.session_id,
                "issues": len(ctx.issues),
                "stats": self.committee_reviewer.summarize(ctx.issues),
                "artifact_dir": ctx.artifact_dir,
                "workflow": workflow_name,
            },
        )
        return ctx

    @staticmethod
    def _flatten_static_issues(static_results: list) -> list[dict]:
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
        return all_static_issues

    def _apply_fix_with_verification(
        self,
        ctx: ReviewContext,
        issue: ReviewIssue,
    ) -> tuple[bool, str | None]:
        lock = self._get_fix_lock(issue.file_path)
        with lock:
            runtime_issue = issue
            generated_fix = self.fix_generator.generate_fix(
                issue,
                session_id=ctx.session_id,
                workflow_name=self._resolve_workflow_name(),
                review_mode=self.config.mode.value,
                language=self.config.language,
                complexity=self._runtime_complexity(ctx),
                target_type=self._runtime_target_type(),
            )
            if generated_fix.ok:
                runtime_issue = replace(issue, file_path=generated_fix.file_path or issue.file_path)
                fix_result = self.fix_generator.apply_fix(runtime_issue, generated_fix.code)
            else:
                fix_result = self.fix_generator.apply_fix_from_suggestion(issue)

            if not fix_result.success:
                return False, fix_result.error or generated_fix.error or "apply-failed"

            verification_result = self.verification_loop.verify_fix(
                issue=runtime_issue,
                fixed_content=fix_result.fixed_content,
            )
            if self._review_context is not None:
                self._review_context.stats.tokens_used += verification_result.tokens_spent

            if verification_result.fix_verified:
                self._record_external_lesson_outcome(
                    ctx.session_id,
                    stages=["semantic_review", "fix_generation"],
                    success=True,
                    outcome="positive_fix_verification",
                )
                return True, verification_result.verification_details

            rollback_reason = (
                verification_result.failure_analysis or verification_result.verification_details
            )
            self._record_external_lesson_outcome(
                ctx.session_id,
                stages=["semantic_review", "fix_generation"],
                success=False,
                outcome="negative_fix_verification",
            )
            rollback_ok = self.fix_generator.rollback_fix(fix_result)
            self._emit(
                ReviewEvent.FIX_ROLLBACK,
                {
                    "file": runtime_issue.file_path,
                    "line": runtime_issue.line_number,
                    "rolled_back": rollback_ok,
                },
            )
            return False, rollback_reason

    def _record_fix_failure(self, issue: ReviewIssue, reason: str | None) -> None:
        if self.correction_signal_callback:
            self.correction_signal_callback(
                correction_type="fix_failed",
                severity=issue.severity.name,
                file_path=issue.file_path,
                line_number=issue.line_number,
                rule_id=issue.cwe_id or issue.title,
                description=issue.description,
            )

    def _apply_workflow_fixes(
        self,
        ctx: ReviewContext,
        issues: list[ReviewIssue],
        scope: ReviewScope,
    ) -> dict[str, object]:
        if self.config.mode not in {ReviewMode.AUTO_FIX, ReviewMode.HYBRID}:
            return {
                "applied": [],
                "failed": [],
                "verified": 0,
                "remaining_issues": len(issues),
            }

        fixable_issues = [issue for issue in issues if issue.auto_fixable and issue.suggested_fix]
        if self.config.mode == ReviewMode.HYBRID:
            fixable_issues = [
                issue for issue in fixable_issues if issue.severity.value <= Severity.MEDIUM.value
            ]

        issues_to_fix = fixable_issues[: min(self.config.max_fixes_per_round, scope.auto_fix_cap)]
        fixed_payload: list[dict] = []
        failed_payload: list[dict] = []

        fix_lock = Lock()
        fixed_count = 0

        def apply_single_fix(issue: ReviewIssue) -> tuple[bool, ReviewIssue, str | None]:
            success, reason = self._apply_fix_with_verification(ctx, issue)
            return success, issue, reason

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FIXES) as executor:
            futures = {executor.submit(apply_single_fix, issue): issue for issue in issues_to_fix}
            for future in as_completed(futures):
                issue = futures[future]
                try:
                    success, issue, reason = future.result()
                    if not success:
                        ctx.unfixed_issues.append(issue)
                        failed_payload.append(
                            {
                                "issue": review_issue_to_dict(issue),
                                "reason": reason or "apply-failed",
                            }
                        )
                        self._record_fix_failure(issue, reason)
                        continue

                    with fix_lock:
                        fixed_count += 1
                    ctx.fixed_issues.append(issue)
                    fixed_payload.append(
                        {
                            "issue": review_issue_to_dict(issue),
                            "verification": reason or "verified",
                        }
                    )
                    self._emit(
                        ReviewEvent.FIX_APPLIED,
                        {"file": issue.file_path, "line": issue.line_number},
                    )
                except Exception as e:
                    logger.warning(f"Fix application failed: {e}")
                    failed_payload.append({"issue": review_issue_to_dict(issue), "reason": str(e)})

        ctx.stats.fixed_issues = fixed_count
        ctx.stats.auto_fixed = fixed_count
        unresolved = [issue for issue in issues if issue not in ctx.fixed_issues]
        ctx.unfixed_issues = unresolved
        return {
            "applied": fixed_payload,
            "failed": failed_payload,
            "verified": fixed_count,
            "remaining_issues": len(unresolved),
        }

    def _validate_post_fix_state(self, ctx: ReviewContext) -> dict:
        if self.config.mode not in {ReviewMode.AUTO_FIX, ReviewMode.HYBRID}:
            return {
                "performed": False,
                "remaining_issues": len(ctx.issues),
                "status": "not-run",
            }
        re_review = self.static_analyzer.analyze()
        remaining = sum(len(result.issues) for result in re_review)
        return {
            "performed": True,
            "remaining_issues": remaining,
            "status": "passed" if remaining == 0 else "issues-remaining",
        }

    @staticmethod
    def _build_summary_markdown(
        workflow_name: str,
        scope: dict,
        synthesized_issues: list[ReviewIssue],
        fix_payload: dict,
        validation_payload: dict,
    ) -> str:
        summary = {
            "critical": sum(
                1 for issue in synthesized_issues if issue.severity == Severity.CRITICAL
            ),
            "high": sum(1 for issue in synthesized_issues if issue.severity == Severity.HIGH),
            "medium": sum(1 for issue in synthesized_issues if issue.severity == Severity.MEDIUM),
            "low": sum(1 for issue in synthesized_issues if issue.severity == Severity.LOW),
            "info": sum(1 for issue in synthesized_issues if issue.severity == Severity.INFO),
        }
        lines = [
            "# MUSCLE Review Summary",
            "",
            f"- Workflow: `{workflow_name}`",
            f"- Complexity: `{scope.get('complexity', 'unknown')}`",
            f"- Agents: {', '.join(scope.get('review_agents', [])) or 'none'}",
            f"- Findings: {json.dumps(summary, sort_keys=True)}",
            f"- Fixes verified: {fix_payload.get('verified', 0)}",
            f"- Validation status: `{validation_payload.get('status', 'not-run')}`",
            "",
            "## Synthesized Findings",
        ]
        if synthesized_issues:
            for issue in synthesized_issues[:20]:
                lines.append(
                    f"- [{issue.severity.name}] `{issue.file_path}:{issue.line_number}` {issue.title}"
                )
        else:
            lines.append("- No findings")
        return "\n".join(lines)

    def _run_review_mode(self, ctx: ReviewContext) -> ReviewContext:
        self._configure_verification_runtime(ctx)
        static_results = self.static_analyzer.analyze()
        self._emit(ReviewEvent.STATIC_ANALYSIS_COMPLETE, {"tools": len(static_results)})

        all_static_issues = self._flatten_static_issues(static_results)

        semantic_issues, summary = self.code_reviewer.review(
            self.config.target_path,
            all_static_issues,
            telemetry_session_id=ctx.session_id,
            workflow_name=self._resolve_workflow_name(),
            review_mode=self.config.mode.value,
            language=self.config.language,
            complexity=self._runtime_complexity(ctx),
            target_type=self._runtime_target_type(),
        )
        ctx.issues = self._filter_by_severity(semantic_issues)
        ctx.stats.valid_issues = len(ctx.issues)
        if isinstance(summary, dict):
            ctx.stats.tokens_used += int(summary.get("token_usage", 0))

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
        failed_fixes = 0

        def apply_single_fix(issue: ReviewIssue) -> tuple[bool, ReviewIssue, str | None]:
            success, reason = self._apply_fix_with_verification(ctx, issue)
            return success, issue, reason

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FIXES) as executor:
            futures = {executor.submit(apply_single_fix, issue): issue for issue in issues_to_fix}

            for future in as_completed(futures):
                try:
                    success, issue, reason = future.result()
                    if success:
                        with fix_lock:
                            fixed_count += 1
                        ctx.fixed_issues.append(issue)
                        self._emit(
                            ReviewEvent.FIX_APPLIED,
                            {"file": issue.file_path, "line": issue.line_number},
                        )
                        if self.review_kb:
                            self.review_kb.record_fix_attempt(issue.title, True, 0)
                    else:
                        with fix_lock:
                            failed_fixes += 1
                        ctx.stats.failed_fixes += 1
                        ctx.unfixed_issues.append(issue)
                        self._record_fix_failure(issue, reason)
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
                ctx.issues,
                ctx.session_id,
                self.config.target_path,
                workflow_name=self._resolve_workflow_name(),
                review_mode=self.config.mode.value,
            )
            ctx.stats.handoffs_generated = len(ctx.handoff_plan.issues)
            self._emit(ReviewEvent.HANDOFF_GENERATED, {"count": ctx.stats.handoffs_generated})

        return ctx

    def _run_hybrid_mode(self, ctx: ReviewContext) -> ReviewContext:
        ctx = self._run_review_mode(ctx)

        critical_high = [i for i in ctx.issues if i.severity.value >= Severity.HIGH.value]
        if critical_high:
            plan = self.handoff_generator.generate_handoffs(
                critical_high,
                ctx.session_id,
                self.config.target_path,
                workflow_name=self._resolve_workflow_name(),
                review_mode=self.config.mode.value,
            )
            ctx.handoff_plan = plan
            ctx.stats.handoffs_generated = len(plan.issues)

        fixable = [
            i for i in ctx.issues if i.auto_fixable and i.severity.value <= Severity.MEDIUM.value
        ]
        issues_to_fix = fixable[: self.config.max_fixes_per_round]

        fix_lock = Lock()
        fixed_count = 0

        def apply_single_fix(issue: ReviewIssue) -> tuple[bool, ReviewIssue, str | None]:
            success, reason = self._apply_fix_with_verification(ctx, issue)
            return success, issue, reason

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FIXES) as executor:
            futures = {executor.submit(apply_single_fix, issue): issue for issue in issues_to_fix}

            for future in as_completed(futures):
                try:
                    success, issue, reason = future.result()
                    if success:
                        with fix_lock:
                            fixed_count += 1
                        ctx.fixed_issues.append(issue)
                    else:
                        ctx.unfixed_issues.append(issue)
                        self._record_fix_failure(issue, reason)
                except Exception as e:
                    logger.warning(f"Fix application failed: {e}")

        ctx.stats.fixed_issues = fixed_count

        return ctx

    def _run_pressure_mode(self, ctx: ReviewContext) -> ReviewContext:
        artifact_store = ReviewArtifactStore(self.project_path, ctx.session_id)
        ctx.artifact_dir = artifact_store.artifact_dir
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

        def review_single_file(file_path: Path) -> tuple[list[ReviewIssue], int]:
            issues: list[ReviewIssue] = []
            token_usage = 0
            try:
                cached_content = _read_file_cached(str(file_path))
                if cached_content is not None:
                    pressure_result = self.code_reviewer.pressure_review(
                        str(file_path),
                        cached_content,
                        pressure_focus,
                        artifact_store=artifact_store,
                    )
                    summary = pressure_result.get("summary", {})
                    if isinstance(summary, dict):
                        token_usage = int(summary.get("token_usage", 0))
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
            return issues, token_usage

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FILE_REVIEWS) as executor:
            futures = {executor.submit(review_single_file, fp): fp for fp in files_to_review}

            for future in as_completed(futures):
                try:
                    issues, token_usage = future.result()
                    with issues_lock:
                        found_issues.extend(issues)
                        ctx.stats.tokens_used += token_usage
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
                high_severity,
                ctx.session_id,
                self.config.target_path,
                workflow_name=self._resolve_workflow_name(),
                review_mode=self.config.mode.value,
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
            files_reviewed=len((ctx.scope_summary or {}).get("source_files", [])),
            lines_reviewed=int((ctx.scope_summary or {}).get("line_count", 0)),
            critical_count=sum(1 for i in ctx.issues if i.severity == Severity.CRITICAL),
            high_count=sum(1 for i in ctx.issues if i.severity == Severity.HIGH),
            medium_count=sum(1 for i in ctx.issues if i.severity == Severity.MEDIUM),
            low_count=sum(1 for i in ctx.issues if i.severity == Severity.LOW),
            info_count=sum(1 for i in ctx.issues if i.severity == Severity.INFO),
            auto_fixed_count=ctx.stats.auto_fixed,
            fixed_issues=ctx.fixed_issues,
            unfixed_issues=ctx.unfixed_issues or ctx.issues,
            workflow_name=self._resolve_workflow_name(),
            execution_mode=self.config.execution_mode,
            worktree_path=ctx.worktree_path,
            base_branch=ctx.base_branch,
            sync_summary=ctx.sync_summary,
            applied_back_files=ctx.applied_back_files,
            artifact_dir=ctx.artifact_dir,
            scope_summary=ctx.scope_summary,
            raw_issues=ctx.raw_issues,
        )
