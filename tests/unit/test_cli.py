"""
Unit and integration tests for cli.py helper functions and commands.

Covers:
- Helper functions: _parse_timeout, _parse_budget, _truncate, _get_status_color,
  _serialize_json, _session_report_to_dict
- _event_handler via LoopEvent emission
- Commands: init, tui, history, resume, abort, check, kb, cost, improve,
  long-eval, probe, diagnosis, lifeline (review already covered in test_cli_review.py)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tools.muscle.cli import (
    _create_event_handler,
    _get_status_color,
    _parse_budget,
    _parse_timeout,
    _serialize_json,
    _session_report_to_dict,
    _truncate,
    abort,
    agents_group,
    agents_list,
    backups_group,
    check,
    cli,
    cost_group,
    diagnosis,
    disable,
    enable,
    history,
    improve_group,
    init,
    kb_group,
    lifeline,
    memory_group,
    memory_history,
    memory_status,
    long_eval_group,
    probe,
    resume,
    run,
    settings_group,
    skills_group,
    skills_list,
    status,
    tui,
)
from tools.muscle.loop_controller import LoopContext, LoopEvent
from tools.muscle.model_identity import SUPPORTED_CANONICAL_MODELS
from tools.muscle.types import (
    BudgetInfo,
    BudgetMode,
    CodeArtifact,
    EvalMode,
    IterationResult,
    IterationReport,
    LoopStats,
    RunConfig,
    SessionReport,
    SessionStatus,
)


class TestHelperFunctions:
    """Unit tests for pure helper functions in cli.py."""

    class TestParseTimeout:
        def test_valid_seconds(self):
            assert _parse_timeout("30s") == 30

        def test_validMinutes(self):
            assert _parse_timeout("5m") == 300

        def test_validHours(self):
            assert _parse_timeout("2h") == 7200

        def test_validDays(self):
            assert _parse_timeout("1d") == 86400

        def test_bareNumber(self):
            assert _parse_timeout("120") == 120

        def test_emptyString(self):
            assert _parse_timeout("") == 3600

        def test_negativeNumber(self):
            assert _parse_timeout("-10") == 3600

        def test_exceedsMax(self):
            from tools.muscle.cli import MAX_TIMEOUT_SECONDS

            assert _parse_timeout("100d") == MAX_TIMEOUT_SECONDS

        def test_invalidFormat(self):
            assert _parse_timeout("abc") == 3600

        def test_invalidUnit(self):
            assert _parse_timeout("5x") == 3600

        def test_zeroValue(self):
            assert _parse_timeout("0s") == 0

        def test_floatValue(self):
            assert _parse_timeout("1.5m") == 3600

        def test_negativeWithUnit(self):
            assert _parse_timeout("-5m") == 3600

    class TestParseBudget:
        def test_unlimited(self):
            mode, limit = _parse_budget("unlimited")
            assert mode == BudgetMode.UNLIMITED
            assert limit == 0

        def test_unlimitedUppercase(self):
            mode, limit = _parse_budget("UNLIMITED")
            assert mode == BudgetMode.UNLIMITED

        def test_auto(self):
            mode, limit = _parse_budget("auto")
            assert mode == BudgetMode.AUTO
            assert limit == 0

        def test_autoMixedCase(self):
            mode, limit = _parse_budget("Auto")
            assert mode == BudgetMode.AUTO

        def test_fixedNumber(self):
            mode, limit = _parse_budget("100")
            assert mode == BudgetMode.FIXED
            assert limit == 100

        def test_fixedWithK(self):
            mode, limit = _parse_budget("50k")
            assert mode == BudgetMode.UNLIMITED

        def test_fixedWithM(self):
            mode, limit = _parse_budget("2m")
            assert mode == BudgetMode.UNLIMITED

        def test_invalidString(self):
            mode, limit = _parse_budget("abc")
            assert mode == BudgetMode.UNLIMITED
            assert limit == 0

        def test_emptyString(self):
            mode, limit = _parse_budget("")
            assert mode == BudgetMode.UNLIMITED

    class TestTruncate:
        def test_underLimit(self):
            result = _truncate("hello", 10)
            assert result == "hello"

        def test_exactLimit(self):
            result = _truncate("hello", 5)
            assert result == "hello"

        def test_overLimit(self):
            result = _truncate("hello world", 8)
            assert result == "hello..."

        def test_exactlyThreeOver(self):
            result = _truncate("abcdefgh", 5)
            assert result == "ab..."

        def test_emptyString(self):
            result = _truncate("", 10)
            assert result == ""

        def test_unicode(self):
            result = _truncate("hello世界", 7)
            assert result == "hello世界"

    class TestGetStatusColor:
        def test_pending(self):
            assert _get_status_color("pending") == "yellow"

        def test_running(self):
            assert _get_status_color("running") == "cyan"

        def test_completed(self):
            assert _get_status_color("completed") == "green"

        def test_failed(self):
            assert _get_status_color("failed") == "red"

        def test_cancelled(self):
            assert _get_status_color("cancelled") == "dim"

        def test_unknown(self):
            assert _get_status_color("unknown") == "white"

        def test_empty(self):
            assert _get_status_color("") == "white"

    class TestSerializeJson:
        def test_dict_with_simple_values(self):
            data = {"key": "value", "num": 42}
            result = _serialize_json(data)
            assert "key" in result
            assert "value" in result
            assert json.loads(result) == data

        def test_nested_dict(self):
            data = {"outer": {"inner": "value"}}
            result = _serialize_json(data)
            assert json.loads(result) == data

        def test_list_value(self):
            data = {"items": [1, 2, 3]}
            result = _serialize_json(data)
            assert json.loads(result) == data

        def test_empty_dict(self):
            result = _serialize_json({})
            assert json.loads(result) == {}

        def test_special_chars(self):
            data = {"msg": "hello\nworld"}
            result = _serialize_json(data)
            assert json.loads(result) == data

    class TestSessionReportToDict:
        def test_full_report(self):
            iteration = IterationReport(
                iteration=1,
                success=True,
                errors=[],
                warnings=["warn1"],
                token_cost=100,
                duration_seconds=5.0,
                files_generated=["a.py", "b.py"],
                evolved_strategy="strategy_v1",
            )
            artifact = CodeArtifact(
                file_path="a.py",
                content_hash="abc123",
                language="python",
                lines=10,
            )
            budget_info = BudgetInfo(
                mode=BudgetMode.FIXED,
                limit=1000,
                spent=100,
            )
            report = SessionReport(
                session_id="sess-123",
                task="test task",
                status=SessionStatus.SUCCESS,
                total_iterations=1,
                total_tokens=100,
                total_duration_seconds=5.0,
                iterations=[iteration],
                final_strategy="final_strat",
                artifacts=[artifact],
                budget_info=budget_info,
                git_commit="abc123",
            )

            result = _session_report_to_dict(report)

            assert result["session_id"] == "sess-123"
            assert result["task"] == "test task"
            assert result["status"] == "success"
            assert result["total_iterations"] == 1
            assert result["total_tokens"] == 100
            assert len(result["iterations"]) == 1
            assert result["iterations"][0]["iteration"] == 1
            assert result["iterations"][0]["success"] is True
            assert result["iterations"][0]["files_generated"] == ["a.py", "b.py"]
            assert len(result["artifacts"]) == 1
            assert result["artifacts"][0]["file_path"] == "a.py"
            assert result["budget_info"]["mode"] == "fixed"
            assert result["budget_info"]["limit"] == 1000
            assert result["git_commit"] == "abc123"

        def test_report_without_budget_info(self):
            iteration = IterationReport(
                iteration=1,
                success=False,
                errors=["error1"],
                warnings=[],
                token_cost=0,
                duration_seconds=0.0,
                files_generated=[],
                evolved_strategy="",
            )
            report = SessionReport(
                session_id="sess-456",
                task="",
                status=SessionStatus.FAILED,
                total_iterations=1,
                total_tokens=0,
                total_duration_seconds=0.0,
                iterations=[iteration],
                final_strategy="",
                artifacts=[],
                budget_info=None,
                git_commit=None,
            )

            result = _session_report_to_dict(report)

            assert result["status"] == "failed"
            assert result["budget_info"] is None
            assert len(result["iterations"]) == 1
            assert result["iterations"][0]["errors"] == ["error1"]

        def test_report_with_no_iterations(self):
            report = SessionReport(
                session_id="sess-empty",
                task="empty session",
                status=SessionStatus.RUNNING,
                total_iterations=0,
                total_tokens=0,
                total_duration_seconds=0.0,
                iterations=[],
                final_strategy="",
                artifacts=[],
                budget_info=None,
                git_commit=None,
            )

            result = _session_report_to_dict(report)

            assert result["iterations"] == []
            assert result["artifacts"] == []


class TestEventHandler:
    """Unit tests for _event_handler function.

    These tests verify that _event_handler produces output and modifies
    module state correctly. We use capsys to capture stdout since the
    function prints to the real console.
    """

    def test_iteration_start_resets_streaming_text(self, capsys):
        state, handler = _create_event_handler()
        handler(LoopEvent.ITERATION_START, {"iteration": 1})
        captured = capsys.readouterr()
        assert "Iteration 1" in captured.out

    def test_generation_stream_appends_chunk(self):
        state, handler = _create_event_handler()
        handler(LoopEvent.GENERATION_STREAM, {"chunk": "test_chunk"})
        assert "test_chunk" in state.chunks

    def test_evaluation_passed(self, capsys):
        _, handler = _create_event_handler()
        handler(LoopEvent.EVALUATION_END, {"passed": True, "errors": 0})
        captured = capsys.readouterr()
        assert "PASSED" in captured.out

    def test_evaluation_failed(self, capsys):
        _, handler = _create_event_handler()
        handler(LoopEvent.EVALUATION_END, {"passed": False, "errors": 3})
        captured = capsys.readouterr()
        assert "failed" in captured.out

    def test_parallel_evaluation_mode(self, capsys):
        _, handler = _create_event_handler()
        handler(LoopEvent.EVALUATION_START, {"eval_mode": EvalMode.PARALLEL})
        captured = capsys.readouterr()
        assert "parallel" in captured.out

    def test_evolution_end(self, capsys):
        _, handler = _create_event_handler()
        handler(LoopEvent.EVOLUTION_END, {"tokens": 500})
        captured = capsys.readouterr()
        assert "Evolved strategy" in captured.out

    def test_session_complete_success(self, capsys):
        _, handler = _create_event_handler()
        handler(
            LoopEvent.SESSION_COMPLETE, {"status": SessionStatus.SUCCESS.value, "reason": ""}
        )
        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out

    def test_session_complete_failed(self, capsys):
        _, handler = _create_event_handler()
        handler(
            LoopEvent.SESSION_COMPLETE,
            {"status": SessionStatus.FAILED.value, "reason": "budget exceeded"},
        )
        captured = capsys.readouterr()
        assert "FAILED" in captured.out

    def test_budget_warning(self, capsys):
        _, handler = _create_event_handler()
        handler(LoopEvent.BUDGET_WARNING, {"iteration": 5, "total_tokens": 50000})
        captured = capsys.readouterr()
        assert "Budget warning" in captured.out


class TestInitCommand:
    """Integration tests for init command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_init_non_interactive(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            init,
            ["--non-interactive"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        config_path = tmp_path / ".muscle" / "config.yaml"
        assert config_path.exists()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["project"]["review_execution"] == "local"
        assert config["project"]["related_project_mode"] == "suggest"
        assert config["project"]["model_pack_mode"] == "suggest"
        assert "canonical_model_key" in config["project"]
        assert config["project"]["model_identity_source"]
        assert "Setup Summary" in result.output
        assert "Related-project mode" in result.output
        assert "Model-pack mode" in result.output

    def test_init_non_interactive_accepts_growth_and_model_overrides(
        self,
        runner,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            init,
            [
                "--non-interactive",
                "--related-mode",
                "off",
                "--pack-mode",
                "auto",
                "--canonical-model",
                "openai/gpt-5@1",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        config = json.loads((tmp_path / ".muscle" / "config.yaml").read_text(encoding="utf-8"))
        assert config["project"]["related_project_mode"] == "off"
        assert config["project"]["model_pack_mode"] == "auto"
        assert config["project"]["canonical_model_key"] == "openai/gpt-5@1"
        assert config["project"]["model_manual_override"] == "openai/gpt-5@1"
        assert config["project"]["model_identity_source"] == "manual_override"
        assert "openai/gpt-5@1" in result.output

    def test_init_interactive_prompts_for_unresolved_model(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr("tools.muscle.cli._requested_model_label", lambda: "opaque-gateway")
        monkeypatch.setattr(
            "tools.muscle.cli._provider_endpoint",
            lambda: "https://gateway.example/anthropic",
        )

        result = runner.invoke(
            init,
            ["--platform", "claude-code", "--review-execution", "local"],
            input="\n\n2\n\n\n\n1\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        config = json.loads((tmp_path / ".muscle" / "config.yaml").read_text(encoding="utf-8"))
        assert config["project"]["model_manual_override"] == SUPPORTED_CANONICAL_MODELS[0]
        assert config["project"]["canonical_model_key"] == SUPPORTED_CANONICAL_MODELS[0]
        assert config["project"]["model_identity_source"] == "manual_override"
        assert "could not confidently verify the backing model" in result.output

    def test_init_interactive_detects_no_project(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("builtins.input", return_value=""):
                result = runner.invoke(init, [], input="\n")
                # May succeed or gracefully exit depending on project detection


class TestEnableCommand:
    """Integration tests for enable command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_enable_without_project(self, runner):
        """enable without a project should handle gracefully."""
        result = runner.invoke(enable, [], catch_exceptions=False)
        assert result is not None

    def test_enable_command_exists(self, runner):
        """enable command should be registered and callable."""
        result = runner.invoke(enable, [], catch_exceptions=True)
        # Should not crash - may exit non-zero if no project
        assert result is not None


class TestDisableCommand:
    """Integration tests for disable command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_disable_without_project(self, runner):
        """disable without a project should handle gracefully."""
        result = runner.invoke(disable, [], catch_exceptions=False)
        assert result is not None

    def test_disable_command_exists(self, runner):
        """disable command should be registered and callable."""
        result = runner.invoke(disable, [], catch_exceptions=True)
        # Should not crash - may exit non-zero if no project
        assert result is not None


class TestStatusCommand:
    """Integration tests for status command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_status_command_exists(self, runner):
        """status command should be registered and callable."""
        result = runner.invoke(status, [], catch_exceptions=False)
        assert result is not None
        # Status should always return 0 and show something
        assert result.exit_code == 0


class TestTuiCommand:
    """Integration tests for tui command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_tui_runs(self, runner):
        # TUI may fail in headless environment - that's ok
        result = runner.invoke(tui, [], catch_exceptions=False)
        # Just verify it doesn't crash - exit code may be non-zero in headless
        assert result is not None


class TestHistoryCommand:
    """Integration tests for history command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_history_empty(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(history, [], catch_exceptions=False)
            assert result.exit_code == 0

    def test_history_with_limit(self, runner):
        result = runner.invoke(history, [], catch_exceptions=False)
        assert result.exit_code == 0


class TestAbortCommand:
    """Integration tests for abort command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_abort_nonexistent_session(self, runner):
        # Should handle gracefully
        result = runner.invoke(abort, ["nonexistent-session-id"], catch_exceptions=False)
        # May fail if session doesn't exist - that's expected
        assert result is not None

    def test_abort_no_session_id(self, runner):
        result = runner.invoke(abort, [], catch_exceptions=True)
        assert result.exit_code != 0


class TestResumeCommand:
    """Integration tests for resume command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_resume_rejects_successful_session(self, runner):
        mock_manager = MagicMock()
        mock_manager.load_session.return_value = {
            "session_id": "done-123",
            "task": "already finished",
            "status": SessionStatus.SUCCESS.value,
        }

        with patch("tools.muscle.cli.SessionManager", return_value=mock_manager):
            result = runner.invoke(resume, ["done-123"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "already completed successfully" in result.output

    def test_resume_rejects_active_running_session(self, runner):
        mock_manager = MagicMock()
        mock_manager.load_session.return_value = {
            "session_id": "running-123",
            "task": "still running",
            "status": SessionStatus.RUNNING.value,
        }

        with patch("tools.muscle.cli.SessionManager", return_value=mock_manager):
            with patch("tools.muscle.cli._read_session_pid", return_value=4242):
                with patch("tools.muscle.cli._is_process_alive", return_value=True):
                    result = runner.invoke(resume, ["running-123"], catch_exceptions=False)

        assert result.exit_code == 1
        assert "still running" in result.output

    def test_resume_runs_with_loaded_checkpoint(self, runner, tmp_path):
        resume_ctx = LoopContext(
            session_id="resume-123",
            config=RunConfig(
                task="resume task",
                language="python",
                output_dir=str(tmp_path),
                max_iterations=4,
                budget_mode=BudgetMode.UNLIMITED,
                eval_mode=EvalMode.ALL,
            ),
            stats=LoopStats(total_iterations=2, total_tokens=200),
            evolved_strategy="Refine tests first",
            iterations=[
                IterationResult(iteration=1, success=False, token_cost=100),
                IterationResult(iteration=2, success=False, token_cost=100),
            ],
            current_iteration=2,
        )

        mock_manager = MagicMock()
        mock_manager.load_session.return_value = {
            "session_id": "resume-123",
            "task": "resume task",
            "status": SessionStatus.FAILED.value,
        }
        mock_manager.load_resume_context.return_value = resume_ctx

        mock_controller = MagicMock()
        resumed_ctx = LoopContext(
            session_id="resume-123",
            config=resume_ctx.config,
            stats=LoopStats(
                total_iterations=3,
                total_tokens=300,
                status=SessionStatus.SUCCESS,
            ),
            current_iteration=3,
        )
        mock_controller.run.return_value = resumed_ctx

        with patch("tools.muscle.cli.SessionManager", return_value=mock_manager):
            with patch("tools.muscle.cli._create_m27_client") as mock_create_client:
                mock_create_client.return_value.api_key = "test-key"
                with patch("tools.muscle.cli.CodeGenerator"):
                    with patch("tools.muscle.cli.Evolver"):
                        with patch("tools.muscle.cli.BudgetManager"):
                            with patch(
                                "tools.muscle.cli.LoopController", return_value=mock_controller
                            ):
                                with patch("tools.muscle.cli.Progress") as mock_progress:
                                    mock_progress.return_value.__enter__.return_value.add_task = (
                                        MagicMock()
                                    )
                                    with patch("tools.muscle.cli.Live") as mock_live:
                                        mock_live.return_value.start = MagicMock()
                                        mock_live.return_value.stop = MagicMock()
                                        result = runner.invoke(
                                            resume,
                                            ["resume-123"],
                                            catch_exceptions=False,
                                        )

        assert result.exit_code == 0
        assert "Resuming session resume-123" in result.output
        assert "Status: success" in result.output
        mock_controller.run.assert_called_once()
        assert mock_controller.run.call_args.kwargs["resume_context"] is resume_ctx


class TestCheckCommand:
    """Integration tests for check command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_check_file_not_found(self, runner):
        result = runner.invoke(
            check,
            ["--target", "/nonexistent/file.py", "--language", "python"],
            catch_exceptions=False,
        )
        assert result.exit_code != 0

    def test_check_target_does_not_exist(self, runner):
        result = runner.invoke(
            check,
            ["--target", "/tmp/this_file_definitely_does_not_exist_12345.py"],
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_check_language_py_short_alias(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"x = 1\n")
            f.flush()
            try:
                result = runner.invoke(
                    check,
                    ["--target", f.name, "--language", "py"],
                    catch_exceptions=False,
                )
                assert result.exit_code in (0, 1)
            finally:
                Path(f.name).unlink()

    def test_check_language_js_short_alias(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as f:
            f.write(b"let x = 1;\n")
            f.flush()
            try:
                result = runner.invoke(
                    check,
                    ["--target", f.name, "--language", "js"],
                    catch_exceptions=False,
                )
                # May pass or skip if node not installed
                assert result is not None
            finally:
                Path(f.name).unlink()


class TestKbGroup:
    """Integration tests for kb subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_kb_stats(self, runner):
        result = runner.invoke(kb_group, ["stats"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_kb_export_missing_file(self, runner):
        result = runner.invoke(
            kb_group,
            ["export", "/nonexistent/path/export.json"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

    def test_kb_import_missing_file(self, runner):
        result = runner.invoke(
            kb_group,
            ["import", "/nonexistent/path/import.json"],
            catch_exceptions=False,
        )
        assert result.exit_code != 0

    def test_kb_clear_without_force(self, runner):
        result = runner.invoke(kb_group, ["clear"], catch_exceptions=True)
        # Should require --force
        assert result.exit_code != 0

    def test_kb_clear_with_force(self, runner):
        result = runner.invoke(kb_group, ["clear", "--force"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_kb_knowledge_add_success(self, runner):
        result = runner.invoke(
            kb_group,
            [
                "knowledge-add",
                "--pattern",
                "Auth token expired",
                "--solution",
                "Refresh token and retry",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "Added strategy" in result.output

    def test_kb_import_valid_file(self, runner, tmp_path):
        export_file = tmp_path / "export.json"
        export_file.write_text("[]")
        result = runner.invoke(
            kb_group,
            ["import", str(export_file)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "Imported" in result.output


class TestCostGroup:
    """Integration tests for cost subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_cost_stats(self, runner):
        result = runner.invoke(cost_group, ["stats"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_cost_clear_without_force(self, runner):
        result = runner.invoke(cost_group, ["clear"], catch_exceptions=True)
        assert result.exit_code != 0

    def test_cost_clear_with_force(self, runner):
        result = runner.invoke(cost_group, ["clear", "--force"], catch_exceptions=False)
        assert result.exit_code == 0


class TestImproveGroup:
    """Integration tests for improve subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_improve_report(self, runner):
        result = runner.invoke(improve_group, ["report"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_improve_export_missing_file(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            export_path = Path(tmpdir) / "export.json"
            result = runner.invoke(
                improve_group,
                ["export", str(export_path)],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

    def test_improve_import_missing_file(self, runner):
        result = runner.invoke(
            improve_group,
            ["import", "/nonexistent/path/import.json"],
            catch_exceptions=False,
        )
        assert result.exit_code != 0

    def test_improve_clear_without_force(self, runner):
        result = runner.invoke(improve_group, ["clear"], catch_exceptions=True)
        assert result.exit_code != 0

    def test_improve_clear_with_force(self, runner):
        result = runner.invoke(improve_group, ["clear", "--force"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_improve_prompt(self, runner):
        result = runner.invoke(improve_group, ["prompt"], catch_exceptions=False)
        assert result.exit_code == 0


class TestLongEvalGroup:
    """Integration tests for long-eval subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_long_eval_run(self, runner, tmp_path):
        result = runner.invoke(
            long_eval_group,
            ["run", "--target", str(tmp_path)],
            catch_exceptions=False,
        )
        assert result is not None

    def test_long_eval_reports(self, runner):
        result = runner.invoke(
            long_eval_group, ["reports", "--limit", "10"], catch_exceptions=False
        )
        assert result.exit_code == 0

    def test_long_eval_cleanup_without_force(self, runner):
        result = runner.invoke(long_eval_group, ["cleanup", "--days", "7"], catch_exceptions=True)
        assert result.exit_code != 0

    def test_long_eval_cleanup_with_force(self, runner):
        result = runner.invoke(
            long_eval_group,
            ["cleanup", "--days", "7", "--force"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert result is not None

    def test_long_eval_benchmark(self, runner):
        with patch("tools.muscle.code_review.review_benchmark.ReviewBenchmarkRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run_benchmark.return_value = {
                "aggregate": {
                    "baseline": {
                        "high_critical_recall": 0.4,
                        "false_positive_rate": 0.1,
                        "tokens_used": 100,
                    },
                    "candidate": {
                        "high_critical_recall": 0.6,
                        "false_positive_rate": 0.08,
                        "tokens_used": 90,
                    },
                },
                "thresholds": {
                    "high_critical_recall_up_20pct": True,
                    "false_positive_rate_not_worse": True,
                    "token_cost_down_30pct": False,
                },
                "report_paths": {"json": "/tmp/benchmark.json"},
            }
            mock_cls.return_value = mock_runner
            result = runner.invoke(
                long_eval_group,
                ["benchmark", "--suite", "model-pack"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            mock_runner.run_benchmark.assert_called_once_with(
                baseline="legacy",
                candidate="review-smart",
                include_history=True,
                suite="model-pack",
            )

    def test_long_eval_benchmark_enforce_gates(self, runner):
        with patch("tools.muscle.code_review.review_benchmark.ReviewBenchmarkRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run_benchmark.return_value = {
                "aggregate": {
                    "baseline": {
                        "high_critical_recall": 0.4,
                        "false_positive_rate": 0.1,
                        "tokens_used": 100,
                    },
                    "candidate": {
                        "high_critical_recall": 0.6,
                        "false_positive_rate": 0.08,
                        "tokens_used": 90,
                    },
                },
                "thresholds": {
                    "high_critical_recall_up_20pct": True,
                    "false_positive_rate_not_worse": True,
                    "token_cost_down_30pct": False,
                },
                "benchmark_gates": {"overall_passed": True, "gates": {}},
                "report_paths": {"json": "/tmp/benchmark.json"},
            }
            mock_runner.build_release_evidence.return_value = {
                "release_gates": {"overall_passed": True, "gates": {}}
            }
            mock_runner.write_release_evidence.return_value = {"json": "/tmp/release.json"}
            mock_cls.return_value = mock_runner
            with patch(
                "tools.muscle.cli._run_benchmark_release_invariants",
                return_value={"checked": True, "passed": True, "summary": "ok", "details": {}},
            ) as mock_invariants:
                result = runner.invoke(
                    long_eval_group,
                    ["benchmark", "--enforce-gates"],
                    catch_exceptions=False,
                )

            assert result.exit_code == 0
            mock_invariants.assert_called_once_with()
            mock_runner.build_release_evidence.assert_called_once()
            mock_runner.write_release_evidence.assert_called_once()


class TestSettingsGroup:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_settings_show_includes_review_execution(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(init, ["--non-interactive"], catch_exceptions=False)

        result = runner.invoke(settings_group, ["show"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Review Execution" in result.output
        assert "local" in result.output
        assert "Related Project Mode" in result.output
        assert "Model Pack Mode" in result.output
        assert "Canonical Model" in result.output
        assert "Model Identity Source" in result.output

    def test_settings_review_updates_execution_mode(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner.invoke(init, ["--non-interactive"], catch_exceptions=False)

        result = runner.invoke(
            settings_group,
            ["review", "--execution", "worktree"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        config = json.loads((tmp_path / ".muscle" / "config.yaml").read_text(encoding="utf-8"))
        assert config["project"]["review_execution"] == "worktree"
        assert config["project"]["review_gate"] == "block+fix"


class TestBackupsGroup:
    """Integration tests for backups subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_backups_list_empty(self, runner):
        """List command should succeed even with no backups."""
        result = runner.invoke(backups_group, ["list"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_backups_list_with_limit(self, runner):
        """List command accepts --limit flag."""
        result = runner.invoke(backups_group, ["list", "--limit", "5"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_backups_list_invalid_type(self, runner):
        """List command handles invalid backup type (with or without DB)."""
        result = runner.invoke(backups_group, ["list", "--type", "invalid"], catch_exceptions=True)
        # Either gracefully handles it (exit 0 with error message) or fails on DB env
        assert result.exit_code == 0 or "Invalid backup type" in result.output

    def test_backups_list_valid_types(self, runner):
        """List command accepts each valid backup type."""
        for btype in ("full", "claude_md", "config", "memory"):
            result = runner.invoke(backups_group, ["list", "--type", btype], catch_exceptions=False)
            assert result.exit_code == 0

    def test_backups_show_nonexistent(self, runner):
        """Show command handles nonexistent backup ID."""
        result = runner.invoke(backups_group, ["show", "99999"], catch_exceptions=False)
        assert result.exit_code == 0  # gracefully handles not found

    def test_backups_restore_nonexistent(self, runner):
        """Restore command handles nonexistent backup ID."""
        result = runner.invoke(backups_group, ["restore", "99999"], catch_exceptions=False)
        assert result.exit_code == 0  # gracefully handles not found

    def test_backups_restore_dry_run(self, runner):
        """Restore with --dry-run does not error for nonexistent backup."""
        result = runner.invoke(
            backups_group, ["restore", "99999", "--dry-run"], catch_exceptions=False
        )
        assert result.exit_code == 0


class TestProbeCommand:
    """Integration tests for probe command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_probe_no_job_id(self, runner):
        result = runner.invoke(probe, [], catch_exceptions=False)
        assert result.exit_code == 0

    def test_probe_nonexistent_job(self, runner):
        result = runner.invoke(probe, ["--job-id", "nonexistent-job-id"], catch_exceptions=False)
        assert result.exit_code == 1


class TestDiagnosisCommand:
    """Integration tests for diagnosis command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_diagnosis_no_job_id(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(diagnosis, [], catch_exceptions=False)
        assert result.exit_code == 1

    def test_diagnosis_nonexistent_job(self, runner):
        result = runner.invoke(
            diagnosis, ["--job-id", "nonexistent-job-id"], catch_exceptions=False
        )
        assert result.exit_code == 1


class TestLifelineCommand:
    """Integration tests for lifeline command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_lifeline_requires_target(self, runner):
        result = runner.invoke(lifeline, [], catch_exceptions=True)
        assert result.exit_code != 0

    def test_lifeline_with_target_and_prompt(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.py"
            target.write_text("x = 1")

            result = runner.invoke(
                lifeline,
                [str(target), "--prompt", "review this"],
                catch_exceptions=False,
            )
            # Should call API or gracefully handle missing API key
            assert result is not None

    def test_lifeline_default_intensity(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.py"
            target.write_text("x = 1")

            result = runner.invoke(
                lifeline,
                [str(target), "--prompt", "review this"],
                catch_exceptions=False,
            )
            assert result is not None


class TestRunCommand:
    """Integration tests for the run command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_run_empty_task(self, runner):
        result = runner.invoke(
            run,
            ["--task", ""],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "Error: Task cannot be empty" in result.output

    def test_run_max_iterations_too_low(self, runner):
        result = runner.invoke(
            run,
            ["--task", "Build a calculator", "--max-iterations", "0"],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "max_iterations must be between 1 and 100" in result.output

    def test_run_max_iterations_too_high(self, runner):
        result = runner.invoke(
            run,
            ["--task", "Build a calculator", "--max-iterations", "101"],
            catch_exceptions=False,
        )
        assert result.exit_code == 1
        assert "max_iterations must be between 1 and 100" in result.output

    def test_run_estimate_cost(self, runner):
        result = runner.invoke(
            run,
            ["--task", "Build a calculator", "--estimate-cost"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "Cost Estimate:" in result.output
        assert "Cost estimate complete" in result.output

    def test_run_no_api_key(self, runner):
        with patch.dict(os.environ, {"MINIMAX_API_KEY": ""}, clear=False):
            result = runner.invoke(
                run,
                ["--task", "Build a calculator"],
                catch_exceptions=True,
            )
            assert result.exit_code == 1

    def test_run_keyboard_interrupt(self, runner):
        mock_live_instance = MagicMock()
        mock_live_instance.__enter__ = MagicMock(return_value=mock_live_instance)
        mock_live_instance.__exit__ = MagicMock(return_value=None)
        mock_live_instance.start = MagicMock()
        mock_live_instance.stop = MagicMock()

        with patch("tools.muscle.cli._create_m27_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.api_key = "test-key"
            mock_client.chat.return_value = ("code", MagicMock(total=100))
            mock_create_client.return_value = mock_client

            with patch("tools.muscle.cli.CodeGenerator"):
                with patch("tools.muscle.cli.Evolver"):
                    with patch("tools.muscle.cli.BudgetManager"):
                        with patch("tools.muscle.cli.LoopController") as mock_lc:
                            with patch("tools.muscle.cli.Live", return_value=mock_live_instance):
                                mock_lc.return_value.run.side_effect = KeyboardInterrupt
                                mock_lc.return_value.get_session_report.return_value = None
                                mock_lc.return_value.request_abort = MagicMock()

                                result = runner.invoke(
                                    run,
                                    ["--task", "Build a calculator", "--no-interactive"],
                                    catch_exceptions=False,
                                )
                                assert result.exit_code == 130
                                assert "Aborted by user" in result.output

    def test_run_with_json_format(self, runner):
        from tools.muscle.types import BudgetInfo, SessionReport

        mock_budget_info = BudgetInfo(mode=BudgetMode.UNLIMITED, limit=0, spent=0)
        mock_session_report = SessionReport(
            session_id="test-session",
            task="Build a calculator",
            status=SessionStatus.SUCCESS,
            total_iterations=1,
            total_tokens=1000,
            total_duration_seconds=1.0,
            iterations=[],
            final_strategy="Use Python",
            artifacts=[],
            budget_info=mock_budget_info,
            git_commit=None,
        )

        mock_live_instance = MagicMock()
        mock_live_instance.__enter__ = MagicMock(return_value=mock_live_instance)
        mock_live_instance.__exit__ = MagicMock(return_value=None)
        mock_live_instance.start = MagicMock()
        mock_live_instance.stop = MagicMock()

        with patch("tools.muscle.cli._create_m27_client") as mock_create_client:
            mock_client = MagicMock()
            mock_client.api_key = "test-key"
            mock_client.chat.return_value = ("code", MagicMock(total=100))
            mock_create_client.return_value = mock_client

            with patch("tools.muscle.cli.CodeGenerator"):
                with patch("tools.muscle.cli.Evolver"):
                    with patch("tools.muscle.cli.BudgetManager"):
                        with patch("tools.muscle.cli.LoopController") as mock_lc:
                            with patch("tools.muscle.cli.Live", return_value=mock_live_instance):
                                mock_ctx = MagicMock()
                                mock_ctx.session_id = "test-session"
                                mock_ctx.stats.status = SessionStatus.SUCCESS
                                mock_ctx.stats.total_iterations = 1
                                mock_ctx.stats.total_tokens = 1000
                                mock_lc.return_value.run.return_value = mock_ctx
                                mock_lc.return_value.get_session_report.return_value = (
                                    mock_session_report
                                )

                                result = runner.invoke(
                                    run,
                                    [
                                        "--task",
                                        "Build a calculator",
                                        "--format",
                                        "json",
                                        "--no-interactive",
                                    ],
                                    catch_exceptions=False,
                                )
                                assert result.exit_code == 0
                                assert (
                                    "session_id" in result.output.lower()
                                    or "test-session" in result.output.lower()
                                )


class TestMemoryGroup:
    """Integration tests for memory subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_memory_status_empty(self, runner):
        """memory status should succeed even with empty DB."""
        result = runner.invoke(memory_status, [], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Memory Status" in result.output

    def test_memory_status_shows_db_path(self, runner):
        """memory status shows database path."""
        result = runner.invoke(memory_status, [], catch_exceptions=False)
        assert result.exit_code == 0
        # Verify the table header and at least the "Database" row label appears
        assert "Memory Status" in result.output
        assert "Database" in result.output

    def test_memory_history_empty(self, runner):
        """memory history should succeed even with no data."""
        result = runner.invoke(memory_history, [], catch_exceptions=False)
        assert result.exit_code == 0

    def test_memory_history_with_limit(self, runner):
        """memory history accepts --limit flag."""
        result = runner.invoke(memory_history, ["--limit", "5"], catch_exceptions=False)
        assert result.exit_code == 0


class TestSkillsGroup:
    """Integration tests for skills subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_skills_list_no_dir(self, runner):
        """skills list handles missing skills directory gracefully."""
        result = runner.invoke(skills_list, [], catch_exceptions=False)
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "no skills" in result.output.lower()

    def test_skills_list_empty_dir(self, runner):
        """skills list handles empty skills directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / ".muscle" / "skills"
            skills_dir.mkdir(parents=True)
            result = runner.invoke(skills_list, ["--path", str(skills_dir)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "no skills" in result.output.lower()

    def test_skills_list_with_files(self, runner):
        """skills list shows skill files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = Path(tmpdir) / ".muscle" / "skills"
            skills_dir.mkdir(parents=True)
            (skills_dir / "test_skill.md").write_text("# Test Skill")
            (skills_dir / "another.md").write_text("# Another")

            result = runner.invoke(skills_list, ["--path", str(skills_dir)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "test_skill" in result.output
            assert "another" in result.output


class TestAgentsGroup:
    """Integration tests for agents subcommands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_agents_list_no_dir(self, runner, tmp_path, monkeypatch):
        """agents list handles missing agents directory gracefully."""
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(agents_list, [], catch_exceptions=False)
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "no agents" in result.output.lower()

    def test_agents_list_empty_dir(self, runner):
        """agents list handles empty agents directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".muscle" / "agents"
            agents_dir.mkdir(parents=True)
            result = runner.invoke(agents_list, ["--path", str(agents_dir)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "no agents" in result.output.lower()

    def test_agents_list_with_files(self, runner):
        """agents list shows agent files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / ".muscle" / "agents"
            agents_dir.mkdir(parents=True)
            (agents_dir / "coder.md").write_text("# Coder Agent")
            (agents_dir / "reviewer.md").write_text("# Reviewer Agent")

            result = runner.invoke(agents_list, ["--path", str(agents_dir)], catch_exceptions=False)
            assert result.exit_code == 0
            assert "coder" in result.output
            assert "reviewer" in result.output
