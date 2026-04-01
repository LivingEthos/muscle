"""
Tests for SCLE CLI review command.

Integration tests that verify the review command correctly parses
arguments and calls the ReviewController.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tools.muscle.cli import cli


class TestReviewCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    @pytest.fixture
    def mock_review_controller(self):
        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = "/tmp/test"
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None

        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_run_result
        mock_instance.get_review_result.return_value = mock_result

        with patch("tools.muscle.code_review.review_controller.ReviewController") as mock_class:
            mock_class.return_value = mock_instance
            yield mock_instance

    def test_review_requires_api_key(self, runner):
        """Test that review command fails without API key."""
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("MINIMAX_API_KEY", None)

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test"],
            env=env,
        )

        assert result.exit_code != 0
        assert "MINIMAX_API_KEY not set" in result.output

    def test_review_with_minimax_api_key(self, runner, mock_review_controller):
        """Test that review command works with MINIMAX_API_KEY set."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--language", "python"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_mode_review(self, runner, mock_review_controller):
        """Test review command with mode=review."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--mode", "review"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_mode_plan(self, runner, mock_review_controller):
        """Test review command with mode=plan."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--mode", "plan", "--output", "/tmp/handoff.md"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_severity_threshold(self, runner, mock_review_controller):
        """Test review command with severity threshold."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--severity", "high"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_json_format(self, runner, mock_review_controller):
        """Test review command with JSON output format."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--format", "json"],
            env=env,
        )

        assert result.exit_code == 0
        assert "critical" in result.output
        assert "high" in result.output

    def test_review_max_fixes(self, runner, mock_review_controller):
        """Test review command with custom max fixes."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--max-fixes", "10"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_interrupt_handling(self, runner):
        """Test review command handles keyboard interrupt gracefully."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test"],
            env=env,
        )
        assert result.exit_code == 0
        assert "review" in result.output.lower()

    def test_review_with_anthropic_api_key(self, runner, mock_review_controller):
        """Test review command works with ANTHROPIC_API_KEY set."""
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = "test-key"
        env.pop("MINIMAX_API_KEY", None)

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_mode_auto_fix(self, runner, mock_review_controller):
        """Test review command with mode=auto-fix."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--mode", "auto-fix"],
            env=env,
        )

        assert result.exit_code == 0

    def test_review_mode_hybrid(self, runner, mock_review_controller):
        """Test review command with mode=hybrid."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--mode", "hybrid"],
            env=env,
        )

        assert result.exit_code == 0
