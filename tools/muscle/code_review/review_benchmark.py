"""
Review Benchmark Runner - Fixture-based review comparisons with optional history replay.

Architecture Decision Record (ADR):
- Use fixture manifests with stable substring matchers instead of brittle exact-text checks
- Compare workflows directly through ReviewController so legacy and workflow modes share one path
- Treat historical review_runs data as supplemental trend context, not recall ground truth
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..lesson_resolver import LessonResolver
from ..m27_client import M27Client
from ..project_memory import ProjectMemory
from ..project_memory_types import ModelPackLesson, ModelPackMetadata
from ..strategy_kb import GlobalKnowledgeBase
from ..system_db import SystemDatabase
from ..tui.project_manager import ProjectConfig, ProjectManager
from .review_controller import ReviewController
from .types import ReviewConfig, ReviewIssue, ReviewMode, Severity

logger = logging.getLogger(__name__)

BENCHMARK_REPORTS_DIR = Path(".muscle/reports/benchmarks")
BENCHMARK_RELEASE_EVIDENCE_DIR = Path(".muscle/reports/release_evidence")
FIXTURE_ROOT = Path(__file__).parent / "benchmark_fixtures"
FIXTURE_MANIFEST_VERSION = 2
SUPPORTED_BENCHMARK_SUITES = (
    "all",
    "core-review",
    "neutral-baseline",
    "related-project",
    "unrelated-project",
    "model-pack",
)
PROMPT_OVERHEAD_LIMITS = {
    "core-review": 1.15,
    "neutral-baseline": 1.15,
    "unrelated-project": 1.15,
    "related-project": 1.35,
    "model-pack": 1.35,
}
DEFAULT_RELEASE_INVARIANT_GUARD = {
    "checked": False,
    "passed": False,
    "summary": "Operational invariant tests were not provided.",
    "details": {},
}

SEVERITY_VALUES = {
    "critical": Severity.CRITICAL.value,
    "high": Severity.HIGH.value,
    "medium": Severity.MEDIUM.value,
    "low": Severity.LOW.value,
    "info": Severity.INFO.value,
}


@dataclass(frozen=True)
class BenchmarkExpectedFinding:
    file_path: str
    minimum_severity: str
    matchers: list[str]


@dataclass(frozen=True)
class BenchmarkScenario:
    name: str
    suite: str
    target_path: str
    false_positive_severity: str
    expected_findings: list[BenchmarkExpectedFinding]
    description: str = ""
    project_root: str | None = None
    languages: list[str] | None = None
    tags: list[str] | None = None
    setup: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreparedBenchmarkWorkspace:
    project_path: str
    target_path: str
    project_config: ProjectConfig
    system_db: SystemDatabase
    lesson_resolver: LessonResolver


class ReviewBenchmarkRunner:
    """Run manual benchmark comparisons for MUSCLE review workflows."""

    def __init__(
        self,
        project_path: str,
        m27_client: M27Client | None = None,
        fixture_root: Path | None = None,
    ):
        self.project_path = Path(project_path).resolve()
        self.fixture_root = (fixture_root or FIXTURE_ROOT).resolve()
        self.reports_dir = self.project_path / BENCHMARK_REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.release_evidence_dir = self.project_path / BENCHMARK_RELEASE_EVIDENCE_DIR
        self.release_evidence_dir.mkdir(parents=True, exist_ok=True)
        self.m27_client = m27_client
        self.fixture_manifest_version = FIXTURE_MANIFEST_VERSION

    def run_benchmark(
        self,
        baseline: str = "legacy",
        candidate: str = "review-smart",
        include_history: bool = True,
        suite: str = "all",
    ) -> dict[str, Any]:
        scenarios = self._load_scenarios(suite=suite)
        benchmark_started = datetime.now()
        report: dict[str, Any] = {
            "started_at": benchmark_started.isoformat(),
            "baseline": baseline,
            "candidate": candidate,
            "suite": suite,
            "fixture_manifest_version": self.fixture_manifest_version,
            "scenarios": [],
        }

        aggregate = {
            "baseline": self._empty_aggregate_metrics(),
            "candidate": self._empty_aggregate_metrics(),
        }

        for scenario in scenarios:
            baseline_run = self._run_scenario(scenario, baseline)
            candidate_run = self._run_scenario(scenario, candidate)
            scenario_result = self._compare_runs(scenario, baseline_run, candidate_run)
            report["scenarios"].append(scenario_result)
            self._accumulate_metrics(aggregate["baseline"], scenario_result["baseline"])
            self._accumulate_metrics(aggregate["candidate"], scenario_result["candidate"])

        report["aggregate"] = {
            "baseline": self._finalize_aggregate_metrics(aggregate["baseline"]),
            "candidate": self._finalize_aggregate_metrics(aggregate["candidate"]),
        }
        report["suite_aggregates"] = self._aggregate_by_suite(report["scenarios"])
        report["scenario_counts_by_suite"] = self._scenario_counts_by_suite(report["scenarios"])
        report["benchmark_gates"] = self._evaluate_benchmark_gates(report)
        report["thresholds"] = self._evaluate_thresholds(report["aggregate"])
        if include_history:
            report["history"] = self._history_summary()

        report["completed_at"] = datetime.now().isoformat()
        report["duration_seconds"] = (
            datetime.fromisoformat(report["completed_at"]) - benchmark_started
        ).total_seconds()

        json_path = self._write_json_report(report)
        md_path = self._write_markdown_report(report)
        report["report_paths"] = {
            "json": str(json_path),
            "markdown": str(md_path),
        }
        return report

    def _load_manifest(self) -> dict[str, Any]:
        manifest_path = self.fixture_root / "manifest.json"
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.fixture_manifest_version = int(manifest.get("manifest_version", 1))
        return manifest

    def _load_scenarios(self, suite: str = "all") -> list[BenchmarkScenario]:
        if suite not in SUPPORTED_BENCHMARK_SUITES:
            msg = f"Unsupported benchmark suite: {suite}"
            raise ValueError(msg)

        manifest = self._load_manifest()
        scenarios: list[BenchmarkScenario] = []
        for item in manifest.get("scenarios", []):
            scenario_target = str((self.fixture_root / item["target_path"]).resolve())
            expected_findings = [
                BenchmarkExpectedFinding(
                    file_path=finding["file_path"],
                    minimum_severity=finding["minimum_severity"],
                    matchers=list(finding.get("matchers", [])),
                )
                for finding in item.get("expected_findings", [])
            ]
            scenario = BenchmarkScenario(
                name=item["name"],
                suite=item.get("suite", "core-review"),
                target_path=scenario_target,
                false_positive_severity=item.get("false_positive_severity", "medium"),
                expected_findings=expected_findings,
                description=item.get("description", ""),
                project_root=item.get("project_root"),
                languages=list(item.get("languages", [])) or None,
                tags=list(item.get("tags", [])) or None,
                setup=dict(item.get("setup", {})) or None,
            )
            if suite == "all" or scenario.suite == suite:
                scenarios.append(scenario)
        if suite != "all" and not scenarios:
            msg = f"No benchmark scenarios found for suite: {suite}"
            raise ValueError(msg)
        return scenarios

    def _run_scenario(self, scenario: BenchmarkScenario, workflow_name: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="muscle-benchmark-") as temp_dir:
            prepared = self._build_scenario_workspace(scenario, Path(temp_dir))
            controller = ReviewController(
                config=ReviewConfig(
                    target_path=prepared.target_path,
                    language=self._primary_language_label(prepared.project_config.languages),
                    mode=ReviewMode.REVIEW,
                    workflow_name=workflow_name,
                    review_profile=(
                        "comprehensive" if workflow_name == "review-comprehensive" else "smart"
                    ),
                    execution_mode="local",
                    worktree_enabled=False,
                ),
                m27_client=self._get_client(),
                use_kb=False,
                project_path=prepared.project_path,
                lesson_resolver=prepared.lesson_resolver,
            )
            context = controller.run()
            review_result = controller.get_review_result()
            if review_result is None:
                msg = f"Benchmark run produced no review result for {scenario.name}"
                raise RuntimeError(msg)
            session_id = getattr(context, "session_id", None)
            lesson_usage_events = (
                prepared.lesson_resolver.project_memory.list_lesson_usage_events(
                    project_path=prepared.project_path,
                    session_id=session_id,
                    limit=200,
                )
                if session_id
                else []
            )
            return {
                "workflow_name": workflow_name,
                "session_id": session_id,
                "issues": review_result.issues,
                "duration_seconds": context.stats.duration_seconds,
                "tokens_used": context.stats.tokens_used,
                "finding_count": len(review_result.issues),
                "verified_fix_count": len(review_result.fixed_issues),
                "one_shot_verified_fix_count": len(review_result.fixed_issues),
                "net_tokens_saved": 0,
                "lesson_usage_summary": self._summarize_lesson_usage_events(lesson_usage_events),
            }

    def _build_scenario_workspace(
        self,
        scenario: BenchmarkScenario,
        workspace_root: Path,
    ) -> PreparedBenchmarkWorkspace:
        current_project_root = workspace_root / "current_project"
        fixture_project_root = self._resolve_fixture_project_root(scenario)
        shutil.copytree(fixture_project_root, current_project_root, dirs_exist_ok=True)
        target_path = current_project_root / self._target_relative_path(scenario)
        languages = list(scenario.languages or self._infer_languages(target_path))

        project_config = ProjectConfig(
            name=scenario.name,
            path=current_project_root,
            languages=languages,
            related_project_mode="suggest",
            model_pack_mode="suggest",
        )

        setup = dict(scenario.setup or {})
        model_pack_setup = dict(setup.get("model_pack", {}))
        if model_pack_setup:
            canonical_model_key = str(model_pack_setup.get("canonical_model_key", "")).strip()
            if canonical_model_key:
                project_config.canonical_model_key = canonical_model_key
                project_config.model_manual_override = canonical_model_key
                project_config.model_identity_source = "manual_override"
                project_config.model_pack_mode = (
                    str(model_pack_setup.get("pack_mode", "suggest")) or "suggest"
                )

        manager = ProjectManager(current_project_root)
        if not manager.init_project(project_config):
            msg = f"Failed to initialize benchmark project for scenario {scenario.name}"
            raise RuntimeError(msg)

        system_db_path = workspace_root / ".system" / "system.db"
        system_db = SystemDatabase(system_db_path)

        related_setup = dict(setup.get("related_project", {}))
        if related_setup:
            source_fixture_root = self._resolve_fixture_path(
                str(related_setup["source_project_path"])
            )
            source_project_root = workspace_root / "related_source_project"
            shutil.copytree(source_fixture_root, source_project_root, dirs_exist_ok=True)
            source_config = ProjectConfig(
                name=f"{scenario.name}-source",
                path=source_project_root,
                languages=list(related_setup.get("languages", languages)),
            )
            if not ProjectManager(source_project_root).init_project(source_config):
                msg = f"Failed to initialize related source project for scenario {scenario.name}"
                raise RuntimeError(msg)
            source_pm = ProjectMemory(str(source_project_root))
            for rule in related_setup.get("learned_rules", []):
                source_pm.insert_learned_rule(
                    str(source_project_root),
                    str(rule.get("rule_text", "")),
                    str(rule.get("trigger_pattern", "")),
                )
            current_pm = ProjectMemory(str(current_project_root))
            current_pm.import_project_lessons(
                project_path=str(current_project_root),
                source_project_path=str(source_project_root),
                link_mode=str(related_setup.get("link_mode", "snapshot")),
                relatedness_score=float(related_setup.get("relatedness_score", 0.9) or 0.9),
            )

        if model_pack_setup:
            metadata = ModelPackMetadata(
                canonical_model_key=str(model_pack_setup["canonical_model_key"]),
                version=str(model_pack_setup.get("version", "fixture-v1")),
                install_status="installed",
                source_repo="fixture://benchmark",
                source_repo_commit=str(model_pack_setup.get("source_repo_commit", "fixture-v1")),
                pack_path=str(self._resolve_fixture_project_root(scenario)),
                metadata={"scenario": scenario.name},
            )
            lessons = [
                ModelPackLesson(
                    canonical_model_key=metadata.canonical_model_key,
                    lesson_key=str(lesson["lesson_key"]),
                    lesson_text=str(lesson["lesson_text"]),
                    scope_tags=list(lesson.get("scope_tags", [])),
                    safety_scope=str(lesson.get("safety_scope", "review-only")),
                    portability=str(lesson.get("portability", "portable")),
                    evidence=dict(lesson.get("evidence", {})),
                    rationale=(
                        str(lesson["rationale"]) if lesson.get("rationale") is not None else None
                    ),
                    source_repo_commit=metadata.source_repo_commit,
                )
                for lesson in model_pack_setup.get("lessons", [])
            ]
            system_db.upsert_model_pack(metadata, lessons)

        loaded_config = manager.load_config(current_project_root)
        if loaded_config is None:
            msg = f"Failed to reload benchmark project config for scenario {scenario.name}"
            raise RuntimeError(msg)

        lesson_resolver = LessonResolver(
            project_path=str(current_project_root),
            project_memory=ProjectMemory(str(current_project_root)),
            system_db=system_db,
            global_kb=GlobalKnowledgeBase(str(workspace_root / ".global-kb")),
            project_config=loaded_config,
            requested_model_label=(
                loaded_config.model_manual_override or loaded_config.canonical_model_key or None
            ),
            provider_endpoint=None,
        )

        return PreparedBenchmarkWorkspace(
            project_path=str(current_project_root),
            target_path=str(target_path),
            project_config=loaded_config,
            system_db=system_db,
            lesson_resolver=lesson_resolver,
        )

    def _compare_runs(
        self,
        scenario: BenchmarkScenario,
        baseline_run: dict[str, Any],
        candidate_run: dict[str, Any],
    ) -> dict[str, Any]:
        baseline_metrics = self._evaluate_run_against_scenario(scenario, baseline_run)
        candidate_metrics = self._evaluate_run_against_scenario(scenario, candidate_run)
        return {
            "scenario": scenario.name,
            "suite": scenario.suite,
            "description": scenario.description,
            "tags": list(scenario.tags or []),
            "target_path": scenario.target_path,
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
        }

    def _evaluate_run_against_scenario(
        self,
        scenario: BenchmarkScenario,
        run_result: dict[str, Any],
    ) -> dict[str, Any]:
        verified_fix_count = int(run_result.get("verified_fix_count", 0))
        one_shot_verified_fix_count = int(run_result.get("one_shot_verified_fix_count", 0))
        net_tokens_saved = int(run_result.get("net_tokens_saved", 0))
        issues = run_result["issues"]
        matched_issue_indexes: set[int] = set()
        matched_expected_indexes: set[int] = set()

        for expected_index, expected in enumerate(scenario.expected_findings):
            for issue_index, issue in enumerate(issues):
                if issue_index in matched_issue_indexes:
                    continue
                if self._issue_matches_expected(issue, expected, scenario.target_path):
                    matched_issue_indexes.add(issue_index)
                    matched_expected_indexes.add(expected_index)
                    break

        expected_high_critical = [
            finding
            for finding in scenario.expected_findings
            if SEVERITY_VALUES[finding.minimum_severity] >= Severity.HIGH.value
        ]
        matched_high_critical = [
            scenario.expected_findings[index]
            for index in matched_expected_indexes
            if SEVERITY_VALUES[scenario.expected_findings[index].minimum_severity]
            >= Severity.HIGH.value
        ]

        false_positive_floor = SEVERITY_VALUES[scenario.false_positive_severity]
        false_positive_count = sum(
            1
            for issue_index, issue in enumerate(issues)
            if issue_index not in matched_issue_indexes
            and issue.severity.value >= false_positive_floor
        )
        lesson_usage_summary = dict(
            run_result.get("lesson_usage_summary", self._empty_lesson_usage_summary())
        )
        lesson_usage_by_source = dict(lesson_usage_summary.get("by_source", {}))

        expected_count = len(scenario.expected_findings)
        high_critical_expected_count = len(expected_high_critical)
        return {
            "workflow_name": run_result["workflow_name"],
            "finding_count": run_result["finding_count"],
            "tokens_used": run_result["tokens_used"],
            "duration_seconds": run_result["duration_seconds"],
            "verified_fix_count": verified_fix_count,
            "one_shot_verified_fix_count": one_shot_verified_fix_count,
            "tokens_per_verified_fix": (
                run_result["tokens_used"] / verified_fix_count if verified_fix_count else None
            ),
            "net_tokens_saved": net_tokens_saved,
            "matched_expected": len(matched_expected_indexes),
            "expected_total": expected_count,
            "recall": (len(matched_expected_indexes) / expected_count) if expected_count else 1.0,
            "matched_high_critical": len(matched_high_critical),
            "high_critical_total": high_critical_expected_count,
            "high_critical_recall": (
                len(matched_high_critical) / high_critical_expected_count
                if high_critical_expected_count
                else 1.0
            ),
            "false_positive_count": false_positive_count,
            "false_positive_rate": (false_positive_count / max(run_result["finding_count"], 1)),
            "lesson_usage_summary": lesson_usage_summary,
            "lesson_usage_count": int(lesson_usage_summary.get("total_events", 0) or 0),
            "related_lesson_usage_count": int(lesson_usage_by_source.get("related", 0) or 0),
            "model_pack_lesson_usage_count": int(lesson_usage_by_source.get("model-pack", 0) or 0),
        }

    def _issue_matches_expected(
        self,
        issue: ReviewIssue,
        expected: BenchmarkExpectedFinding,
        scenario_target_path: str,
    ) -> bool:
        relative_path = self._relative_issue_path(issue.file_path, scenario_target_path)
        if relative_path != expected.file_path:
            return False
        if issue.severity.value < SEVERITY_VALUES[expected.minimum_severity]:
            return False
        haystack = f"{issue.title} {issue.description}".lower()
        return any(matcher.lower() in haystack for matcher in expected.matchers)

    @staticmethod
    def _relative_issue_path(file_path: str, scenario_target_path: str) -> str:
        issue_path = Path(file_path).resolve()
        target_path = Path(scenario_target_path).resolve()
        base_path = (
            target_path.parent if target_path.is_file() or target_path.suffix else target_path
        )
        try:
            return str(issue_path.relative_to(base_path))
        except ValueError:
            return issue_path.name

    @staticmethod
    def _empty_aggregate_metrics() -> dict[str, Any]:
        return {
            "matched_expected": 0,
            "expected_total": 0,
            "matched_high_critical": 0,
            "high_critical_total": 0,
            "false_positive_count": 0,
            "finding_count": 0,
            "tokens_used": 0,
            "duration_seconds": 0.0,
            "scenario_count": 0,
            "verified_fix_count": 0,
            "one_shot_verified_fix_count": 0,
            "net_tokens_saved": 0,
            "lesson_usage_count": 0,
            "related_lesson_usage_count": 0,
            "model_pack_lesson_usage_count": 0,
        }

    @staticmethod
    def _accumulate_metrics(aggregate: dict[str, Any], metrics: dict[str, Any]) -> None:
        aggregate["matched_expected"] += metrics["matched_expected"]
        aggregate["expected_total"] += metrics["expected_total"]
        aggregate["matched_high_critical"] += metrics["matched_high_critical"]
        aggregate["high_critical_total"] += metrics["high_critical_total"]
        aggregate["false_positive_count"] += metrics["false_positive_count"]
        aggregate["finding_count"] += metrics["finding_count"]
        aggregate["tokens_used"] += metrics["tokens_used"]
        aggregate["duration_seconds"] += metrics["duration_seconds"]
        aggregate["verified_fix_count"] += metrics["verified_fix_count"]
        aggregate["one_shot_verified_fix_count"] += metrics["one_shot_verified_fix_count"]
        aggregate["net_tokens_saved"] += metrics["net_tokens_saved"]
        aggregate["lesson_usage_count"] += int(metrics.get("lesson_usage_count", 0) or 0)
        aggregate["related_lesson_usage_count"] += int(
            metrics.get("related_lesson_usage_count", 0) or 0
        )
        aggregate["model_pack_lesson_usage_count"] += int(
            metrics.get("model_pack_lesson_usage_count", 0) or 0
        )
        aggregate["scenario_count"] += 1

    @staticmethod
    def _finalize_aggregate_metrics(aggregate: dict[str, Any]) -> dict[str, Any]:
        expected_total = aggregate["expected_total"]
        high_critical_total = aggregate["high_critical_total"]
        finding_count = aggregate["finding_count"]
        return {
            **aggregate,
            "recall": (aggregate["matched_expected"] / expected_total) if expected_total else 1.0,
            "high_critical_recall": (
                aggregate["matched_high_critical"] / high_critical_total
                if high_critical_total
                else 1.0
            ),
            "false_positive_rate": (aggregate["false_positive_count"] / max(finding_count, 1)),
            "one_shot_verified_fix_rate": (
                aggregate["one_shot_verified_fix_count"] / aggregate["verified_fix_count"]
                if aggregate["verified_fix_count"]
                else 0.0
            ),
            "tokens_per_verified_fix": (
                aggregate["tokens_used"] / aggregate["verified_fix_count"]
                if aggregate["verified_fix_count"]
                else None
            ),
            "external_lesson_usage_count": (
                aggregate["related_lesson_usage_count"] + aggregate["model_pack_lesson_usage_count"]
            ),
        }

    @staticmethod
    def _empty_lesson_usage_summary() -> dict[str, Any]:
        return {
            "total_events": 0,
            "by_source": {},
            "sources": [],
            "outcomes": {},
        }

    def _summarize_lesson_usage_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        by_source: dict[str, int] = {}
        outcomes: dict[str, int] = {}
        for event in events:
            source = str(event.get("lesson_source", "")).strip() or "unknown"
            by_source[source] = by_source.get(source, 0) + 1
            outcome = str(event.get("outcome", "")).strip() or "pending"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return {
            "total_events": len(events),
            "by_source": by_source,
            "sources": sorted(by_source),
            "outcomes": outcomes,
        }

    def _aggregate_by_suite(self, scenarios: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        by_suite: dict[str, dict[str, Any]] = {}
        for scenario in scenarios:
            suite = str(scenario.get("suite", "core-review"))
            bucket = by_suite.setdefault(
                suite,
                {
                    "baseline": self._empty_aggregate_metrics(),
                    "candidate": self._empty_aggregate_metrics(),
                    "scenario_count": 0,
                    "candidate_measurable_wins": 0,
                    "candidate_related_traceable_scenarios": 0,
                    "candidate_model_pack_traceable_scenarios": 0,
                },
            )
            self._accumulate_metrics(bucket["baseline"], scenario["baseline"])
            self._accumulate_metrics(bucket["candidate"], scenario["candidate"])
            bucket["scenario_count"] += 1
            if self._scenario_has_measurable_win(scenario):
                bucket["candidate_measurable_wins"] += 1
            if int(scenario["candidate"].get("related_lesson_usage_count", 0) or 0) > 0:
                bucket["candidate_related_traceable_scenarios"] += 1
            if int(scenario["candidate"].get("model_pack_lesson_usage_count", 0) or 0) > 0:
                bucket["candidate_model_pack_traceable_scenarios"] += 1

        for suite, bucket in by_suite.items():
            bucket["baseline"] = self._finalize_aggregate_metrics(bucket["baseline"])
            bucket["candidate"] = self._finalize_aggregate_metrics(bucket["candidate"])
            bucket["prompt_overhead_ratio"] = self._token_overhead_ratio(
                bucket["baseline"]["tokens_used"],
                bucket["candidate"]["tokens_used"],
            )
            bucket["prompt_overhead_limit"] = PROMPT_OVERHEAD_LIMITS.get(suite)
        return by_suite

    @staticmethod
    def _token_overhead_ratio(baseline_tokens: int, candidate_tokens: int) -> float | None:
        if baseline_tokens <= 0:
            return None
        return candidate_tokens / baseline_tokens

    @staticmethod
    def _scenario_has_measurable_win(scenario: dict[str, Any]) -> bool:
        baseline = scenario["baseline"]
        candidate = scenario["candidate"]
        recall_gain = float(candidate["recall"]) > float(baseline["recall"])
        high_critical_gain = float(candidate["high_critical_recall"]) > float(
            baseline["high_critical_recall"]
        )
        false_positive_gain = float(candidate["false_positive_rate"]) < float(
            baseline["false_positive_rate"]
        )
        no_recall_regression = float(candidate["recall"]) >= float(baseline["recall"]) and float(
            candidate["high_critical_recall"]
        ) >= float(baseline["high_critical_recall"])
        return recall_gain or high_critical_gain or (false_positive_gain and no_recall_regression)

    def _evaluate_benchmark_gates(self, report: dict[str, Any]) -> dict[str, Any]:
        suite_aggregates = dict(report.get("suite_aggregates", {}))
        gates: dict[str, dict[str, Any]] = {}

        protected_suites = ["core-review", "neutral-baseline", "unrelated-project"]
        protected_missing = [suite for suite in protected_suites if suite not in suite_aggregates]
        protected_failures: list[dict[str, Any]] = []
        for suite in protected_suites:
            metrics = suite_aggregates.get(suite)
            if metrics is None:
                continue
            baseline = metrics["baseline"]
            candidate = metrics["candidate"]
            if (
                float(candidate["recall"]) < float(baseline["recall"])
                or float(candidate["high_critical_recall"])
                < float(baseline["high_critical_recall"])
                or float(candidate["false_positive_rate"]) > float(baseline["false_positive_rate"])
            ):
                protected_failures.append(
                    {
                        "suite": suite,
                        "baseline": {
                            "recall": baseline["recall"],
                            "high_critical_recall": baseline["high_critical_recall"],
                            "false_positive_rate": baseline["false_positive_rate"],
                        },
                        "candidate": {
                            "recall": candidate["recall"],
                            "high_critical_recall": candidate["high_critical_recall"],
                            "false_positive_rate": candidate["false_positive_rate"],
                        },
                    }
                )
        gates["project_only_no_regression"] = {
            "passed": not protected_missing and not protected_failures,
            "summary": "Project-local and unrelated suites must not regress.",
            "missing_suites": protected_missing,
            "failing_suites": protected_failures,
        }

        related_metrics = suite_aggregates.get("related-project")
        gates["related_project_measurable_win"] = {
            "passed": related_metrics is not None
            and int(related_metrics.get("candidate_measurable_wins", 0) or 0) > 0,
            "summary": "Related-project overlays must win on at least one related-project scenario.",
            "missing_suites": [] if related_metrics is not None else ["related-project"],
            "candidate_measurable_wins": (
                int(related_metrics.get("candidate_measurable_wins", 0) or 0)
                if related_metrics is not None
                else 0
            ),
            "scenario_count": (
                int(related_metrics.get("scenario_count", 0) or 0)
                if related_metrics is not None
                else 0
            ),
        }

        model_pack_metrics = suite_aggregates.get("model-pack")
        gates["model_pack_measurable_win"] = {
            "passed": model_pack_metrics is not None
            and int(model_pack_metrics.get("candidate_measurable_wins", 0) or 0) > 0,
            "summary": "Model-pack overlays must win on at least one model-pack scenario.",
            "missing_suites": [] if model_pack_metrics is not None else ["model-pack"],
            "candidate_measurable_wins": (
                int(model_pack_metrics.get("candidate_measurable_wins", 0) or 0)
                if model_pack_metrics is not None
                else 0
            ),
            "scenario_count": (
                int(model_pack_metrics.get("scenario_count", 0) or 0)
                if model_pack_metrics is not None
                else 0
            ),
        }

        prompt_missing = [
            suite for suite in PROMPT_OVERHEAD_LIMITS if suite not in suite_aggregates
        ]
        prompt_failures: list[dict[str, Any]] = []
        for suite, limit in PROMPT_OVERHEAD_LIMITS.items():
            metrics = suite_aggregates.get(suite)
            if metrics is None:
                continue
            ratio = metrics.get("prompt_overhead_ratio")
            if ratio is not None and float(ratio) > float(limit):
                prompt_failures.append(
                    {
                        "suite": suite,
                        "ratio": ratio,
                        "limit": limit,
                    }
                )
        gates["prompt_overhead_within_budget"] = {
            "passed": not prompt_missing and not prompt_failures,
            "summary": "Candidate prompt/token overhead must stay within per-suite budget ratios.",
            "missing_suites": prompt_missing,
            "failing_suites": prompt_failures,
            "limits": PROMPT_OVERHEAD_LIMITS,
        }

        related_traceable = (
            related_metrics is not None
            and int(related_metrics.get("candidate_related_traceable_scenarios", 0) or 0) > 0
        )
        model_pack_traceable = (
            model_pack_metrics is not None
            and int(model_pack_metrics.get("candidate_model_pack_traceable_scenarios", 0) or 0) > 0
        )
        gates["external_lesson_usage_traceable"] = {
            "passed": related_traceable and model_pack_traceable,
            "summary": "Benchmark results must show traceable external lesson usage for related and model-pack suites.",
            "related_project_traceable_scenarios": (
                int(related_metrics.get("candidate_related_traceable_scenarios", 0) or 0)
                if related_metrics is not None
                else 0
            ),
            "model_pack_traceable_scenarios": (
                int(model_pack_metrics.get("candidate_model_pack_traceable_scenarios", 0) or 0)
                if model_pack_metrics is not None
                else 0
            ),
            "missing_suites": [
                suite
                for suite, metrics in (
                    ("related-project", related_metrics),
                    ("model-pack", model_pack_metrics),
                )
                if metrics is None
            ],
        }

        return {
            "overall_passed": all(gate["passed"] for gate in gates.values()),
            "gates": gates,
        }

    def build_release_evidence(
        self,
        report: dict[str, Any],
        *,
        operational_invariants: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        benchmark_gates = dict(
            report.get("benchmark_gates") or self._evaluate_benchmark_gates(report)
        )
        invariants = dict(operational_invariants or {})
        offline_guard = dict(invariants.get("offline_guardrails", DEFAULT_RELEASE_INVARIANT_GUARD))
        release_gates = dict(benchmark_gates.get("gates", {}))
        release_gates["normal_paths_offline_safe"] = {
            "passed": bool(offline_guard.get("checked")) and bool(offline_guard.get("passed")),
            "summary": str(
                offline_guard.get(
                    "summary",
                    "Normal run/review paths must stay off remote model-pack fetch flows.",
                )
            ),
            "details": dict(offline_guard.get("details", {})),
            "checked": bool(offline_guard.get("checked")),
        }
        overall_passed = all(gate["passed"] for gate in release_gates.values())
        return {
            "generated_at": datetime.now().isoformat(),
            "project_path": str(self.project_path),
            "suite": str(report.get("suite", "all")),
            "benchmark_report_paths": dict(report.get("report_paths", {})),
            "suite_aggregates": dict(report.get("suite_aggregates", {})),
            "benchmark_gates": benchmark_gates,
            "operational_invariants": invariants,
            "release_gates": {
                "overall_passed": overall_passed,
                "gates": release_gates,
            },
        }

    def write_release_evidence(self, evidence: dict[str, Any]) -> dict[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.release_evidence_dir / f"release_gates_{timestamp}.json"
        md_path = self.release_evidence_dir / f"release_gates_{timestamp}.md"
        json_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

        lines = [
            "# MUSCLE Release Gate Evidence",
            "",
            f"- Project: `{evidence['project_path']}`",
            f"- Suite: `{evidence.get('suite', 'all')}`",
            f"- Overall passed: `{evidence['release_gates']['overall_passed']}`",
            "",
            "## Benchmark Reports",
            "",
        ]
        for label, path in dict(evidence.get("benchmark_report_paths", {})).items():
            lines.append(f"- {label}: `{path}`")

        lines.extend(["", "## Release Gates", ""])
        for gate_name, gate in dict(evidence["release_gates"]["gates"]).items():
            lines.append(f"- `{gate_name}`: `{gate['passed']}`")
            lines.append(f"  Summary: {gate.get('summary', 'n/a')}")

        offline_guard = dict(
            dict(evidence.get("operational_invariants", {})).get("offline_guardrails", {})
        )
        if offline_guard:
            lines.extend(
                [
                    "",
                    "## Offline Guardrails",
                    "",
                    f"- Checked: `{offline_guard.get('checked', False)}`",
                    f"- Passed: `{offline_guard.get('passed', False)}`",
                    f"- Summary: {offline_guard.get('summary', 'n/a')}",
                ]
            )

        md_path.write_text("\n".join(lines), encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path)}

    @staticmethod
    def _evaluate_thresholds(aggregate: dict[str, Any]) -> dict[str, Any]:
        baseline = aggregate["baseline"]
        candidate = aggregate["candidate"]

        recall_delta = candidate["high_critical_recall"] - baseline["high_critical_recall"]
        false_positive_delta = candidate["false_positive_rate"] - baseline["false_positive_rate"]

        token_reduction: float | None = None
        if baseline["tokens_used"] > 0:
            token_reduction = 1 - (candidate["tokens_used"] / baseline["tokens_used"])

        return {
            "high_critical_recall_up_20pct": recall_delta >= 0.2,
            "false_positive_rate_not_worse": false_positive_delta <= 0,
            "token_cost_down_30pct": token_reduction is not None and token_reduction >= 0.3,
            "high_critical_recall_delta": recall_delta,
            "false_positive_rate_delta": false_positive_delta,
            "token_cost_reduction": token_reduction,
        }

    def _history_summary(self) -> dict[str, Any]:
        memory = ProjectMemory(str(self.project_path))
        runs = memory.list_review_runs(project_path=str(self.project_path), limit=200)
        if not runs:
            return {"available": False, "review_runs": 0}

        total_runs = len(runs)
        total_tokens = sum(int(run.get("token_cost", 0)) for run in runs)
        total_duration = sum(int(run.get("duration_ms", 0)) for run in runs)
        total_findings = sum(int(run.get("findings_count", 0)) for run in runs)

        return {
            "available": True,
            "review_runs": total_runs,
            "average_token_cost": total_tokens / total_runs,
            "average_duration_ms": total_duration / total_runs,
            "average_findings_count": total_findings / total_runs,
        }

    def _write_json_report(self, report: dict[str, Any]) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.reports_dir / f"benchmark_{timestamp}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report_path

    def _write_markdown_report(self, report: dict[str, Any]) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.reports_dir / f"benchmark_{timestamp}.md"
        baseline = report["aggregate"]["baseline"]
        candidate = report["aggregate"]["candidate"]
        thresholds = report["thresholds"]
        suite_aggregates = dict(report.get("suite_aggregates", {}))
        benchmark_gates = dict(report.get("benchmark_gates", {}))

        lines = [
            "# MUSCLE Review Benchmark",
            "",
            f"- Baseline: `{report['baseline']}`",
            f"- Candidate: `{report['candidate']}`",
            f"- Suite: `{report.get('suite', 'all')}`",
            f"- Fixture manifest version: `{report.get('fixture_manifest_version', FIXTURE_MANIFEST_VERSION)}`",
            "",
            "## Aggregate",
            "",
            "| Metric | Baseline | Candidate |",
            "| --- | ---: | ---: |",
            f"| Recall | {baseline['recall']:.2%} | {candidate['recall']:.2%} |",
            f"| High/Critical Recall | {baseline['high_critical_recall']:.2%} | {candidate['high_critical_recall']:.2%} |",
            f"| False Positive Rate | {baseline['false_positive_rate']:.2%} | {candidate['false_positive_rate']:.2%} |",
            f"| Tokens Used | {baseline['tokens_used']} | {candidate['tokens_used']} |",
            f"| One-shot Verified Fix Rate | {baseline['one_shot_verified_fix_rate']:.2%} | {candidate['one_shot_verified_fix_rate']:.2%} |",
            f"| Tokens / Verified Fix | {baseline['tokens_per_verified_fix'] or 0:.1f} | {candidate['tokens_per_verified_fix'] or 0:.1f} |",
            f"| Net Tokens Saved | {baseline['net_tokens_saved']} | {candidate['net_tokens_saved']} |",
            f"| Duration (s) | {baseline['duration_seconds']:.1f} | {candidate['duration_seconds']:.1f} |",
            "",
            "## Thresholds",
            "",
            f"- High/Critical recall up 20%: `{thresholds['high_critical_recall_up_20pct']}`",
            f"- False positive rate not worse: `{thresholds['false_positive_rate_not_worse']}`",
            f"- Token cost down 30%: `{thresholds['token_cost_down_30pct']}`",
            "",
            "## Suite Aggregates",
            "",
        ]

        for suite, metrics in suite_aggregates.items():
            lines.extend(
                [
                    f"### {suite}",
                    "",
                    f"- Scenarios: {metrics.get('scenario_count', 0)}",
                    f"- Candidate measurable wins: {metrics.get('candidate_measurable_wins', 0)}",
                    (
                        f"- Prompt overhead ratio: {metrics['prompt_overhead_ratio']:.2f}"
                        if metrics.get("prompt_overhead_ratio") is not None
                        else "- Prompt overhead ratio: n/a"
                    ),
                    (
                        f"- External lesson usage: related={metrics['candidate'].get('related_lesson_usage_count', 0)}, "
                        f"model-pack={metrics['candidate'].get('model_pack_lesson_usage_count', 0)}"
                    ),
                    "",
                ]
            )

        lines.extend(
            [
                "## Benchmark Gates",
                "",
            ]
        )
        for gate_name, gate in dict(benchmark_gates.get("gates", {})).items():
            lines.append(f"- `{gate_name}`: `{gate['passed']}`")
            lines.append(f"  Summary: {gate.get('summary', 'n/a')}")

        lines.extend(
            [
                "",
                "## Scenarios",
                "",
            ]
        )

        for scenario in report["scenarios"]:
            lines.extend(
                [
                    f"### {scenario['scenario']}",
                    "",
                    f"- Suite: `{scenario.get('suite', 'core-review')}`",
                    (
                        f"- Description: {scenario['description']}"
                        if scenario.get("description")
                        else "- Description: n/a"
                    ),
                    f"- Baseline recall: {scenario['baseline']['recall']:.2%}",
                    f"- Candidate recall: {scenario['candidate']['recall']:.2%}",
                    f"- Baseline false positives: {scenario['baseline']['false_positive_count']}",
                    f"- Candidate false positives: {scenario['candidate']['false_positive_count']}",
                    "",
                ]
            )

        history = report.get("history")
        if history:
            lines.extend(
                [
                    "## History Replay",
                    "",
                    f"- Available: `{history.get('available', False)}`",
                    f"- Review runs: {history.get('review_runs', 0)}",
                ]
            )
            if history.get("available"):
                lines.extend(
                    [
                        f"- Average token cost: {history.get('average_token_cost', 0):.1f}",
                        f"- Average duration (ms): {history.get('average_duration_ms', 0):.1f}",
                        f"- Average findings count: {history.get('average_findings_count', 0):.1f}",
                    ]
                )

        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    @staticmethod
    def _scenario_counts_by_suite(scenarios: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scenario in scenarios:
            suite = str(scenario.get("suite", "core-review"))
            counts[suite] = counts.get(suite, 0) + 1
        return counts

    def _get_client(self) -> M27Client:
        if self.m27_client is None:
            self.m27_client = M27Client()
        return self.m27_client

    def _resolve_fixture_path(self, relative_path: str) -> Path:
        return (self.fixture_root / relative_path).resolve()

    def _resolve_fixture_project_root(self, scenario: BenchmarkScenario) -> Path:
        if scenario.project_root:
            return self._resolve_fixture_path(scenario.project_root)
        target_path = Path(scenario.target_path)
        return target_path.parent if target_path.is_file() else target_path

    def _target_relative_path(self, scenario: BenchmarkScenario) -> Path:
        target_path = Path(scenario.target_path)
        project_root = self._resolve_fixture_project_root(scenario)
        try:
            return target_path.relative_to(project_root)
        except ValueError:
            return Path(target_path.name)

    @staticmethod
    def _infer_languages(target_path: Path) -> list[str]:
        suffix = target_path.suffix.lower()
        if suffix == ".py":
            return ["Python"]
        if suffix in {".ts", ".tsx"}:
            return ["TypeScript"]
        if suffix in {".js", ".jsx"}:
            return ["JavaScript"]
        return []

    @staticmethod
    def _primary_language_label(languages: list[str]) -> str | None:
        return languages[0] if languages else None
