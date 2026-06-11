"""Unit tests for claude_cli_client.py (the claude-subscription provider).

COMPLIANCE INVARIANTS under test:
- MUSCLE only spawns the official `claude` binary as a subprocess.
- It never reads, stores, transmits, or accepts CLAUDE_CODE_OAUTH_TOKEN or
  claude.ai credentials, and never offers claude.ai login (see
  test_never_touches_oauth_token: zero occurrences in module source, and the
  subprocess environment is passed through untouched — no env= kwarg).
- Headless `claude -p` draws from the separate monthly "Agent SDK credit"
  pool — billing errors must be labeled as such, never interactive quota.
- No auth probe at init (it would consume Agent SDK credit): init verifies
  only binary presence; auth failures surface at first call.

All tests mock subprocess.run and shutil.which — the real binary is NEVER
invoked.
"""

import inspect
import json
import logging
import subprocess
from unittest.mock import patch

import pytest
from pydantic import BaseModel

import muscle.claude_cli_client
from muscle.claude_cli_client import ClaudeCliClient
from muscle.providers import ProviderBillingError, ProviderError

FAKE_BINARY = "/usr/local/bin/claude"


def _make_client(**kwargs) -> ClaudeCliClient:
    with patch("muscle.claude_cli_client.shutil.which", return_value=FAKE_BINARY):
        return ClaudeCliClient(**kwargs)


def _proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=[FAKE_BINARY], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _result_stdout(result: str = "hello", usage: dict | None = None, is_error: bool = False) -> str:
    data: dict = {"type": "result", "result": result, "is_error": is_error}
    if usage is not None:
        data["usage"] = usage
    return json.dumps(data)


def _has_pair(cmd: list[str], flag: str, value: str) -> bool:
    """True when `flag` appears in cmd immediately followed by `value`."""
    for i, token in enumerate(cmd[:-1]):
        if token == flag and cmd[i + 1] == value:
            return True
    return False


class _TrivialSchema(BaseModel):
    ok: bool


class TestInit:
    def test_missing_binary_raises_clear_error(self):
        with patch("muscle.claude_cli_client.shutil.which", return_value=None):
            with pytest.raises(ProviderError) as exc_info:
                ClaudeCliClient()
        message = str(exc_info.value)
        assert "claude" in message
        assert "Install" in message
        assert "log in" in message


class TestCommandConstruction:
    def test_chat_invokes_print_mode_with_expected_flags(self):
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}], system="SYS TEXT")
        cmd = mock_run.call_args.args[0]
        assert "-p" in cmd
        assert _has_pair(cmd, "--output-format", "json")
        assert _has_pair(cmd, "--model", "claude-opus-4-8")
        assert _has_pair(cmd, "--effort", "medium")
        assert _has_pair(cmd, "--tools", "")
        assert "--no-session-persistence" in cmd
        assert _has_pair(cmd, "--system-prompt", "SYS TEXT")
        # The prompt goes via stdin, never argv.
        assert mock_run.call_args.kwargs["input"] == "hi"
        assert "hi" not in cmd

    def test_no_system_prompt_flag_when_system_absent(self):
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}])
        cmd = mock_run.call_args.args[0]
        assert "--system-prompt" not in cmd

    def test_thinking_adaptive_maps_to_effort_high(self):
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}], thinking="adaptive")
        assert _has_pair(mock_run.call_args.args[0], "--effort", "high")

    def test_thinking_disabled_maps_to_effort_medium(self):
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}], thinking="disabled")
        assert _has_pair(mock_run.call_args.args[0], "--effort", "medium")


class TestResultParsing:
    def test_parses_result_and_usage(self):
        client = _make_client()
        stdout = _result_stdout(
            result="hello",
            usage={"input_tokens": 7, "output_tokens": 3, "cache_read_input_tokens": 2},
        )
        with patch("muscle.claude_cli_client.subprocess.run", return_value=_proc(stdout)):
            text, usage = client.chat([{"role": "user", "content": "hi"}])
        assert text == "hello"
        # Same cache_read folding invariant as the HTTP path: input_tokens is
        # the FULL prompt size (fresh + cached), cached is the subset.
        assert usage.input_tokens == 9
        assert usage.output_tokens == 3
        assert usage.cached_input_tokens == 2

    def test_estimates_usage_when_cli_omits_it(self, caplog):
        client = _make_client()
        stdout = _result_stdout(result="hello world response")
        sink: dict = {}
        with caplog.at_level(logging.INFO, logger="muscle.claude_cli_client"):
            with patch("muscle.claude_cli_client.subprocess.run", return_value=_proc(stdout)):
                text, usage = client.chat(
                    [{"role": "user", "content": "a prompt long enough to estimate"}],
                    _metadata_sink=sink,
                )
        assert text == "hello world response"
        assert usage.input_tokens > 0
        assert usage.output_tokens > 0
        assert sink["usage_estimated"] is True
        assert any(
            "estimat" in record.getMessage().lower()
            for record in caplog.records
            if record.levelno == logging.INFO
        )

    def test_invalid_json_stdout_raises_with_stderr_context(self):
        client = _make_client()
        proc = _proc(stdout="not json", stderr="boom-stderr-context")
        with patch("muscle.claude_cli_client.subprocess.run", return_value=proc):
            with pytest.raises(ProviderError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
        assert "boom-stderr-context" in str(exc_info.value)


class TestErrorMapping:
    def test_credit_exhaustion_maps_to_billing_error(self):
        client = _make_client()
        proc = _proc(stderr="You've hit your usage limit", returncode=1)
        with patch("muscle.claude_cli_client.subprocess.run", return_value=proc):
            with pytest.raises(ProviderBillingError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
        assert "Agent SDK credit" in str(exc_info.value)

    def test_not_logged_in_maps_to_clear_error(self):
        client = _make_client()
        proc = _proc(stderr="Please log in", returncode=1)
        with patch("muscle.claude_cli_client.subprocess.run", return_value=proc):
            with pytest.raises(ProviderError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
        message = str(exc_info.value)
        assert "`claude`" in message
        assert "authenticate" in message

    def test_is_error_result_with_billing_text(self):
        client = _make_client()
        stdout = _result_stdout(result="You are out of credit for this month", is_error=True)
        with patch("muscle.claude_cli_client.subprocess.run", return_value=_proc(stdout)):
            with pytest.raises(ProviderBillingError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
        assert "Agent SDK credit" in str(exc_info.value)

    def test_timeout_maps_to_provider_error(self):
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=FAKE_BINARY, timeout=600),
        ):
            with pytest.raises(ProviderError) as exc_info:
                client.chat([{"role": "user", "content": "hi"}])
        assert "timed out" in str(exc_info.value)


class TestCompliance:
    def test_never_touches_oauth_token(self):
        source = inspect.getsource(muscle.claude_cli_client)
        # The token name must not appear anywhere in the module — not even in
        # the docstring — so there is no code path that could read it.
        assert source.count("CLAUDE_CODE_OAUTH_TOKEN") == 0
        # The subprocess environment is passed through untouched: no env= kwarg.
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat([{"role": "user", "content": "hi"}])
        assert "env" not in mock_run.call_args.kwargs


class TestPromptRendering:
    def test_multi_turn_prompt_rendering(self):
        client = _make_client()
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat(messages)
        assert mock_run.call_args.kwargs["input"] == "[user]\nq1\n\n[assistant]\na1\n\n[user]\nq2"

    def test_single_user_message_renders_bare(self):
        client = _make_client()
        with patch(
            "muscle.claude_cli_client.subprocess.run", return_value=_proc(_result_stdout())
        ) as mock_run:
            client.chat([{"role": "user", "content": "just the content"}])
        assert mock_run.call_args.kwargs["input"] == "just the content"


class TestInheritedMachinery:
    def test_chat_structured_inherited_machinery(self, tmp_path):
        client = _make_client(cache_db_path=tmp_path / "c.db")
        stdout = _result_stdout(
            result='{"ok": true}',
            usage={"input_tokens": 5, "output_tokens": 2},
        )
        with patch("muscle.claude_cli_client.subprocess.run", return_value=_proc(stdout)):
            result = client.chat_structured(_TrivialSchema, [{"role": "user", "content": "hi"}])
        assert isinstance(result, _TrivialSchema)
        assert result.ok is True

    def test_chat_streaming_yields_single_final_chunk(self):
        client = _make_client()
        stdout = _result_stdout(result="streamed", usage={"input_tokens": 4, "output_tokens": 2})
        with patch("muscle.claude_cli_client.subprocess.run", return_value=_proc(stdout)):
            chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))
        assert len(chunks) == 1
        text, usage = chunks[0]
        assert text == "streamed"
        assert usage is not None and usage.output_tokens == 2


class TestMessageValidationParity:
    """The override must validate messages exactly like the base chat()."""

    def test_non_list_messages_raises_type_error(self):
        client = _make_client()
        with pytest.raises(TypeError):
            client.chat("not a list")  # type: ignore[arg-type]

    def test_empty_messages_returns_empty_success(self):
        client = _make_client()
        with patch("muscle.claude_cli_client.subprocess.run") as mock_run:
            text, usage = client.chat([])
        assert text == ""
        assert usage.input_tokens == 0 and usage.output_tokens == 0
        mock_run.assert_not_called()

    def test_message_missing_role_raises_value_error(self):
        client = _make_client()
        with pytest.raises(ValueError):
            client.chat([{"content": "hi"}])
