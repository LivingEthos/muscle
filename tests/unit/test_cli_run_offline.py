"""
Focused CLI regression tests for keeping normal run flows offline.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from tools.muscle.cli import run
from tools.muscle.types import SessionStatus


def test_run_does_not_trigger_remote_model_pack_fetch() -> None:
    runner = CliRunner()
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
                            with patch(
                                "tools.muscle.cli.ModelPackManager",
                                side_effect=AssertionError(
                                    "run should not instantiate remote model-pack flows"
                                ),
                            ):
                                mock_ctx = MagicMock()
                                mock_ctx.session_id = "test-session"
                                mock_ctx.stats.status = SessionStatus.SUCCESS
                                mock_ctx.stats.total_iterations = 1
                                mock_ctx.stats.total_tokens = 1000
                                mock_lc.return_value.run.return_value = mock_ctx
                                mock_lc.return_value.get_session_report.return_value = None

                                result = runner.invoke(
                                    run,
                                    ["--task", "Build a calculator", "--no-interactive"],
                                    catch_exceptions=False,
                                )

    assert result.exit_code == 0
