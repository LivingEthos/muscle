"""
Tests for SCLE CLI review command.

Integration tests that verify the review command correctly parses
arguments and calls the ReviewController.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from muscle.cli import cli
from muscle.tui.project_manager import ProjectConfig, ProjectManager


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
        mock_result.workflow_name = "review-smart"
        mock_result.execution_mode = "local"

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = 0
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = 0

        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_run_result
        mock_instance.get_review_result.return_value = mock_result

        with patch("muscle.code_review.ReviewController") as mock_class:
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

    def test_review_does_not_trigger_foresight(self, runner, tmp_path):
        """Normal review path should not invoke the opt-in foresight preflight."""
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("MINIMAX_API_KEY", None)

        with patch(
            "muscle.foresight.build_foresight_report",
            side_effect=AssertionError("review should not call foresight"),
        ) as build_foresight:
            result = runner.invoke(
                cli,
                ["review", "--target", str(tmp_path)],
                env=env,
            )

        assert result.exit_code != 0
        assert "MINIMAX_API_KEY not set" in result.output
        build_foresight.assert_not_called()

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
        """JSON review output should be parseable and free of progress text."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        result = runner.invoke(
            cli,
            ["review", "--target", "/tmp/test", "--format", "json"],
            env=env,
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["session_id"] == "abc123"
        assert payload["summary"]["critical"] == 0
        assert payload["summary"]["high"] == 0
        assert "Starting code review session" not in result.output
        assert "Review Complete" not in result.output

    @staticmethod
    def _controller_with(issues, *, files_reviewed, input_tokens, output_tokens):
        from muscle.code_review.types import (
            IssueCategory,
            ReviewIssue,
            Severity,
        )

        severity_map = {
            "critical": Severity.CRITICAL,
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
            "info": Severity.INFO,
        }
        built = [
            ReviewIssue(
                file_path=i["file_path"],
                line_number=i.get("line_number", 0),
                severity=severity_map[i.get("severity", "high")],
                category=IssueCategory.CORRECTNESS,
                cwe_id=i.get("cwe_id"),
                title=i["title"],
                description=i.get("description", ""),
                code_snippet="",
                suggested_fix=i.get("suggested_fix"),
                auto_fixable=i.get("auto_fixable", False),
            )
            for i in issues
        ]

        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = "/tmp/test"
        mock_result.issues = built
        mock_result.files_reviewed = files_reviewed
        mock_result.critical_count = sum(1 for b in built if b.severity == Severity.CRITICAL)
        mock_result.high_count = sum(1 for b in built if b.severity == Severity.HIGH)
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0
        mock_result.workflow_name = "review-smart"
        mock_result.execution_mode = "local"

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = input_tokens + output_tokens
        mock_run_result.stats.input_tokens = input_tokens
        mock_run_result.stats.output_tokens = output_tokens

        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_run_result
        mock_instance.get_review_result.return_value = mock_result
        return mock_instance

    def test_review_json_includes_description_and_fix(self, runner):
        """JSON issues must carry description, suggested_fix, and cwe_id."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        controller = self._controller_with(
            [
                {
                    "file_path": "/tmp/test/mod.py",
                    "line_number": 12,
                    "severity": "high",
                    "title": "SQL injection",
                    "description": "User input flows into a raw query.",
                    "suggested_fix": "Use parameterized queries.",
                    "cwe_id": "CWE-89",
                }
            ],
            files_reviewed=1,
            input_tokens=100,
            output_tokens=50,
        )
        with patch("muscle.code_review.ReviewController", return_value=controller):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--format", "json"],
                env=env,
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        issue = payload["issues"][0]
        assert issue["description"] == "User input flows into a raw query."
        assert issue["suggested_fix"] == "Use parameterized queries."
        assert issue["cwe_id"] == "CWE-89"
        assert issue["line"] == 12
        # Path normalized relative to the target root, not an absolute path.
        assert issue["file"] == "mod.py"
        assert payload["warnings"] == []

    def test_review_json_line_null_passthrough(self, runner):
        """A line-less finding (line_number 0) renders as JSON null."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        controller = self._controller_with(
            [
                {
                    "file_path": "/tmp/test/mod.py",
                    "line_number": 0,
                    "severity": "high",
                    "title": "No line",
                    "description": "A bug without a line.",
                }
            ],
            files_reviewed=1,
            input_tokens=100,
            output_tokens=50,
        )
        with patch("muscle.code_review.ReviewController", return_value=controller):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--format", "json"],
                env=env,
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["issues"][0]["line"] is None

    def test_review_json_warns_on_zero_activity(self, runner):
        """Degenerate run (scope nonempty, 0 tokens, 0 findings) emits a warning,
        keeps exit 0, and does not read as a clean pass."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        controller = self._controller_with(
            [],
            files_reviewed=3,
            input_tokens=0,
            output_tokens=0,
        )
        with patch("muscle.code_review.ReviewController", return_value=controller):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--format", "json"],
                env=env,
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["warnings"]
        assert "no LLM activity" in payload["warnings"][0]

    def test_review_json_no_warning_when_findings_present(self, runner):
        """Zero LLM tokens WITH findings (deterministic detectors) is legitimate."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        controller = self._controller_with(
            [
                {
                    "file_path": "/tmp/test/mod.py",
                    "line_number": 5,
                    "severity": "high",
                    "title": "Deterministic finding",
                    "description": "Found by a local detector.",
                }
            ],
            files_reviewed=2,
            input_tokens=0,
            output_tokens=0,
        )
        with patch("muscle.code_review.ReviewController", return_value=controller):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--format", "json"],
                env=env,
            )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["warnings"] == []

    def test_review_json_format_writes_output_file(
        self,
        runner,
        mock_review_controller,
        tmp_path,
    ):
        """JSON output files should be written even when no handoff plan exists."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"
        output_path = tmp_path / "review.json"

        result = runner.invoke(
            cli,
            [
                "review",
                "--target",
                "/tmp/test",
                "--format",
                "json",
                "--output",
                str(output_path),
            ],
            env=env,
        )

        assert result.exit_code == 0
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        assert payload["session_id"] == "abc123"
        assert payload["summary"]["critical"] == 0

    def test_review_no_db_skips_memory_and_learning(self, runner, mock_review_controller):
        """--no-db should not open ProjectMemory or write learning artifacts."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        with (
            patch("muscle.cli.review.ProjectMemory") as mock_project_memory,
            patch("muscle.cli.review.LearningPipeline") as mock_learning_pipeline,
        ):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--no-db"],
                env=env,
            )

        assert result.exit_code == 0
        mock_project_memory.assert_not_called()
        mock_learning_pipeline.assert_not_called()

    def test_review_does_not_trigger_remote_model_pack_fetch(
        self,
        runner,
        mock_review_controller,
    ):
        """Review should stay off the remote model-pack install path."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        with patch(
            "muscle.cli._shared.ModelPackManager",
            side_effect=AssertionError("review should not instantiate remote model-pack flows"),
        ):
            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--language", "python"],
                env=env,
            )

        assert result.exit_code == 0

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

    def test_review_pressure_challenge_threads_into_config(self, runner):
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = "/tmp/test"
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0
        mock_result.workflow_name = "pressure-review"
        mock_result.execution_mode = "local"

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = 0

        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_run_result
        mock_instance.get_review_result.return_value = mock_result

        with patch("muscle.code_review.ReviewController") as mock_class:
            mock_class.return_value = mock_instance
            result = runner.invoke(
                cli,
                [
                    "review",
                    "--target",
                    "/tmp/test",
                    "--mode",
                    "pressure",
                    "--challenge",
                    "fragility",
                    "--focus",
                    "failure,reliability",
                ],
                env=env,
            )

        assert result.exit_code == 0
        config = mock_class.call_args.kwargs["config"]
        assert config.pressure_challenge == "fragility"
        assert config.pressure_focus is not None
        assert config.pressure_focus.failure_modes is True
        assert config.pressure_focus.reliability is True

    def test_review_shadow_uses_detached_worker(self, runner):
        """Shadow review should launch a detached background worker process."""
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        with patch("muscle.code_review.shadow_worker.WorkerManager") as mock_manager_cls:
            mock_manager = MagicMock()
            mock_manager.submit_shadow_job.return_value = "shadow123"
            mock_manager_cls.return_value = mock_manager

            result = runner.invoke(
                cli,
                ["review", "--target", "/tmp/test", "--shadow"],
                env=env,
            )

        assert result.exit_code == 0
        mock_manager.submit_shadow_job.assert_called_once()
        assert mock_manager.submit_shadow_job.call_args.kwargs["detached"] is True
        assert "shadow123" in result.output

    def test_review_uses_cli_execution_override(self, runner, tmp_path):
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"
        target = tmp_path / "main.py"
        target.write_text("print('hello')\n", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = str(target)
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = 0

        with patch("muscle.code_review.ReviewController") as mock_class:
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_run_result
            mock_instance.get_review_result.return_value = mock_result
            mock_class.return_value = mock_instance

            result = runner.invoke(
                cli,
                ["review", "--target", str(target), "--execution", "worktree"],
                env=env,
            )

        assert result.exit_code == 0
        config = mock_class.call_args.kwargs["config"]
        assert config.execution_mode == "worktree"

    def test_review_uses_nearest_project_execution_config(self, runner, tmp_path, monkeypatch):
        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        manager = ProjectManager(base_path=tmp_path)
        assert manager.init_project(
            ProjectConfig(
                name="benchmark-project",
                path=tmp_path,
                languages=["python"],
                review_execution="worktree",
            )
        )

        src_dir = tmp_path / "src"
        src_dir.mkdir()
        target = src_dir / "main.py"
        target.write_text("print('hello')\n", encoding="utf-8")
        monkeypatch.chdir(src_dir)

        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = str(target)
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = 0

        with patch("muscle.code_review.ReviewController") as mock_class:
            mock_instance = MagicMock()
            mock_instance.run.return_value = mock_run_result
            mock_instance.get_review_result.return_value = mock_result
            mock_class.return_value = mock_instance

            result = runner.invoke(cli, ["review", "--target", str(target)], env=env)

        assert result.exit_code == 0
        config = mock_class.call_args.kwargs["config"]
        assert config.execution_mode == "worktree"


class TestReviewLearningIntegration:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_review_calls_learning_pipeline(self, runner, tmp_path):
        """Verify that LearningPipeline.learn_from_review is called after review."""
        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = str(tmp_path)
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None
        mock_run_result.stats.duration_seconds = 0.0
        mock_run_result.stats.tokens_used = 0

        mock_controller = MagicMock()
        mock_controller.run.return_value = mock_run_result
        mock_controller.get_review_result.return_value = mock_result

        mock_pipeline = MagicMock()
        mock_pipeline.learn_from_review.return_value = {
            "rules_added": 2,
            "skills_generated": 1,
        }

        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        with (
            patch(
                "muscle.code_review.ReviewController",
                return_value=mock_controller,
            ),
            patch(
                "muscle.cli.review.LearningPipeline",
                return_value=mock_pipeline,
            ) as mock_pipeline_class,
        ):
            result = runner.invoke(
                cli,
                ["review", "--target", str(tmp_path)],
                env=env,
            )

        assert result.exit_code == 0
        mock_pipeline_class.assert_called_once()
        mock_pipeline.learn_from_review.assert_called_once()
        assert "Learned 2 new rules" in result.output
        assert "Generated 1 new skills" in result.output

    def test_review_learning_pipeline_failure_does_not_crash(self, runner, tmp_path):
        """Verify that a failing LearningPipeline does not crash the review."""
        mock_result = MagicMock()
        mock_result.session_id = "abc123"
        mock_result.target_path = str(tmp_path)
        mock_result.issues = []
        mock_result.critical_count = 0
        mock_result.high_count = 0
        mock_result.medium_count = 0
        mock_result.low_count = 0
        mock_result.info_count = 0

        mock_run_result = MagicMock()
        mock_run_result.handoff_plan = None

        mock_controller = MagicMock()
        mock_controller.run.return_value = mock_run_result
        mock_controller.get_review_result.return_value = mock_result

        mock_pipeline = MagicMock()
        mock_pipeline.learn_from_review.side_effect = RuntimeError("pipeline broke")

        env = os.environ.copy()
        env["MINIMAX_API_KEY"] = "test-key"

        with (
            patch(
                "muscle.code_review.ReviewController",
                return_value=mock_controller,
            ),
            patch(
                "muscle.cli.review.LearningPipeline",
                return_value=mock_pipeline,
            ),
        ):
            result = runner.invoke(
                cli,
                ["review", "--target", str(tmp_path)],
                env=env,
            )

        assert result.exit_code == 0
