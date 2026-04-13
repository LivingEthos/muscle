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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..m27_client import M27Client
from ..project_memory import ProjectMemory
from .review_controller import ReviewController
from .types import ReviewConfig, ReviewIssue, ReviewMode, Severity

logger = logging.getLogger(__name__)

BENCHMARK_REPORTS_DIR = Path(".muscle/reports/benchmarks")
FIXTURE_ROOT = Path(__file__).parent / "benchmark_fixtures"

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
    target_path: str
    false_positive_severity: str
    expected_findings: list[BenchmarkExpectedFinding]


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
        self.m27_client = m27_client

    def run_benchmark(
        self,
        baseline: str = "legacy",
        candidate: str = "review-smart",
        include_history: bool = True,
    ) -> dict[str, Any]:
        scenarios = self._load_scenarios()
        benchmark_started = datetime.now()
        report: dict[str, Any] = {
            "started_at": benchmark_started.isoformat(),
            "baseline": baseline,
            "candidate": candidate,
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

    def _load_scenarios(self) -> list[BenchmarkScenario]:
        manifest_path = self.fixture_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
            scenarios.append(
                BenchmarkScenario(
                    name=item["name"],
                    target_path=scenario_target,
                    false_positive_severity=item.get("false_positive_severity", "medium"),
                    expected_findings=expected_findings,
                )
            )
        return scenarios

    def _run_scenario(self, scenario: BenchmarkScenario, workflow_name: str) -> dict[str, Any]:
        controller = ReviewController(
            config=ReviewConfig(
                target_path=scenario.target_path,
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
            project_path=str(self.project_path),
        )
        context = controller.run()
        review_result = controller.get_review_result()
        if review_result is None:
            msg = f"Benchmark run produced no review result for {scenario.name}"
            raise RuntimeError(msg)
        return {
            "workflow_name": workflow_name,
            "issues": review_result.issues,
            "duration_seconds": context.stats.duration_seconds,
            "tokens_used": context.stats.tokens_used,
            "finding_count": len(review_result.issues),
        }

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
            "target_path": scenario.target_path,
            "baseline": baseline_metrics,
            "candidate": candidate_metrics,
        }

    def _evaluate_run_against_scenario(
        self,
        scenario: BenchmarkScenario,
        run_result: dict[str, Any],
    ) -> dict[str, Any]:
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

        expected_count = len(scenario.expected_findings)
        high_critical_expected_count = len(expected_high_critical)
        return {
            "workflow_name": run_result["workflow_name"],
            "finding_count": run_result["finding_count"],
            "tokens_used": run_result["tokens_used"],
            "duration_seconds": run_result["duration_seconds"],
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
        }

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

        lines = [
            "# MUSCLE Review Benchmark",
            "",
            f"- Baseline: `{report['baseline']}`",
            f"- Candidate: `{report['candidate']}`",
            "",
            "## Aggregate",
            "",
            "| Metric | Baseline | Candidate |",
            "| --- | ---: | ---: |",
            f"| Recall | {baseline['recall']:.2%} | {candidate['recall']:.2%} |",
            f"| High/Critical Recall | {baseline['high_critical_recall']:.2%} | {candidate['high_critical_recall']:.2%} |",
            f"| False Positive Rate | {baseline['false_positive_rate']:.2%} | {candidate['false_positive_rate']:.2%} |",
            f"| Tokens Used | {baseline['tokens_used']} | {candidate['tokens_used']} |",
            f"| Duration (s) | {baseline['duration_seconds']:.1f} | {candidate['duration_seconds']:.1f} |",
            "",
            "## Thresholds",
            "",
            f"- High/Critical recall up 20%: `{thresholds['high_critical_recall_up_20pct']}`",
            f"- False positive rate not worse: `{thresholds['false_positive_rate_not_worse']}`",
            f"- Token cost down 30%: `{thresholds['token_cost_down_30pct']}`",
            "",
            "## Scenarios",
            "",
        ]

        for scenario in report["scenarios"]:
            lines.extend(
                [
                    f"### {scenario['scenario']}",
                    "",
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

    def _get_client(self) -> M27Client:
        if self.m27_client is None:
            self.m27_client = M27Client()
        return self.m27_client
