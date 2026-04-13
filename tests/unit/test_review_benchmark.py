"""
Unit tests for review_benchmark.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tools.muscle.code_review.review_benchmark import (
    BenchmarkExpectedFinding,
    BenchmarkScenario,
    ReviewBenchmarkRunner,
)
from tools.muscle.code_review.types import IssueCategory, ReviewIssue, Severity


def _issue(file_path: str, severity: Severity, title: str, description: str) -> ReviewIssue:
    return ReviewIssue(
        file_path=file_path,
        line_number=1,
        severity=severity,
        category=IssueCategory.SECURITY,
        cwe_id=None,
        title=title,
        description=description,
        code_snippet="",
        auto_fixable=False,
    )


class TestReviewBenchmarkRunner:
    def test_issue_matching_respects_file_severity_and_matchers(self, tmp_path: Path):
        runner = ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenario = BenchmarkScenario(
            name="sample",
            target_path=str(tmp_path / "sample.py"),
            false_positive_severity="medium",
            expected_findings=[
                BenchmarkExpectedFinding(
                    file_path="sample.py",
                    minimum_severity="high",
                    matchers=["sql injection"],
                )
            ],
        )
        issue = _issue(
            str(tmp_path / "sample.py"),
            Severity.HIGH,
            "SQL injection vulnerability",
            "Unsanitized query reaches the database.",
        )

        assert runner._issue_matches_expected(
            issue, scenario.expected_findings[0], scenario.target_path
        )

    def test_evaluate_run_counts_recall_and_false_positives(self, tmp_path: Path):
        runner = ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenario = BenchmarkScenario(
            name="sample",
            target_path=str(tmp_path / "sample.py"),
            false_positive_severity="medium",
            expected_findings=[
                BenchmarkExpectedFinding(
                    file_path="sample.py",
                    minimum_severity="high",
                    matchers=["sql injection"],
                )
            ],
        )
        metrics = runner._evaluate_run_against_scenario(
            scenario,
            {
                "workflow_name": "review-smart",
                "issues": [
                    _issue(
                        str(tmp_path / "sample.py"),
                        Severity.HIGH,
                        "SQL injection vulnerability",
                        "Unsanitized query reaches the database.",
                    ),
                    _issue(
                        str(tmp_path / "sample.py"),
                        Severity.MEDIUM,
                        "Extra warning",
                        "Not part of the manifest.",
                    ),
                ],
                "duration_seconds": 1.5,
                "tokens_used": 20,
                "finding_count": 2,
            },
        )

        assert metrics["recall"] == 1.0
        assert metrics["high_critical_recall"] == 1.0
        assert metrics["false_positive_count"] == 1

    def test_run_benchmark_writes_reports(self, tmp_path: Path):
        runner = ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenarios = [
            BenchmarkScenario(
                name="sample",
                target_path=str(tmp_path / "sample.py"),
                false_positive_severity="medium",
                expected_findings=[],
            )
        ]

        with (
            patch.object(runner, "_load_scenarios", return_value=scenarios),
            patch.object(
                runner,
                "_run_scenario",
                side_effect=[
                    {
                        "workflow_name": "legacy",
                        "issues": [],
                        "duration_seconds": 1.0,
                        "tokens_used": 10,
                        "finding_count": 0,
                    },
                    {
                        "workflow_name": "review-smart",
                        "issues": [],
                        "duration_seconds": 0.5,
                        "tokens_used": 7,
                        "finding_count": 0,
                    },
                ],
            ),
        ):
            report = runner.run_benchmark(include_history=False)

        report_paths = report["report_paths"]
        assert Path(report_paths["json"]).exists()
        assert Path(report_paths["markdown"]).exists()
        json_payload = json.loads(Path(report_paths["json"]).read_text(encoding="utf-8"))
        assert json_payload["baseline"] == "legacy"
        assert json_payload["candidate"] == "review-smart"
