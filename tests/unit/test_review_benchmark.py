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
    prompt_tokens_used: int = 0,
    prompt_context_chars: int = 0,
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
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
        "llm_call_count": 1
        if prompt_tokens_used or llm_input_tokens or prompt_context_chars
        else 0,
        "llm_input_tokens": llm_input_tokens or prompt_tokens_used,
        "llm_output_tokens": llm_output_tokens,
        "prompt_context_chars": prompt_context_chars,
        "prompt_token_estimate": (prompt_context_chars + 3) // 4 if prompt_context_chars else 0,
        "prompt_tokens_used": prompt_tokens_used or llm_input_tokens,
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
        assert prepared_related.project_path == prepared_related.lesson_resolver.project_path
        related_pm = prepared_related.lesson_resolver.project_memory
        related_lessons = related_pm.list_transferred_lessons(
            project_path=prepared_related.project_path
        )

        assert Path(prepared_related.target_path).exists()
        assert related_lessons
        assert related_lessons[0]["validation_status"] == "provisional"
        related_result = prepared_related.lesson_resolver.resolve_for_prompt(
            query_text="payment schema validation",
            stage="committee_review",
            session_id="sess-related",
            language="Python",
        )
        assert any(lesson.source == "related" for lesson in related_result.lessons)
        related_usage = related_pm.list_lesson_usage_events(
            project_path=prepared_related.project_path,
            session_id="sess-related",
        )
        assert any(event["lesson_source"] == "related" for event in related_usage)

        unrelated = next(s for s in scenarios if s.name == "unrelated_project_payment_parser")
        prepared_unrelated = runner._build_scenario_workspace(unrelated, tmp_path / "unrelated")
        unrelated_result = prepared_unrelated.lesson_resolver.resolve_for_prompt(
            query_text="payment schema validation",
            stage="committee_review",
            session_id="sess-unrelated",
            language="Python",
        )
        assert all(lesson.source != "related" for lesson in unrelated_result.lessons)

        model_pack = next(s for s in scenarios if s.name == "model_pack_api_response_parser")
        prepared_model = runner._build_scenario_workspace(model_pack, tmp_path / "model")
        installed_packs = prepared_model.system_db.list_model_packs()
        pack_lessons = prepared_model.system_db.get_model_pack_lessons("minimax/m2.7@1")

        assert installed_packs
        assert installed_packs[0]["canonical_model_key"] == "minimax/m2.7@1"
        assert pack_lessons
        assert pack_lessons[0]["lesson_key"] == "python-api-schema-guard"
        model_result = prepared_model.lesson_resolver.resolve_for_prompt(
            query_text="nested api schema validation",
            stage="committee_review",
            session_id="sess-model-pack",
            language="Python",
        )
        assert any(lesson.source == "model-pack" for lesson in model_result.lessons)
        model_usage = prepared_model.lesson_resolver.project_memory.list_lesson_usage_events(
            project_path=prepared_model.project_path,
            session_id="sess-model-pack",
        )
        assert any(event["lesson_source"] == "model-pack" for event in model_usage)

    def test_legacy_benchmark_runs_without_lesson_overlay(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenario = next(
            s for s in runner._load_scenarios() if s.name == "related_project_payment_parser"
        )
        prepared = runner._build_scenario_workspace(scenario, tmp_path / "prepared")

        assert runner._lesson_resolver_for_workflow(prepared, "legacy") is None
        assert (
            runner._lesson_resolver_for_workflow(prepared, "review-smart")
            is prepared.lesson_resolver
        )

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
        assert "meta_harness" in json_payload

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
        assert "promotion_rule" in report["meta_harness"]
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

    def test_prompt_overhead_gate_uses_prompt_side_telemetry(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]
        scenario_results = [
            _scenario_result(
                name=f"{suite}-sample",
                suite=suite,
                baseline=_metrics(
                    workflow_name="legacy",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=100,
                    prompt_tokens_used=100,
                ),
                candidate=_metrics(
                    workflow_name="review-smart",
                    recall=1.0,
                    high_critical_recall=1.0,
                    false_positive_rate=0.10,
                    tokens_used=250,
                    prompt_tokens_used=110,
                ),
            )
            for suite in (
                "core-review",
                "neutral-baseline",
                "unrelated-project",
                "related-project",
                "model-pack",
            )
        ]

        suite_aggregates = runner._aggregate_by_suite(scenario_results)
        report = {"suite_aggregates": suite_aggregates}

        gate = runner._evaluate_benchmark_gates(report)["gates"]["prompt_overhead_within_budget"]

        assert gate["passed"] is True
        assert suite_aggregates["core-review"]["prompt_overhead_ratio"] == 1.1
        assert suite_aggregates["core-review"]["token_overhead_ratio"] == 2.5
        assert suite_aggregates["core-review"]["prompt_overhead_basis"] == "telemetry_prompt_tokens"

    def test_meta_harness_comparisons_include_host_memory_and_routing(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]

        comparisons = runner._run_meta_harness_comparisons()

        assert comparisons["host_memory"]["available"] is True
        assert (
            comparisons["host_memory"]["candidate_chars"]
            <= comparisons["host_memory"]["baseline_chars"]
        )
        assert "cases" in comparisons["routing"]
        assert "promotion_rule" in comparisons

    def test_host_memory_compaction_unavailable_does_not_crash_benchmark(
        self,
        tmp_path: Path,
    ):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]

        with patch.object(
            benchmark_module,
            "ClaudePublisher",
            side_effect=RuntimeError("database disk image is malformed"),
        ):
            result = runner._benchmark_host_memory_compaction()

        assert result["available"] is False
        assert result["error_type"] == "RuntimeError"
        assert result["candidate_kept"] is False

    def test_history_summary_unavailable_does_not_crash_benchmark(self, tmp_path: Path):
        runner = benchmark_module.ReviewBenchmarkRunner(str(tmp_path), m27_client=object())  # type: ignore[arg-type]

        with patch.object(
            benchmark_module,
            "ProjectMemory",
            side_effect=RuntimeError("database disk image is malformed"),
        ):
            result = runner._history_summary()

        assert result["available"] is False
        assert result["error_type"] == "RuntimeError"
        assert result["review_runs"] == 0

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


def _write_manifest(fixture_root: Path, manifest: dict) -> None:
    fixture_root.mkdir(parents=True, exist_ok=True)
    (fixture_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class TestBenchmarkSecurity:
    def test_path_traversal_target_is_rejected(self, tmp_path: Path):
        fixture_root = tmp_path / "fixtures"
        _write_manifest(
            fixture_root,
            {
                "manifest_version": 2,
                "scenarios": [
                    {"name": "evil", "target_path": "../../etc/passwd"},
                ],
            },
        )
        runner = benchmark_module.ReviewBenchmarkRunner(
            str(tmp_path / "proj"),
            m27_client=object(),
            fixture_root=fixture_root,  # type: ignore[arg-type]
        )
        import pytest

        with pytest.raises(ValueError, match="escapes fixture root"):
            runner._load_scenarios()

    def test_zero_scenarios_hard_fails_for_all(self, tmp_path: Path):
        fixture_root = tmp_path / "fixtures"
        _write_manifest(fixture_root, {"manifest_version": 2, "scenarios": []})
        runner = benchmark_module.ReviewBenchmarkRunner(
            str(tmp_path / "proj"),
            m27_client=object(),
            fixture_root=fixture_root,  # type: ignore[arg-type]
        )
        import pytest

        with pytest.raises(ValueError, match="No benchmark scenarios"):
            runner._load_scenarios(suite="all")

    def test_manifest_missing_required_field_rejected(self, tmp_path: Path):
        fixture_root = tmp_path / "fixtures"
        _write_manifest(
            fixture_root,
            {"manifest_version": 2, "scenarios": [{"name": "no-target"}]},
        )
        runner = benchmark_module.ReviewBenchmarkRunner(
            str(tmp_path / "proj"),
            m27_client=object(),
            fixture_root=fixture_root,  # type: ignore[arg-type]
        )
        import pytest

        with pytest.raises(ValueError, match="missing string 'target_path'"):
            runner._load_scenarios()

    def test_manifest_not_object_rejected(self, tmp_path: Path):
        fixture_root = tmp_path / "fixtures"
        fixture_root.mkdir(parents=True, exist_ok=True)
        (fixture_root / "manifest.json").write_text("[]", encoding="utf-8")
        runner = benchmark_module.ReviewBenchmarkRunner(
            str(tmp_path / "proj"),
            m27_client=object(),
            fixture_root=fixture_root,  # type: ignore[arg-type]
        )
        import pytest

        with pytest.raises(ValueError, match="must be a JSON object"):
            runner._load_scenarios()

    def test_symlink_in_fixture_source_rejected(self, tmp_path: Path):
        fixture_root = tmp_path / "fixtures"
        proj = fixture_root / "proj"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "real.py").write_text("x = 1\n")
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        (proj / "link.txt").symlink_to(outside)
        runner = benchmark_module.ReviewBenchmarkRunner(
            str(tmp_path / "out"),
            m27_client=object(),
            fixture_root=fixture_root,  # type: ignore[arg-type]
        )
        import pytest

        with pytest.raises(ValueError, match="symlink"):
            runner._assert_no_symlinks(proj)
