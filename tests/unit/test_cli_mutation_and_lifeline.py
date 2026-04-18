"""
CLI tests for mutation evaluation and lifeline history.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from tools.muscle.cli import lifeline, long_eval_group


def test_long_eval_mutate_runs_mutation_runner(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "service.py"
    target.write_text("value = 1\n", encoding="utf-8")

    with patch("tools.muscle.code_review.mutation_runner.MutationRunner") as mock_cls:
        mock_runner = MagicMock()
        mock_runner.run.return_value = {
            "killed": 1,
            "survived": 1,
            "timeouts": 0,
            "report_paths": {"json": "/tmp/mutation.json"},
        }
        mock_cls.return_value = mock_runner
        result = runner.invoke(
            long_eval_group,
            ["mutate", "--target", str(target)],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_runner.run.assert_called_once()


def test_lifeline_attaches_history_forensics(tmp_path: Path) -> None:
    runner = CliRunner()
    target = tmp_path / "test.py"
    target.write_text("x = 1\n", encoding="utf-8")
    env = os.environ.copy()
    env["MINIMAX_API_KEY"] = "test-key"

    class _FakeClient:
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key

        def chat(self, messages):
            assert "Git history forensics" in messages[1]["content"]
            return "ok", MagicMock(total=42)

    with patch("tools.muscle.m27_client.M27Client", _FakeClient):
        with patch("tools.muscle.cli._resolve_project_context", return_value=(tmp_path, None)):
            with patch("tools.muscle.git_history_forensics.GitHistoryForensics") as mock_cls:
                mock_forensics = MagicMock()
                mock_forensics.analyze.return_value = {
                    "available": True,
                    "summary": "Git history forensics:\n- Repo root: /tmp/repo",
                    "report_paths": {"json": "/tmp/history.json"},
                }
                mock_cls.return_value = mock_forensics
                result = runner.invoke(
                    lifeline,
                    [
                        "--target",
                        str(target),
                        "--prompt",
                        "investigate this",
                        "--history",
                    ],
                    env=env,
                    catch_exceptions=False,
                )

    assert result.exit_code == 0
