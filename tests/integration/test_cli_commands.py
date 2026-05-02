"""
Integration tests for CLI commands.

Tests all CLI command groups via Click's CliRunner with mocked backends.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tools.muscle.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def env_with_key() -> dict:
    env = os.environ.copy()
    env["MINIMAX_API_KEY"] = "test-key-12345"
    return env


# ---------------------------------------------------------------------------
# Review command group
# ---------------------------------------------------------------------------


class TestReviewCLI:
    """Tests for the review command and its options."""

    def test_review_all_modes(self, runner: CliRunner, env_with_key: dict):
        """All review modes should be accepted without errors."""
        modes = ["review", "auto-fix", "plan", "hybrid"]

        for mode in modes:
            mock_result = MagicMock()
            mock_result.session_id = "test-001"
            mock_result.target_path = "/tmp/test"
            mock_result.issues = []
            mock_result.critical_count = 0
            mock_result.high_count = 0
            mock_result.medium_count = 0
            mock_result.low_count = 0
            mock_result.info_count = 0

            mock_ctx = MagicMock()
            mock_ctx.handoff_plan = None

            mock_controller = MagicMock()
            mock_controller.run.return_value = mock_ctx
            mock_controller.get_review_result.return_value = mock_result

            with patch(
                "tools.muscle.code_review.review_controller.ReviewController",
                return_value=mock_controller,
            ):
                result = runner.invoke(
                    cli,
                    ["review", "--target", "/tmp/test", "--mode", mode],
                    env=env_with_key,
                )
                assert result.exit_code == 0, f"Mode {mode} failed: {result.output}"

    def test_review_json_output(self, runner: CliRunner, env_with_key: dict):
        """JSON output format should produce valid JSON only on stdout."""
        mock_result = MagicMock()
        mock_result.session_id = "json-001"
        mock_result.target_path = "/tmp/test"
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0
        mock_result.workflow_name = "review-smart"
        mock_result.execution_mode = "local"

        mock_ctx = MagicMock()
        mock_ctx.handoff_plan = None
        mock_ctx.stats.duration_seconds = 0.0
        mock_ctx.stats.tokens_used = 0

        mock_controller = MagicMock()
        mock_controller.run.return_value = mock_ctx
        mock_controller.get_review_result.return_value = mock_result

        with patch("tools.muscle.code_review.ReviewController", return_value=mock_controller):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--format", "json"],
                env=env_with_key,
            )
            assert result.exit_code == 0
            payload = json.loads(result.output)
            assert payload["session_id"] == "json-001"
            assert payload["summary"]["critical"] == 0
            assert "Starting code review session" not in result.output
            assert "Review Complete" not in result.output

    def test_review_no_api_key(self, runner: CliRunner):
        """Review should fail gracefully without API key."""
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("MINIMAX_API_KEY", None)

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test"],
            env=env,
        )
        assert result.exit_code != 0
        assert "MINIMAX_API_KEY" in result.output

    def test_review_severity_levels(self, runner: CliRunner, env_with_key: dict):
        """All severity thresholds should be accepted."""
        for severity in ["critical", "high", "medium", "low", "info"]:
            mock_ctx = MagicMock()
            mock_ctx.handoff_plan = None

            mock_result = MagicMock()
            mock_result.session_id = "sev-001"
            mock_result.target_path = "/tmp/test"
            mock_result.issues = []
            mock_result.critical_count = 0
            mock_result.high_count = 0
            mock_result.medium_count = 0
            mock_result.low_count = 0
            mock_result.info_count = 0

            mock_controller = MagicMock()
            mock_controller.run.return_value = mock_ctx
            mock_controller.get_review_result.return_value = mock_result

            with patch(
                "tools.muscle.code_review.review_controller.ReviewController",
                return_value=mock_controller,
            ):
                result = runner.invoke(
                    cli,
                    ["review", "--target", "/tmp/test", "--severity", severity],
                    env=env_with_key,
                )
                assert result.exit_code == 0, f"Severity {severity} failed: {result.output}"


# ---------------------------------------------------------------------------
# Knowledge Base commands
# ---------------------------------------------------------------------------


class TestKBCLI:
    """Tests for the kb command group."""

    def test_kb_stats(self, runner: CliRunner):
        """kb stats should display statistics."""
        with patch("tools.muscle.strategy_kb.GlobalKnowledgeBase") as mock_kb_cls:
            mock_kb = MagicMock()
            mock_kb.strategy_kb.get_statistics.return_value = {
                "total_strategies": 10,
                "total_usage": 50,
                "average_success_rate": 0.75,
            }
            mock_kb_cls.return_value = mock_kb

            result = runner.invoke(cli, ["kb", "stats"])
            assert result.exit_code == 0

    def test_kb_export_import(self, runner: CliRunner, tmp_path: Path):
        """kb export then import should round-trip."""
        export_file = str(tmp_path / "kb_export.json")

        with patch("tools.muscle.strategy_kb.GlobalKnowledgeBase") as mock_kb_cls:
            mock_kb = MagicMock()
            mock_kb.strategy_kb.export_to_json.return_value = None
            mock_kb.strategy_kb.import_from_json.return_value = 5
            mock_kb_cls.return_value = mock_kb

            # Export
            result = runner.invoke(cli, ["kb", "export", export_file])
            assert result.exit_code == 0

            # Create a dummy file for import
            (tmp_path / "kb_export.json").write_text("[]")

            # Import
            result = runner.invoke(cli, ["kb", "import", export_file])
            assert result.exit_code == 0
            assert "Imported" in result.output

    def test_kb_clear_with_force(self, runner: CliRunner):
        """kb clear --force should skip confirmation."""
        with patch("tools.muscle.strategy_kb.GlobalKnowledgeBase") as mock_kb_cls:
            mock_kb = MagicMock()
            mock_kb.strategy_kb.clear.return_value = None
            mock_kb_cls.return_value = mock_kb

            result = runner.invoke(cli, ["kb", "clear", "--force"])
            assert result.exit_code == 0
            assert "cleared" in result.output.lower()

    def test_kb_knowledge_add(self, runner: CliRunner):
        """kb knowledge-add should add a strategy."""
        with patch("tools.muscle.cli.GlobalKnowledgeBase") as mock_kb_cls:
            mock_kb = MagicMock()
            mock_kb.add_solution.return_value = 42
            mock_kb_cls.return_value = mock_kb

            result = runner.invoke(
                cli,
                [
                    "kb",
                    "knowledge-add",
                    "-p",
                    "TypeError in handler",
                    "-s",
                    "Add type checking",
                ],
            )
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Cost commands
# ---------------------------------------------------------------------------


class TestCostCLI:
    """Tests for the cost command group."""

    def test_cost_stats(self, runner: CliRunner):
        """cost stats should show cache statistics."""
        with patch("tools.muscle.cost_optimizer.CostOptimizer") as mock_cls:
            mock_opt = MagicMock()
            mock_opt.get_cache_stats.return_value = {
                "cached_items": 25,
                "total_size_bytes": 102400,
                "total_size_mb": 0.1,
            }
            mock_cls.return_value = mock_opt

            result = runner.invoke(cli, ["cost", "stats"])
            assert result.exit_code == 0

    def test_cost_clear_with_force(self, runner: CliRunner):
        """cost clear --force should clear cache without error."""
        result = runner.invoke(cli, ["cost", "clear", "--force"])
        assert result.exit_code == 0
        assert "Cleared" in result.output


# ---------------------------------------------------------------------------
# Improve commands
# ---------------------------------------------------------------------------


class TestImproveCLI:
    """Tests for the improve command group."""

    def test_improve_report(self, runner: CliRunner):
        """improve report should show self-review output."""
        with patch("tools.muscle.self_improver.SelfImprover") as mock_cls:
            mock_improver = MagicMock()
            mock_improver.run_self_review.return_value = "Self-improvement report content"
            mock_cls.return_value = mock_improver

            result = runner.invoke(cli, ["improve", "report"])
            assert result.exit_code == 0

    def test_improve_export_import(self, runner: CliRunner, tmp_path: Path):
        """improve export/import should work."""
        export_file = str(tmp_path / "improve_export.json")

        with patch("tools.muscle.self_improver.SelfImprover") as mock_cls:
            mock_improver = MagicMock()
            mock_improver.export_data.return_value = None
            mock_improver.import_data.return_value = 3
            mock_cls.return_value = mock_improver

            result = runner.invoke(cli, ["improve", "export", export_file])
            assert result.exit_code == 0

            (tmp_path / "improve_export.json").write_text('{"outcomes": []}')
            result = runner.invoke(cli, ["improve", "import", export_file])
            assert result.exit_code == 0

    def test_improve_clear_with_force(self, runner: CliRunner):
        """improve clear --force should clear data."""
        with patch("tools.muscle.self_improver.SelfImprover") as mock_cls:
            mock_improver = MagicMock()
            mock_cls.return_value = mock_improver

            result = runner.invoke(cli, ["improve", "clear", "--force"])
            assert result.exit_code == 0

    def test_improve_prompt(self, runner: CliRunner):
        """improve prompt should generate a prompt."""
        with patch("tools.muscle.self_improver.SelfImprover") as mock_cls:
            mock_improver = MagicMock()
            mock_improver.generate_improved_system_prompt.return_value = "You are MUSCLE, improved."
            mock_cls.return_value = mock_improver

            result = runner.invoke(cli, ["improve", "prompt"])
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Long evaluation commands
# ---------------------------------------------------------------------------


class TestLongEvalCLI:
    """Tests for the long-eval command group."""

    def test_long_eval_run(self, runner: CliRunner):
        """long-eval run should execute a deep evaluation."""
        with patch("tools.muscle.code_review.long_eval_runner.LongEvalRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run_long_eval.return_value = {
                "total_issues": 3,
                "duration_seconds": 12.5,
                "critical_issues": [],
                "high_issues": [],
            }
            mock_cls.return_value = mock_runner

            result = runner.invoke(cli, ["long-eval", "run"])
            assert result.exit_code == 0

    def test_long_eval_reports(self, runner: CliRunner):
        """long-eval reports should list recent reports."""
        with patch("tools.muscle.code_review.long_eval_runner.LongEvalRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.list_reports.return_value = []
            mock_cls.return_value = mock_runner

            result = runner.invoke(cli, ["long-eval", "reports"])
            assert result.exit_code == 0

    def test_long_eval_cleanup_with_force(self, runner: CliRunner):
        """long-eval cleanup --force should remove old reports."""
        with patch("tools.muscle.code_review.long_eval_runner.LongEvalRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.cleanup_old_reports.return_value = 2
            mock_cls.return_value = mock_runner

            result = runner.invoke(cli, ["long-eval", "cleanup", "--force"])
            assert result.exit_code == 0

    def test_long_eval_benchmark(self, runner: CliRunner):
        """long-eval benchmark should execute the benchmark harness."""
        with patch("tools.muscle.code_review.review_benchmark.ReviewBenchmarkRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run_benchmark.return_value = {
                "aggregate": {
                    "baseline": {
                        "high_critical_recall": 0.5,
                        "false_positive_rate": 0.2,
                        "tokens_used": 100,
                    },
                    "candidate": {
                        "high_critical_recall": 0.8,
                        "false_positive_rate": 0.1,
                        "tokens_used": 70,
                    },
                },
                "thresholds": {
                    "high_critical_recall_up_20pct": True,
                    "false_positive_rate_not_worse": True,
                    "token_cost_down_30pct": True,
                },
                "report_paths": {"json": "/tmp/report.json"},
            }
            mock_cls.return_value = mock_runner

            result = runner.invoke(cli, ["long-eval", "benchmark", "--suite", "related-project"])
            assert result.exit_code == 0
            mock_runner.run_benchmark.assert_called_once_with(
                baseline="legacy",
                candidate="review-smart",
                include_history=True,
                suite="related-project",
            )

    def test_long_eval_benchmark_enforce_gates_failure(self, runner: CliRunner):
        """long-eval benchmark --enforce-gates should fail when release gates fail."""
        with patch("tools.muscle.code_review.review_benchmark.ReviewBenchmarkRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run_benchmark.return_value = {
                "aggregate": {
                    "baseline": {
                        "high_critical_recall": 0.5,
                        "false_positive_rate": 0.2,
                        "tokens_used": 100,
                    },
                    "candidate": {
                        "high_critical_recall": 0.5,
                        "false_positive_rate": 0.2,
                        "tokens_used": 100,
                    },
                },
                "thresholds": {
                    "high_critical_recall_up_20pct": False,
                    "false_positive_rate_not_worse": True,
                    "token_cost_down_30pct": False,
                },
                "benchmark_gates": {"overall_passed": False, "gates": {}},
                "report_paths": {"json": "/tmp/report.json"},
            }
            mock_runner.build_release_evidence.return_value = {
                "release_gates": {
                    "overall_passed": False,
                    "gates": {
                        "related_project_measurable_win": {"passed": False},
                        "model_pack_measurable_win": {"passed": False},
                    },
                }
            }
            mock_runner.write_release_evidence.return_value = {"json": "/tmp/release.json"}
            mock_cls.return_value = mock_runner

            with patch(
                "tools.muscle.cli._run_benchmark_release_invariants",
                return_value={"checked": True, "passed": True, "summary": "ok", "details": {}},
            ):
                result = runner.invoke(cli, ["long-eval", "benchmark", "--enforce-gates"])

            assert result.exit_code != 0
            assert "Release gates failed" in result.output


# ---------------------------------------------------------------------------
# Version and help
# ---------------------------------------------------------------------------


class TestCLIMisc:
    """Tests for version, help, and edge cases."""

    def test_version(self, runner: CliRunner):
        """--version should show version string."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self, runner: CliRunner):
        """--help should show all commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "MUSCLE" in result.output

    def test_review_help(self, runner: CliRunner):
        """review --help should show review options."""
        result = runner.invoke(cli, ["review", "--help"])
        assert result.exit_code == 0
        assert "--target" in result.output
        assert "--mode" in result.output

    def test_kb_help(self, runner: CliRunner):
        """kb --help should show kb subcommands."""
        result = runner.invoke(cli, ["kb", "--help"])
        assert result.exit_code == 0

    def test_invalid_command(self, runner: CliRunner):
        """Invalid command should show error."""
        result = runner.invoke(cli, ["nonexistent-command"])
        assert result.exit_code != 0
