"""Unit tests for codex_cli_client.py (the codex-subscription provider)."""

from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import muscle.codex_cli_client
from muscle.codex_cli_client import CodexCliClient, ensure_chatgpt_login
from muscle.providers import ProviderBillingError, ProviderError

FAKE_BINARY = "/usr/local/bin/codex"


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[FAKE_BINARY], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _make_client(**kwargs: object) -> CodexCliClient:
    with patch("muscle.codex_cli_client.shutil.which", return_value=FAKE_BINARY):
        return CodexCliClient(verify_auth=False, **kwargs)


def _has_pair(cmd: list[str], flag: str, value: str) -> bool:
    for i, token in enumerate(cmd[:-1]):
        if token == flag and cmd[i + 1] == value:
            return True
    return False


def _run_success(result_text: str = "hello", stdout: str = ""):
    def _side_effect(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        output_path = Path(cmd[cmd.index("--output-last-message") + 1])
        output_path.write_text(result_text, encoding="utf-8")
        return _proc(stdout=stdout)

    return _side_effect


class TestInit:
    def test_missing_binary_raises_clear_error(self) -> None:
        with patch("muscle.codex_cli_client.shutil.which", return_value=None):
            with pytest.raises(ProviderError, match="codex"):
                CodexCliClient()

    def test_rejects_api_key_login_status(self) -> None:
        with patch("muscle.codex_cli_client.subprocess.run", return_value=_proc("Logged in using API key")):
            with pytest.raises(ProviderError, match="API key"):
                ensure_chatgpt_login(FAKE_BINARY)

    def test_accepts_chatgpt_login_status(self) -> None:
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            return_value=_proc("Logged in using ChatGPT"),
        ):
            assert ensure_chatgpt_login(FAKE_BINARY) == "Logged in using ChatGPT"


class TestCommandConstruction:
    def test_chat_invokes_codex_exec_with_expected_flags(self) -> None:
        client = _make_client()
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            side_effect=_run_success(result_text="hello"),
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}], system="SYS TEXT")

        cmd = mock_run.call_args.args[0]
        assert cmd[:3] == [FAKE_BINARY, "exec", "-"]
        assert _has_pair(cmd, "--model", "gpt-5.5")
        assert "--json" in cmd
        assert "--output-last-message" in cmd
        assert "--ephemeral" in cmd
        assert "--ignore-rules" in cmd
        assert "--ignore-user-config" in cmd
        assert "--skip-git-repo-check" in cmd
        assert _has_pair(cmd, "--sandbox", "read-only")
        assert _has_pair(cmd, "--ask-for-approval", "never")
        assert _has_pair(cmd, "--color", "never")
        assert "--cd" in cmd
        assert mock_run.call_args.kwargs["input"] == "[system]\nSYS TEXT\n\n[user]\nhi"
        assert "hi" not in cmd
        assert "env" not in mock_run.call_args.kwargs

    def test_single_user_prompt_without_system_passes_through_plain(self) -> None:
        client = _make_client()
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            side_effect=_run_success(result_text="hello"),
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}])
        assert mock_run.call_args.kwargs["input"] == "hi"


class TestResultParsing:
    def test_reads_final_response_file(self) -> None:
        client = _make_client()
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            side_effect=_run_success(result_text="final answer"),
        ):
            text, _usage = client.chat([{"role": "user", "content": "hi"}])
        assert text == "final answer"

    def test_parses_token_count_jsonl_usage(self) -> None:
        usage_event = {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 3,
                        "output_tokens": 4,
                        "reasoning_output_tokens": 5,
                    }
                },
            },
        }
        client = _make_client()
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            side_effect=_run_success(result_text="final", stdout=json.dumps(usage_event)),
        ):
            _text, usage = client.chat([{"role": "user", "content": "hi"}])
        assert usage.input_tokens == 10
        assert usage.cached_input_tokens == 3
        assert usage.output_tokens == 4
        assert usage.reasoning_tokens == 5

    def test_estimates_usage_when_jsonl_has_no_usage(self) -> None:
        client = _make_client()
        sink: dict[str, object] = {}
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            side_effect=_run_success(result_text="final answer"),
        ):
            _text, usage = client.chat(
                [{"role": "user", "content": "a prompt long enough to estimate"}],
                _metadata_sink=sink,
            )
        assert usage.input_tokens > 0
        assert usage.output_tokens > 0
        assert sink["usage_estimated"] is True


class TestErrorMapping:
    def test_usage_limit_maps_to_billing_error(self) -> None:
        client = _make_client()
        proc = _proc(stderr="usage limit reached", returncode=1)
        with patch("muscle.codex_cli_client.subprocess.run", return_value=proc):
            with pytest.raises(ProviderBillingError):
                client.chat([{"role": "user", "content": "hi"}])

    def test_auth_error_maps_to_provider_error(self) -> None:
        client = _make_client()
        proc = _proc(stderr="please log in", returncode=1)
        with patch("muscle.codex_cli_client.subprocess.run", return_value=proc):
            with pytest.raises(ProviderError, match="not authenticated"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_timeout_maps_to_provider_error(self) -> None:
        client = _make_client(timeout=30)
        with patch(
            "muscle.codex_cli_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired([FAKE_BINARY], timeout=30),
        ):
            with pytest.raises(ProviderError, match="timed out"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_missing_output_file_raises_malformed_output_error(self) -> None:
        client = _make_client()
        with patch("muscle.codex_cli_client.subprocess.run", return_value=_proc()):
            with pytest.raises(ProviderError, match="final response file"):
                client.chat([{"role": "user", "content": "hi"}])

    def test_module_does_not_manage_codex_auth_tokens(self) -> None:
        source = inspect.getsource(muscle.codex_cli_client)
        assert "CODEX_ACCESS_TOKEN" not in source
        assert "OPENAI_API_KEY" not in source
