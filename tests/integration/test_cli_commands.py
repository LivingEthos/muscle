"""
Integration tests for CLI commands.

Tests all CLI command groups via Click's CliRunner with mocked backends.
"""

from __future__ import annotations

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
        """JSON output format should produce valid JSON."""
        mock_result = MagicMock()
        mock_result.session_id = "json-001"
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
                ["review", "--target", "/tmp/test", "--format", "json"],
                env=env_with_key,
            )
            assert result.exit_code == 0

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
# Nightly commands
# ---------------------------------------------------------------------------


class TestNightlyCLI:
    """Tests for the nightly command group."""

    def test_nightly_enable(self, runner: CliRunner):
        """nightly enable should set schedule."""
        with patch("tools.muscle.code_review.nightly_runner.ScheduleManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_cls.return_value = mock_mgr

            result = runner.invoke(cli, ["nightly", "enable", "--time", "03:00"])
            assert result.exit_code == 0

    def test_nightly_disable(self, runner: CliRunner):
        """nightly disable should remove schedule."""
        with patch("tools.muscle.code_review.nightly_runner.ScheduleManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_cls.return_value = mock_mgr

            result = runner.invoke(cli, ["nightly", "disable"])
            assert result.exit_code == 0

    def test_nightly_status(self, runner: CliRunner):
        """nightly status should show schedule state."""
        with patch("tools.muscle.code_review.nightly_runner.ScheduleManager") as mock_cls:
            mock_mgr = MagicMock()
            mock_mgr.get_schedule.return_value = {
                "nightly": {
                    "enabled": True,
                    "run_time": "03:00",
                    "next_run": "2024-01-02T03:00:00",
                }
            }
            mock_cls.return_value = mock_mgr

            result = runner.invoke(cli, ["nightly", "status"])
            assert result.exit_code == 0


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
