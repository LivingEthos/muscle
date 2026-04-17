"""
Unit tests for review_benchmark.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tools.muscle.code_review import review_benchmark as benchmark_module
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


def _metrics(
    *,
    workflow_name: str,
    recall: float,
    high_critical_recall: float,
    false_positive_rate: float,
    tokens_used: int,
    finding_count: int = 1,
    duration_seconds: float = 1.0,
    lesson_usage_count: int = 0,
    related_lesson_usage_count: int = 0,
    model_pack_lesson_usage_count: int = 0,
) -> dict[str, object]:
    false_positive_count = int(round(false_positive_rate * max(finding_count, 1)))
    return {
        "workflow_name": workflow_name,
        "matched_expected": int(round(recall)),
        "expected_total": 1,
        "recall": recall,
        "matched_high_critical": int(round(high_critical_recall)),
        "high_critical_total": 1,
        "high_critical_recall": high_critical_recall,
        "false_positive_count": false_positive_count,
        "false_positive_rate": false_positive_rate,
        "finding_count": finding_count,
        "tokens_used": tokens_used,
        "duration_seconds": duration_seconds,
        "verified_fix_count": 0,
        "one_shot_verified_fix_count": 0,
        "tokens_per_verified_fix": None,
        "net_tokens_saved": 0,
        "lesson_usage_summary": {
            "total_events": lesson_usage_count,
            "by_source": {
                **({"related": related_lesson_usage_count} if related_lesson_usage_count else {}),
                **(
                    {"model-pack": model_pack_lesson_usage_count}
                    if model_pack_lesson_usage_count
                    else {}
                ),
            },
            "sources": [],
            "outcomes": {},
        },
        "lesson_usage_count": lesson_usage_count,
        "related_lesson_usage_count": related_lesson_usage_count,
        "model_pack_lesson_usage_count": model_pack_lesson_usage_count,
    }


def _scenario_result(
    *,
    name: str,
    suite: str,
    baseline: dict[str, object],
    candidate: dict[str, object],
) -> dict[str, object]:
    return {
        "scenario": name,
        "suite": suite,
        "description": f"{suite} scenario",
        "tags": [suite],
        "target_path": f"/tmp/{name}.py",
        "baseline": baseline,
        "candidate": candidate,
    }


class TestReviewBenchmarkRunner:
    def test_load_real_fixture_manifest_includes_project_first_suites(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]

        scenarios = runner._load_scenarios()

        suites = {scenario.suite for scenario in scenarios}
        assert runner.fixture_manifest_version == 2
        assert {
            "core-review",
            "neutral-baseline",
            "related-project",
            "unrelated-project",
            "model-pack",
        } <= suites
        assert set(benchmark_module.SUPPORTED_BENCHMARK_SUITES) >= {"all", *suites}

    def test_load_scenarios_can_filter_by_suite(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]

        scenarios = runner._load_scenarios(suite="related-project")

        assert scenarios
        assert all(scenario.suite == "related-project" for scenario in scenarios)

    def test_build_scenario_workspace_bootstraps_related_and_model_pack_state(
        self,
        tmp_path: Path,
    ):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenarios = runner._load_scenarios()

        related = next(s for s in scenarios if s.name == "related_project_payment_parser")
        prepared_related = runner._build_scenario_workspace(related, tmp_path / "related")
        related_pm = prepared_related.lesson_resolver.project_memory
        related_lessons = related_pm.list_transferred_lessons(
            project_path=prepared_related.project_path
        )

        assert Path(prepared_related.target_path).exists()
        assert related_lessons
        assert related_lessons[0]["validation_status"] == "provisional"

        model_pack = next(s for s in scenarios if s.name == "model_pack_api_response_parser")
        prepared_model = runner._build_scenario_workspace(model_pack, tmp_path / "model")
        installed_packs = prepared_model.system_db.list_model_packs()
        pack_lessons = prepared_model.system_db.get_model_pack_lessons("minimax/m2.7@1")

        assert installed_packs
        assert installed_packs[0]["canonical_model_key"] == "minimax/m2.7@1"
        assert pack_lessons
        assert pack_lessons[0]["lesson_key"] == "python-api-schema-guard"

    def test_issue_matching_respects_file_severity_and_matchers(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenario = benchmark_module.BenchmarkScenario(
            name="sample",
            suite="core-review",
            target_path=str(tmp_path / "sample.py"),
            false_positive_severity="medium",
            expected_findings=[
                benchmark_module.BenchmarkExpectedFinding(
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
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenario = benchmark_module.BenchmarkScenario(
            name="sample",
            suite="core-review",
            target_path=str(tmp_path / "sample.py"),
            false_positive_severity="medium",
            expected_findings=[
                benchmark_module.BenchmarkExpectedFinding(
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
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenarios = [
            benchmark_module.BenchmarkScenario(
                name="sample",
                suite="core-review",
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
        assert json_payload["suite"] == "all"
        assert json_payload["fixture_manifest_version"] == runner.fixture_manifest_version

    def test_release_gates_pass_with_required_evidence(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenarios = [
            benchmark_module.BenchmarkScenario(
                name=f"{suite}-sample",
                suite=suite,
                target_path=str(tmp_path / f"{suite}.py"),
                false_positive_severity="medium",
                expected_findings=[],
            )
            for suite in (
                "core-review",
                "neutral-baseline",
                "unrelated-project",
                "related-project",
                "model-pack",
            )
        ]
        scenario_results = [
            _scenario_result(
                name="core-review-sample",
                suite="core-review",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.20,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="neutral-baseline-sample",
                suite="neutral-baseline",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="unrelated-project-sample",
                suite="unrelated-project",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="related-project-sample",
                suite="related-project",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=0.0,
                    high_critical_recall=0.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=125,
                    lesson_usage_count=2,
                    related_lesson_usage_count=2,
                ),
            ),
            _scenario_result(
                name="model-pack-sample",
                suite="model-pack",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=0.0,
                    high_critical_recall=0.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=130,
                    lesson_usage_count=1,
                    model_pack_lesson_usage_count=1,
                ),
            ),
        ]

        with (
            patch.object(runner, "_load_scenarios", return_value=scenarios),
            patch.object(runner, "_compare_runs", side_effect=scenario_results),
            patch.object(runner, "_run_scenario", return_value={}),
        ):
            report = runner.run_benchmark(include_history=False)

        assert report["suite_aggregates"]["related-project"]["candidate_measurable_wins"] == 1
        assert report["benchmark_gates"]["overall_passed"] is True
        release_evidence = runner.build_release_evidence(
            report,
            operational_invariants={
                "offline_guardrails": {
                    "checked": True,
                    "passed": True,
                    "summary": "Offline guardrails passed.",
                    "details": {"targets": ["tests/unit/test_cli_run_offline.py"]},
                }
            },
        )
        assert release_evidence["release_gates"]["overall_passed"] is True

    def test_release_gates_fail_on_missing_model_pack_or_related_win(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenarios = [
            benchmark_module.BenchmarkScenario(
                name=f"{suite}-sample",
                suite=suite,
                target_path=str(tmp_path / f"{suite}.py"),
                false_positive_severity="medium",
                expected_findings=[],
            )
            for suite in ("core-review", "neutral-baseline", "unrelated-project", "related-project")
        ]
        scenario_results = [
            _scenario_result(
                name="core-review-sample",
                suite="core-review",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="neutral-baseline-sample",
                suite="neutral-baseline",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="unrelated-project-sample",
                suite="unrelated-project",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="related-project-sample",
                suite="related-project",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=120,
                ),
            ),
        ]

        with (
            patch.object(runner, "_load_scenarios", return_value=scenarios),
            patch.object(runner, "_compare_runs", side_effect=scenario_results),
            patch.object(runner, "_run_scenario", return_value={}),
        ):
            report = runner.run_benchmark(include_history=False)

        gates = report["benchmark_gates"]["gates"]
        assert gates["related_project_measurable_win"]["passed"] is False
        assert gates["model_pack_measurable_win"]["passed"] is False
        release_evidence = runner.build_release_evidence(
            report,
            operational_invariants={
                "offline_guardrails": {
                    "checked": True,
                    "passed": True,
                    "summary": "Offline guardrails passed.",
                    "details": {},
                }
            },
        )
        assert release_evidence["release_gates"]["overall_passed"] is False

    def test_report_persists_gate_evidence_in_json_and_markdown(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenarios = [
            benchmark_module.BenchmarkScenario(
                name=f"{suite}-sample",
                suite=suite,
                target_path=str(tmp_path / f"{suite}.py"),
                false_positive_severity="medium",
                expected_findings=[],
            )
            for suite in (
                "core-review",
                "neutral-baseline",
                "unrelated-project",
                "related-project",
                "model-pack",
            )
        ]
        scenario_results = [
            _scenario_result(
                name="core-review-sample",
                suite="core-review",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.20,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="neutral-baseline-sample",
                suite="neutral-baseline",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="unrelated-project-sample",
                suite="unrelated-project",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=110,
                ),
            ),
            _scenario_result(
                name="related-project-sample",
                suite="related-project",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=0.0,
                    high_critical_recall=0.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=125,
                    lesson_usage_count=2,
                    related_lesson_usage_count=2,
                ),
            ),
            _scenario_result(
                name="model-pack-sample",
                suite="model-pack",
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=0.0,
                    high_critical_recall=0.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=130,
                    lesson_usage_count=1,
                    model_pack_lesson_usage_count=1,
                ),
            ),
        ]

        with (
            patch.object(runner, "_load_scenarios", return_value=scenarios),
            patch.object(runner, "_compare_runs", side_effect=scenario_results),
            patch.object(runner, "_run_scenario", return_value={}),
        ):
            report = runner.run_benchmark(include_history=False)

        release_evidence = runner.build_release_evidence(
            report,
            operational_invariants={
                "offline_guardrails": {
                    "checked": True,
                    "passed": True,
                    "summary": "Offline guardrails passed.",
                    "details": {"targets": ["tests/unit/test_cli_run_offline.py"]},
                }
            },
        )
        paths = runner.write_release_evidence(release_evidence)

        assert Path(paths["json"]).exists()
        assert Path(paths["markdown"]).exists()
        payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
        assert payload["release_gates"]["overall_passed"] is True
        assert "benchmark_report_paths" in payload
        markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
        assert "project_only_no_regression" in markdown
        assert "normal_paths_offline_safe" in markdown
