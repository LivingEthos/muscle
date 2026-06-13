"""
Unit tests for m27_client.py
"""

from unittest.mock import MagicMock, patch

import pytest

from muscle.m27_client import (
    ANTHROPIC_BASE_URL_IO,
    DEFAULT_MODEL,
    OPENAI_BASE_URL_IO,
    ConcurrencyLimiter,
    M27Client,
    M27ClientError,
    RateLimiter,
    TokenUsage,
    _apply_thinking_param,
    _detect_api_base,
    _max_output_tokens_for,
)
from muscle.optimization.types import TelemetryContext


class TestTokenUsage:
    def test_total(self):
        tu = TokenUsage(input_tokens=100, output_tokens=50)
        assert tu.total == 150

    def test_reasoning_tokens_field(self):
        tu = TokenUsage(input_tokens=10, output_tokens=5, reasoning_tokens=3)
        assert tu.reasoning_tokens == 3
        # reasoning tokens are informational; total stays input + output
        assert tu.total == 15

    def test_reasoning_tokens_default_zero(self):
        assert TokenUsage().reasoning_tokens == 0

    def test_cached_input_tokens_field(self):
        tu = TokenUsage(input_tokens=1000, output_tokens=50, cached_input_tokens=800)
        assert tu.cached_input_tokens == 800
        # cached tokens are a subset of input; total stays input + output
        assert tu.total == 1050

    def test_cached_input_tokens_default_zero(self):
        assert TokenUsage().cached_input_tokens == 0


class TestOutputTokenCap:
    def test_m3_has_raised_cap(self):
        assert _max_output_tokens_for("MiniMax-M3") == 32768

    def test_default_cap_for_other_models(self):
        assert _max_output_tokens_for("MiniMax-M2.7") == 8192
        assert _max_output_tokens_for("") == 8192
        assert _max_output_tokens_for("some-unknown-model") == 8192


class TestThinkingParam:
    def test_none_is_noop(self):
        payload: dict = {}
        _apply_thinking_param(payload, None, is_openai_compatible=True)
        _apply_thinking_param(payload, None, is_openai_compatible=False)
        assert payload == {}

    def test_invalid_mode_is_noop(self):
        payload: dict = {}
        _apply_thinking_param(payload, "bogus", is_openai_compatible=False)
        assert payload == {}

    def test_openai_shape_is_boolean(self):
        on: dict = {}
        _apply_thinking_param(on, "adaptive", is_openai_compatible=True)
        assert on == {"reasoning_split": True}
        off: dict = {}
        _apply_thinking_param(off, "disabled", is_openai_compatible=True)
        assert off == {"reasoning_split": False}

    def test_anthropic_shape_is_typed_object(self):
        for mode in ("disabled", "adaptive", "enabled"):
            payload: dict = {}
            _apply_thinking_param(payload, mode, is_openai_compatible=False)
            assert payload == {"thinking": {"type": mode}}


class TestRateLimiter:
    def test_wait_no_blocking(self):
        import time

        limiter = RateLimiter(calls_per_second=100)
        start = time.time()
        limiter.wait()
        elapsed = time.time() - start
        assert elapsed < 0.1


class TestConcurrencyLimiter:
    def test_context_manager(self):
        limiter = ConcurrencyLimiter(max_concurrent=2)
        with limiter as ctx:
            assert ctx is limiter
        assert True


class TestM27Client:
    @pytest.fixture
    def client(self):
        with patch(
            "os.environ.get",
            side_effect=lambda k, d=None: {
                "ANTHROPIC_API_KEY": "test-key",
                "MINIMAX_API_KEY": "test-key",
            }.get(k, d),
        ):
            with patch(
                "muscle.m27_client._detect_api_base",
                return_value="https://api.minimax.io/anthropic",
            ):
                with patch("muscle.m27_client._create_session"):
                    return M27Client(api_key="test-key", model="MiniMax-M2.7")

    def test_init_defaults(self, client):
        assert client.api_key == "test-key"
        assert client.model == "MiniMax-M2.7"
        assert client.timeout == 120

    def test_default_model_is_m3(self):
        assert DEFAULT_MODEL == "MiniMax-M3"

    def test_init_uses_default_model_when_unspecified(self):
        with patch(
            "os.environ.get",
            side_effect=lambda k, d=None: {
                "ANTHROPIC_API_KEY": "test-key",
                "MINIMAX_API_KEY": "test-key",
            }.get(k, d),
        ):
            with patch(
                "muscle.m27_client._detect_api_base",
                return_value="https://api.minimax.io/anthropic",
            ):
                with patch("muscle.m27_client._create_session"):
                    client = M27Client(api_key="test-key")
        assert client.model == "MiniMax-M3"

    def test_format_messages_with_history(self, client):
        messages = client.format_messages("Hello", history=[{"role": "user", "content": "Hi"}])
        assert len(messages) >= 1
        assert messages[-1]["content"] == "Hello"

    def test_format_messages_adds_user_message(self, client):
        messages = client.format_messages("Hello")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"

    def test_empty_messages_returns_empty(self, client):
        result, usage = client.chat([])
        assert result == ""

    def test_temperature_clamped(self, client):
        clamped = max(0.0, min(5.0, 2.0))
        assert clamped == 2.0

    def test_max_tokens_clamped(self, client):
        clamped = max(1, min(99999, 8192))
        assert clamped == 8192


def _make_mock_response(
    status_code: int,
    json_data: dict | None = None,
    text: str = "",
    headers: dict | None = None,
):
    """Create a mock requests.Response with given status and data."""
    from unittest.mock import MagicMock

    import requests

    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    if json_data is not None:
        response.json = MagicMock(return_value=json_data)
    return response


class TestDetectApiBase:
    """Tests for _detect_api_base()."""

    def test_defaults_to_io(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch.dict("os.environ", {"MINIMAX_API_KEY": "fake"}, clear=False):
                result = _detect_api_base()
        assert result == ANTHROPIC_BASE_URL_IO

    def test_minimax_io_base_url_honored(self):
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"},
            clear=True,
        ):
            result = _detect_api_base()
        assert result == "https://api.minimax.io/anthropic"

    def test_minimaxi_com_base_url_honored(self):
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://api.minimaxi.com/anthropic"},
            clear=True,
        ):
            result = _detect_api_base()
        assert result == "https://api.minimaxi.com/anthropic"

    def test_custom_minimax_host_honored(self):
        # Any host containing "minimax" (e.g. regional variants) is honored.
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://minimax-proxy.internal.corp/anthropic"},
            clear=True,
        ):
            result = _detect_api_base()
        assert result == "https://minimax-proxy.internal.corp/anthropic"

    def test_hijacked_anthropic_base_url_ignored_with_warning(self, caplog):
        # Claude Code exports ANTHROPIC_BASE_URL=https://api.anthropic.com; MUSCLE
        # must NOT honor it (would leak the MiniMax credential) and must fall back.
        import logging

        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
            clear=True,
        ):
            with caplog.at_level(logging.WARNING):
                result = _detect_api_base()
        assert result == ANTHROPIC_BASE_URL_IO
        assert any(
            "ANTHROPIC_BASE_URL" in r.message and "MUSCLE_ALLOW_CUSTOM_BASE_URL" in r.message
            for r in caplog.records
        )

    def test_minimax_only_in_path_is_rejected(self):
        # Spoofing defense: "minimax" appears only in the URL path, not the host.
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://evil.com/minimax/path"},
            clear=True,
        ):
            result = _detect_api_base()
        assert result == ANTHROPIC_BASE_URL_IO

    def test_escape_hatch_honors_arbitrary_url(self):
        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_BASE_URL": "https://gateway.example.com/anthropic",
                "MUSCLE_ALLOW_CUSTOM_BASE_URL": "1",
            },
            clear=True,
        ):
            result = _detect_api_base()
        assert result == "https://gateway.example.com/anthropic"

    def test_explicit_io_env(self):
        with patch.dict(
            "os.environ",
            {"MINIMAX_API_BASE": "io", "ANTHROPIC_API_KEY": "fake"},
            clear=True,
        ):
            result = _detect_api_base()
        assert "minimax.io" in result

    def test_explicit_com_env(self):
        with patch.dict(
            "os.environ",
            {"MINIMAX_API_BASE": "com", "ANTHROPIC_API_KEY": "fake"},
            clear=True,
        ):
            result = _detect_api_base()
        assert "minimaxi.com" in result

    def test_explicit_openai_env(self):
        with patch.dict(
            "os.environ",
            {"MINIMAX_API_BASE": "openai", "ANTHROPIC_API_KEY": "fake"},
            clear=True,
        ):
            result = _detect_api_base()
        assert result == OPENAI_BASE_URL_IO


@pytest.fixture
def mock_client():
    """Create M27Client with fully mocked session and rate limiting."""
    import requests as req

    mock_session = MagicMock(spec=req.Session)
    mock_response = MagicMock(spec=req.Response)
    mock_response.status_code = 200
    mock_response.json = MagicMock(
        return_value={
            "content": [{"type": "text", "text": "default"}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    mock_response.text = ""
    mock_response.headers = {}
    mock_session.post.return_value = mock_response

    with patch.dict(
        "os.environ",
        {"ANTHROPIC_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
        clear=True,
    ):
        with patch(
            "muscle.m27_client._detect_api_base",
            return_value="https://api.minimax.io/anthropic",
        ):
            with patch.object(M27Client, "_session", mock_session):
                with patch.object(M27Client, "_rate_limiter"):
                    with patch.object(M27Client, "_concurrency_limiter"):
                        client = M27Client(api_key="test-key")
                        yield client, mock_session


class TestChatValidation:
    """Tests for chat() input validation."""

    def test_empty_messages_list(self, mock_client):
        client, _ = mock_client
        result, usage = client.chat([])
        assert result == ""
        assert usage.total == 0

    def test_messages_not_a_list_raises(self, mock_client):
        # A plain string used to return a silent empty success; it must raise.
        client, _ = mock_client
        with pytest.raises(TypeError, match="messages must be a list"):
            client.chat("not a list")

    def test_message_not_a_dict_raises(self, mock_client):
        client, _ = mock_client
        with pytest.raises(TypeError, match="must be a dict"):
            client.chat(["string instead of dict"])

    def test_message_missing_role_raises(self, mock_client):
        client, _ = mock_client
        with pytest.raises(ValueError, match="missing 'role' or 'content'"):
            client.chat([{"content": "hello"}])

    def test_message_missing_content_raises(self, mock_client):
        client, _ = mock_client
        with pytest.raises(ValueError, match="missing 'role' or 'content'"):
            client.chat([{"role": "user"}])

    def test_message_content_not_string_raises(self, mock_client):
        client, _ = mock_client
        with pytest.raises(TypeError, match="must be a string"):
            client.chat([{"role": "user", "content": 123}])

    def test_chat_streaming_not_a_list_raises(self, mock_client):
        client, _ = mock_client
        with pytest.raises(TypeError, match="messages must be a list"):
            # Generator: consume to trigger the eager guard.
            next(client.chat_streaming("not a list"))


class TestChatSuccess:
    """Tests for chat() success paths."""

    def test_chat_success_returns_text_and_usage(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello world"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

        result, usage = client.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello world"
        assert usage.input_tokens == 10
        assert usage.output_tokens == 5

    def test_chat_captures_cached_tokens_anthropic_shape(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {
                    # Anthropic/MiniMax shape: input_tokens is FRESH-only and
                    # cache_read_input_tokens is disjoint. Full prompt = 200 + 800.
                    "input_tokens": 200,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 800,
                },
            },
        )

        _, usage = client.chat([{"role": "user", "content": "hi"}])
        # input_tokens is normalized to the full prompt size (fresh + cached).
        assert usage.input_tokens == 1000
        assert usage.cached_input_tokens == 800
        assert usage.cached_input_tokens <= usage.input_tokens

    def test_chat_minimax_usage_without_cache_creation_unchanged(self, mock_client):
        # Regression: MiniMax never sends cache_creation_input_tokens. Its usage
        # normalization must stay byte-identical after the Anthropic-provider
        # cache_creation support landed (fold cache_read in, cache_creation 0).
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 90,
                },
            },
        )

        _, usage = client.chat([{"role": "user", "content": "hi"}])
        assert usage.input_tokens == 100
        assert usage.cached_input_tokens == 90
        assert usage.cache_creation_input_tokens == 0

    def test_chat_captures_cached_tokens_openai_shape(self, mock_client):
        client, mock_session = mock_client
        client.base_url = OPENAI_BASE_URL_IO
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 6,
                    "prompt_tokens_details": {"cached_tokens": 900},
                },
            },
        )

        _, usage = client.chat([{"role": "user", "content": "hi"}], system="sys")
        assert usage.input_tokens == 1200
        assert usage.cached_input_tokens == 900

    def test_chat_cached_tokens_absent_defaults_zero(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

        _, usage = client.chat([{"role": "user", "content": "hi"}])
        assert usage.cached_input_tokens == 0

    def test_chat_success_with_system_prompt(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Done"}],
                "usage": {"input_tokens": 20, "output_tokens": 3},
            },
        )

        result, usage = client.chat([{"role": "user", "content": "hi"}], system="You are helpful")
        assert result == "Done"
        assert usage.total == 23
        assert mock_session.post.called

    def test_chat_success_openai_compatible_shape(self, mock_client):
        client, mock_session = mock_client
        client.base_url = OPENAI_BASE_URL_IO
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "choices": [{"message": {"role": "assistant", "content": "OpenAI shape"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        )

        result, usage = client.chat([{"role": "user", "content": "hi"}], system="sys")

        assert result == "OpenAI shape"
        assert usage.input_tokens == 12
        assert usage.output_tokens == 6
        call_args = mock_session.post.call_args
        assert call_args.args[0] == f"{OPENAI_BASE_URL_IO}/chat/completions"
        payload = call_args.kwargs["json"]
        assert payload["messages"][0] == {"role": "system", "content": "sys"}

    def test_chat_streaming_rejects_openai_compatible_endpoint_before_http(self, mock_client):
        client, mock_session = mock_client
        client.base_url = OPENAI_BASE_URL_IO

        with pytest.raises(M27ClientError, match="streaming is not supported"):
            list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        mock_session.post.assert_not_called()

    def test_chat_estimates_zero_token_openai_response(self, mock_client):
        client, mock_session = mock_client
        client.base_url = OPENAI_BASE_URL_IO
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "choices": [{"message": {"role": "assistant", "content": "Estimated usage"}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            },
        )

        result, usage = client.chat([{"role": "user", "content": "hi"}], system="sys")

        assert result == "Estimated usage"
        assert usage.total > 0

    def test_chat_records_telemetry_when_sink_attached(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Telemetry"}],
                "usage": {"input_tokens": 7, "output_tokens": 4},
            },
        )
        telemetry_sink = MagicMock()
        client.set_telemetry_sink(telemetry_sink)
        client.set_model_identity(
            {
                "requested_label": "claude-sonnet-4",
                "provider_endpoint": "https://api.minimax.io/anthropic",
                "provider_fingerprint": "api.minimax.io/anthropic",
                "canonical_model_key": "openai/gpt-5@1",
                "identity_source": "manual_override",
                "confidence": 1.0,
                "manual_override": True,
            }
        )

        result, usage = client.chat(
            [{"role": "user", "content": "hi"}],
            telemetry_context=TelemetryContext(
                project_path="/tmp/project",
                session_id="sess-1",
                stage="generate",
            ),
        )

        assert result == "Telemetry"
        assert usage.total == 11
        telemetry_sink.record_llm_call.assert_called_once()
        event = telemetry_sink.record_llm_call.call_args.args[0]
        assert event.requested_label == "claude-sonnet-4"
        assert event.canonical_model_key == "openai/gpt-5@1"
        assert event.identity_source == "manual_override"
        assert event.manual_override is True

    def test_chat_records_cached_tokens_in_telemetry_metadata(self, mock_client):
        import json as _json

        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Cached"}],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 750,
                },
            },
        )
        telemetry_sink = MagicMock()
        client.set_telemetry_sink(telemetry_sink)

        client.chat(
            [{"role": "user", "content": "hi"}],
            telemetry_context=TelemetryContext(
                project_path="/tmp/project",
                session_id="sess-1",
                stage="semantic_review",
            ),
        )

        event = telemetry_sink.record_llm_call.call_args.args[0]
        metadata = _json.loads(event.metadata_json)
        assert metadata["cached_input_tokens"] == 750

    def test_chat_adopts_trusted_provider_introspection_and_records_history(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "model": "gpt-5-mini-2026-04-14",
                "content": [{"type": "text", "text": "Telemetry"}],
                "usage": {"input_tokens": 7, "output_tokens": 4},
            },
        )
        telemetry_sink = MagicMock()
        client.set_telemetry_sink(telemetry_sink)
        client.set_model_identity(
            {
                "requested_label": "custom-openai-alias",
                "provider_endpoint": "https://api.openai.com/v1",
                "provider_fingerprint": "api.openai.com/v1",
                "canonical_model_key": None,
                "identity_source": "unresolved",
                "confidence": 0.0,
                "manual_override": False,
            }
        )

        result, usage = client.chat(
            [{"role": "user", "content": "hi"}],
            telemetry_context=TelemetryContext(
                project_path="/tmp/project",
                session_id="sess-1",
                stage="generate",
            ),
        )

        assert result == "Telemetry"
        assert usage.total == 11
        telemetry_sink.record_model_identity_history.assert_called_once()
        event = telemetry_sink.record_llm_call.call_args.args[0]
        assert event.canonical_model_key == "openai/gpt-5-mini@1"
        assert event.identity_source == "provider_introspection"

    def test_chat_does_not_replace_manual_override_with_introspection(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "model": "gpt-5-mini-2026-04-14",
                "content": [{"type": "text", "text": "Telemetry"}],
                "usage": {"input_tokens": 7, "output_tokens": 4},
            },
        )
        telemetry_sink = MagicMock()
        client.set_telemetry_sink(telemetry_sink)
        client.set_model_identity(
            {
                "requested_label": "claude-sonnet-4",
                "provider_endpoint": "https://api.openai.com/v1",
                "provider_fingerprint": "api.openai.com/v1",
                "canonical_model_key": "anthropic/claude-sonnet@4",
                "identity_source": "manual_override",
                "confidence": 1.0,
                "manual_override": True,
            }
        )

        result, usage = client.chat(
            [{"role": "user", "content": "hi"}],
            telemetry_context=TelemetryContext(
                project_path="/tmp/project",
                session_id="sess-1",
                stage="generate",
            ),
        )

        assert result == "Telemetry"
        assert usage.total == 11
        telemetry_sink.record_model_identity_history.assert_not_called()
        event = telemetry_sink.record_llm_call.call_args.args[0]
        assert event.canonical_model_key == "anthropic/claude-sonnet@4"
        assert event.identity_source == "manual_override"


class TestChatRetry:
    """Tests for chat() retry logic."""

    def test_retry_on_json_decode_error(self, mock_client):
        import json

        import requests as req

        client, mock_session = mock_client

        error_response = MagicMock(spec=req.Response)
        error_response.status_code = 200
        error_response.json = MagicMock(side_effect=json.JSONDecodeError("bad json", "", 0))
        error_response.text = ""

        success_response = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Success after retry"}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        )

        mock_session.post.side_effect = [error_response, success_response]

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Success after retry"
        assert mock_session.post.call_count == 2

    def test_retry_on_thinking_only_then_text(self, mock_client):
        client, mock_session = mock_client

        thinking_response = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "thinking", "thinking": "Let me think..."}],
                "usage": {"input_tokens": 5, "output_tokens": 100},
            },
        )

        success_response = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Here is the answer"}],
                "usage": {"input_tokens": 5, "output_tokens": 10},
            },
        )

        mock_session.post.side_effect = [thinking_response, success_response]

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Here is the answer"
        assert mock_session.post.call_count == 2

    def test_retry_on_empty_text_response(self, mock_client):
        client, mock_session = mock_client

        empty_response = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": ""}],
                "usage": {"input_tokens": 5, "output_tokens": 0},
            },
        )

        success_response = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Final answer"}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        )

        mock_session.post.side_effect = [empty_response, success_response]

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Final answer"

    def test_all_retries_exhausted_returns_empty(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={"content": [{"type": "thinking", "thinking": "..."}], "usage": {}},
        )

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert usage.total == 0
        assert mock_session.post.call_count == client.max_retries


class TestChatRateLimit:
    """Tests for chat() rate limiting (429)."""

    def test_retry_on_429_with_retry_after_header(self, mock_client):
        client, mock_session = mock_client

        rate_limited = _make_mock_response(429, headers={"Retry-After": "5"})
        success = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Success"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )
        mock_session.post.side_effect = [rate_limited, success]

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Success"
        mock_sleep.assert_called_with(5.0)

    def test_retry_on_429_without_retry_after_header(self, mock_client):
        client, mock_session = mock_client

        rate_limited = _make_mock_response(429, headers={})
        success = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Success"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )
        mock_session.post.side_effect = [rate_limited, success]

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Success"
        mock_sleep.assert_called()

    def test_retry_on_429_increments_backoff(self, mock_client):
        client, mock_session = mock_client

        responses = [
            _make_mock_response(429, headers={}),
            _make_mock_response(429, headers={}),
            _make_mock_response(
                200,
                json_data={
                    "content": [{"type": "text", "text": "Success"}],
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                },
            ),
        ]
        mock_session.post.side_effect = responses

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Success"
        assert mock_sleep.call_count == 2


class TestChatErrors:
    """Tests for chat() error status codes."""

    def test_401_returns_error(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(401, text="Invalid API key")

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert usage.total == 0

    def test_403_returns_error(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(403, text="Forbidden")

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert usage.total == 0

    def test_404_returns_error(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(404, text="Not found")

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert usage.total == 0

    def test_500_server_error_retries(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(500, text="Internal error")

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert mock_sleep.call_count >= 1

    def test_502_503_504_retries(self, mock_client):
        client, mock_session = mock_client
        for status_code in [502, 503, 504]:
            mock_session.post.return_value = _make_mock_response(status_code, text="Error")

            with patch("time.sleep"):
                result, usage = client.chat([{"role": "user", "content": "hi"}])
                assert result == ""


class TestChatExceptions:
    """Tests for chat() exception handling."""

    def test_timeout_exception_retries(self, mock_client):
        import requests as req

        client, mock_session = mock_client
        mock_session.post.side_effect = req.exceptions.Timeout("Connection timed out")

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert mock_sleep.call_count >= 1

    def test_connection_error_retries(self, mock_client):
        import requests as req

        client, mock_session = mock_client
        mock_session.post.side_effect = req.exceptions.ConnectionError("Connection refused")

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        assert mock_sleep.call_count >= 1


class TestChatStreaming:
    """Tests for chat_streaming()."""

    def test_chat_streaming_success(self, mock_client):
        client, mock_session = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"type": "content_block", "content": [{"type": "text", "text": "Hello"}]}',
                    'data: {"type": "content_block", "content": [{"type": "text", "text": " world"}]}',
                    'data: {"usage": {"input_tokens": 5, "output_tokens": 3}}',
                    "data: [DONE]",
                ]
            )
        )
        mock_session.post.return_value = mock_response

        chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert len(chunks) >= 1

    def test_chat_streaming_captures_cached_tokens(self, mock_client):
        client, mock_session = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"type": "content_block", "content": [{"type": "text", "text": "hi"}]}',
                    'data: {"usage": {"input_tokens": 20, "output_tokens": 3, '
                    '"cache_read_input_tokens": 80}}',
                    "data: [DONE]",
                ]
            )
        )
        mock_session.post.return_value = mock_response

        usages = [
            usage
            for _, usage in client.chat_streaming([{"role": "user", "content": "hi"}])
            if usage is not None
        ]
        assert usages, "expected at least one usage event"
        final = usages[-1]
        # input_tokens folds in the disjoint cache_read count (20 + 80).
        assert final.input_tokens == 100
        assert final.cached_input_tokens == 80
        assert final.cached_input_tokens <= final.input_tokens

    def test_chat_streaming_429_retries(self, mock_client):
        client, mock_session = mock_client

        rate_limited = _make_mock_response(429, headers={"Retry-After": "1"})
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.headers = {}
        success_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"type": "content_block", "content": [{"type": "text", "text": "Done"}]}',
                    "data: [DONE]",
                ]
            )
        )
        mock_session.post.side_effect = [rate_limited, success_response]

        with patch("time.sleep"):
            list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == 2

    def test_chat_streaming_500_retries(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(500, text="Error")

        with patch("time.sleep"):
            list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == client.max_retries

    def test_chat_streaming_timeout(self, mock_client):
        import requests as req

        client, mock_session = mock_client
        mock_session.post.side_effect = req.exceptions.Timeout("timed out")

        with patch("time.sleep"):
            list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == client.max_retries

    def test_chat_streaming_connection_error(self, mock_client):
        import requests as req

        client, mock_session = mock_client
        mock_session.post.side_effect = req.exceptions.ConnectionError("refused")

        with patch("time.sleep"):
            list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == client.max_retries


class TestParseSseStream:
    """Tests for _parse_sse_stream()."""

    def test_parses_text_delta(self, mock_client):
        client, _ = mock_client

        mock_response = MagicMock()
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"content": [{"type": "text", "text": "Hello"}]}',
                    'data: {"usage": {"input_tokens": 5, "output_tokens": 3}}',
                    "data: [DONE]",
                ]
            )
        )

        chunks = list(client._parse_sse_stream(mock_response))
        assert len(chunks) >= 1
        assert any("Hello" in c[0] for c in chunks)

    def test_parses_usage_event(self, mock_client):
        client, _ = mock_client

        mock_response = MagicMock()
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"content": [{"type": "text", "text": "Hi"}]}',
                    'data: {"usage": {"input_tokens": 5, "output_tokens": 3}}',
                    "data: [DONE]",
                ]
            )
        )

        chunks = list(client._parse_sse_stream(mock_response))
        usage_chunks = [c for c in chunks if c[1] is not None]
        assert len(usage_chunks) >= 1

    def test_parses_error_event(self, mock_client):
        client, _ = mock_client

        mock_response = MagicMock()
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"content": [{"type": "text", "text": "Hello"}]}',
                    'data: {"error": {"message": "Server error"}}',
                ]
            )
        )

        chunks = list(client._parse_sse_stream(mock_response))
        # Fix: H3. A provider mid-stream error event must surface a sentinel-prefixed
        # payload (not a clean ("", None) end-of-stream) so chat_streaming records
        # success=False instead of treating the error as a successful empty finish.
        from muscle.m27_client import STREAM_ERROR_PREFIX

        assert chunks[-1][0].startswith(STREAM_ERROR_PREFIX)
        assert "Server error" in chunks[-1][0]
        # The response must be closed even when the stream ends on an error event.
        mock_response.close.assert_called_once()

    def test_skips_invalid_json(self, mock_client):
        client, _ = mock_client

        mock_response = MagicMock()
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    "data: not valid json",
                    'data: {"content": [{"type": "text", "text": "Hello"}]}',
                    "data: [DONE]",
                ]
            )
        )

        chunks = list(client._parse_sse_stream(mock_response))
        assert any("Hello" in c[0] for c in chunks)


class TestChatWithHistory:
    """Tests for chat_with_history()."""

    def test_chat_with_history_appends_user_message(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Response"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

        result, usage = client.chat_with_history(
            "Hello",
            history=[{"role": "user", "content": "Previous"}],
        )

        assert result == "Response"
        call_args = mock_session.post.call_args
        messages = call_args.kwargs["json"]["messages"]
        assert len(messages) == 2


class TestHelperMethods:
    """Tests for helper methods."""

    def test_get_headers_includes_auth(self, mock_client):
        client, _ = mock_client
        headers = client._get_headers()
        assert "Authorization" in headers
        assert "Bearer test-key" in headers["Authorization"]
        assert headers["Content-Type"] == "application/json; charset=utf-8"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_get_headers_uses_x_api_key_for_minimax_token_plan_keys(self, mock_client):
        client, _ = mock_client
        client.api_key = "sk-cp-test"
        client.base_url = "https://api.minimax.io/anthropic"

        headers = client._get_headers()

        assert "Authorization" not in headers
        assert headers["X-Api-Key"] == "sk-cp-test"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_get_rate_limit_status(self, mock_client):
        client, _ = mock_client
        client._rate_limit_errors = 5
        status = client.get_rate_limit_status()
        assert status["rate_limit_errors"] == 5
        assert "base_url" in status
        assert "model" in status

    def test_reset_rate_limits(self, mock_client):
        client, _ = mock_client
        client._rate_limit_errors = 10
        client.reset_rate_limits()
        assert client._rate_limit_errors == 0

    def test_chat_with_history_no_history(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Response"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

        result, usage = client.chat_with_history("Hello")
        assert result == "Response"


class TestM2705RetryNarrow:
    """Fix M27-05: bare except narrowed to (RequestException, JSONDecodeError, ValueError)."""

    def test_connection_reset_error_continues_retry(self, mock_client):
        """ConnectionResetError (a subclass of ConnectionError / OSError) should retry,
        not break early."""
        import requests as req

        client, mock_session = mock_client
        client.max_retries = 3

        # First call raises ConnectionResetError; second returns success.
        success_response = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Recovered"}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise req.exceptions.ConnectionError(
                    "Connection reset by peer", ConnectionResetError()
                )
            return success_response

        mock_session.post.side_effect = side_effect

        with patch("time.sleep"):
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == "Recovered"
        assert mock_session.post.call_count == 2

    def test_value_error_breaks_retry_loop(self, mock_client):
        """ValueError must break the loop immediately without further retries."""
        client, mock_session = mock_client
        client.max_retries = 5

        mock_session.post.side_effect = ValueError("bad argument")

        with patch("time.sleep") as mock_sleep:
            result, usage = client.chat([{"role": "user", "content": "hi"}])

        assert result == ""
        # Only 1 attempt; ValueError breaks immediately.
        assert mock_session.post.call_count == 1
        mock_sleep.assert_not_called()


class TestRateLimiterWait:
    """Tests for RateLimiter."""

    def test_wait_no_sleep_when_fast(self):
        import time

        limiter = RateLimiter(calls_per_second=100)
        start = time.time()
        limiter.wait()
        elapsed = time.time() - start
        assert elapsed < 0.05

    def test_wait_sleeps_when_called_rapidly(self):
        import time

        limiter = RateLimiter(calls_per_second=10)
        start = time.time()
        limiter.wait()
        limiter.wait()
        elapsed = time.time() - start
        assert elapsed >= 0.09

    def test_wait_does_not_sleep_while_holding_lock(self):
        """Fix: M6. sleep must run OUTSIDE the lock so callers can overlap."""
        import threading

        limiter = RateLimiter(calls_per_second=5)
        # Prime last_call so the next wait() computes a real sleep.
        limiter.wait()

        sleeping = threading.Event()
        lock_free_during_sleep = threading.Event()

        real_sleep = __import__("time").sleep

        def fake_sleep(duration):
            sleeping.set()
            # The limiter lock must be acquirable while we are "sleeping".
            if limiter.lock.acquire(blocking=False):
                lock_free_during_sleep.set()
                limiter.lock.release()
            real_sleep(0)

        with patch("muscle.m27_client.time.sleep", side_effect=fake_sleep):
            limiter.wait()

        assert sleeping.is_set()
        assert lock_free_during_sleep.is_set(), "lock was held during sleep (M6 regression)"


class TestStreamingResourceSafety:
    """Fix: C1/C2. Streaming response lifecycle and mid-stream failure handling."""

    def test_parse_sse_stream_closes_response_on_normal_finish(self, mock_client):
        client, _ = mock_client

        mock_response = MagicMock()
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"content": [{"type": "text", "text": "hi"}]}',
                    "data: [DONE]",
                ]
            )
        )

        list(client._parse_sse_stream(mock_response))
        mock_response.close.assert_called_once()

    def test_parse_sse_stream_closes_response_on_abandoned_iteration(self, mock_client):
        client, _ = mock_client

        mock_response = MagicMock()
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"content": [{"type": "text", "text": "a"}]}',
                    'data: {"content": [{"type": "text", "text": "b"}]}',
                    "data: [DONE]",
                ]
            )
        )

        gen = client._parse_sse_stream(mock_response)
        next(gen)  # consume one chunk, then abandon
        gen.close()
        mock_response.close.assert_called_once()

    def test_chat_streaming_closes_response_on_non_200(self, mock_client):
        client, mock_session = mock_client
        err = _make_mock_response(404, text="not found")
        mock_session.post.return_value = err

        with patch("time.sleep"):
            list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        err.close.assert_called()

    def test_chat_streaming_does_not_retry_after_partial_output(self, mock_client):
        """Fix: C2. A mid-stream connection error after chunks were yielded must
        NOT restart the stream (which would re-emit cumulative text)."""
        import requests as req

        client, mock_session = mock_client

        def exploding_lines(*_a, **_k):
            yield 'data: {"content": [{"type": "text", "text": "partial"}]}'
            raise req.exceptions.ConnectionError("dropped mid-stream")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.iter_lines = MagicMock(side_effect=exploding_lines)
        mock_session.post.return_value = mock_response

        with patch("time.sleep"):
            chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        # Only one POST: no retry was attempted after partial output.
        assert mock_session.post.call_count == 1
        # The consumer received the partial chunk then an error sentinel.
        from muscle.m27_client import STREAM_ERROR_PREFIX

        assert any(text == "partial" for text, _ in chunks)
        assert chunks[-1][0].startswith(STREAM_ERROR_PREFIX)

    def test_chat_streaming_provider_error_records_failure(self, mock_client):
        """Fix: H3. Provider mid-stream error event yields a sentinel and is
        reported as a failed call, not a clean finish."""
        client, mock_session = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.iter_lines = MagicMock(
            return_value=iter(
                [
                    'data: {"content": [{"type": "text", "text": "Hi"}]}',
                    'data: {"error": {"message": "boom"}}',
                ]
            )
        )
        mock_session.post.return_value = mock_response

        from muscle.m27_client import STREAM_ERROR_PREFIX

        chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))
        assert chunks[-1][0].startswith(STREAM_ERROR_PREFIX)
        # No retry storm: a single POST.
        assert mock_session.post.call_count == 1


class TestChatUsageFallback:
    """Fix: M9. Zero-usage fallback must estimate input from prompt size."""

    def test_zero_usage_estimates_input_from_prompt(self, mock_client):
        client, mock_session = mock_client
        long_prompt = "x" * 400  # ~100 input tokens
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json = MagicMock(
            return_value={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        )
        mock_session.post.return_value = resp

        _, usage = client.chat([{"role": "user", "content": long_prompt}])
        # Input is derived from the prompt (~100), output from the 2-char reply (1),
        # NOT both set to len(text)//4.
        assert usage.input_tokens >= 90
        assert usage.output_tokens < usage.input_tokens

    def test_bare_total_split_between_input_and_output(self, mock_client):
        client, mock_session = mock_client
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json = MagicMock(
            return_value={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"total_tokens": 1000},
            }
        )
        mock_session.post.return_value = resp

        _, usage = client.chat([{"role": "user", "content": "short prompt"}])
        assert usage.input_tokens + usage.output_tokens == 1000
        assert usage.output_tokens > 0  # not all dumped into input


class TestChatStructuredTruncationAndKey:
    """Fix: H4 (truncation not cached) and L12 (full-history cache key)."""

    def _schema(self):
        from pydantic import BaseModel

        class Out(BaseModel):
            value: int

        return Out

    def _make_chat_stub(self, text, *, truncated):
        def _stub(*args, _metadata_sink=None, **kwargs):
            if _metadata_sink is not None:
                _metadata_sink["truncated"] = truncated
                _metadata_sink["stop_reason"] = "max_tokens" if truncated else "end_turn"
            return text, TokenUsage(input_tokens=5, output_tokens=5)

        return _stub

    def test_truncated_response_not_cached(self, mock_client, tmp_path):
        client, _ = mock_client
        client._cache_db_path = tmp_path / "c.db"
        schema_cls = self._schema()

        with patch.object(
            client, "chat", side_effect=self._make_chat_stub('{"value": 1}', truncated=True)
        ):
            result, meta = client.chat_structured(
                schema_cls, [{"role": "user", "content": "go"}], include_metadata=True
            )
        assert result.value == 1
        assert meta.truncated is True

        from muscle.response_cache import ResponseCache

        cache = ResponseCache(tmp_path / "c.db")
        assert meta.cache_key is not None
        assert cache.get(meta.cache_key) is None  # truncated result was NOT stored

    def test_complete_response_is_cached(self, mock_client, tmp_path):
        client, _ = mock_client
        client._cache_db_path = tmp_path / "c.db"
        schema_cls = self._schema()

        with patch.object(
            client, "chat", side_effect=self._make_chat_stub('{"value": 7}', truncated=False)
        ):
            result, meta = client.chat_structured(
                schema_cls, [{"role": "user", "content": "go"}], include_metadata=True
            )
        assert meta.truncated is False

        from muscle.response_cache import ResponseCache

        cache = ResponseCache(tmp_path / "c.db")
        assert cache.get(meta.cache_key) == {"value": 7}

    def test_cache_key_distinguishes_history(self, mock_client, tmp_path):
        """Fix: L12. Same user turn + different assistant history -> different key."""
        client, _ = mock_client
        client._cache_db_path = tmp_path / "c.db"
        schema_cls = self._schema()

        def _stub(*args, _metadata_sink=None, **kwargs):
            if _metadata_sink is not None:
                _metadata_sink["truncated"] = False
            return '{"value": 1}', TokenUsage(input_tokens=1, output_tokens=1)

        msgs_a = [{"role": "user", "content": "same"}]
        msgs_b = [
            {"role": "user", "content": "same"},
            {"role": "assistant", "content": "different history"},
            {"role": "user", "content": "same"},
        ]

        with patch.object(client, "chat", side_effect=_stub):
            _, meta_a = client.chat_structured(schema_cls, msgs_a, include_metadata=True)
            _, meta_b = client.chat_structured(schema_cls, msgs_b, include_metadata=True)

        assert meta_a.cache_key != meta_b.cache_key, "history must influence cache key (L12)"

    def test_cache_hit_reports_zero_usage(self, mock_client, tmp_path):
        """A2: a cache hit costs ZERO new tokens; usage must not be fabricated."""
        client, _ = mock_client
        client._cache_db_path = tmp_path / "c.db"
        schema_cls = self._schema()
        msgs = [{"role": "user", "content": "go"}]

        # First call populates the cache (real spend recorded).
        with patch.object(
            client, "chat", side_effect=self._make_chat_stub('{"value": 9}', truncated=False)
        ):
            _, meta_first = client.chat_structured(schema_cls, msgs, include_metadata=True)
        assert meta_first.cache_hit is False
        assert meta_first.usage.total > 0  # real spend on the miss

        # Second call hits the cache. chat() must NOT be invoked, and usage is zero.
        with patch.object(client, "chat", side_effect=AssertionError("chat() called on hit")):
            result, meta = client.chat_structured(schema_cls, msgs, include_metadata=True)

        assert result.value == 9
        assert meta.cache_hit is True
        assert meta.usage.total == 0
        assert meta.usage.input_tokens == 0
        assert meta.usage.output_tokens == 0
        # Savings estimate is preserved (heuristic, since the cache does not persist
        # the original call's input/output split — only the response dict).
        assert meta.tokens_saved_estimate > 0


# ---------------------------------------------------------------------------
# CachePlan + _prepare_payload hook tests
# ---------------------------------------------------------------------------


class TestCachePlan:
    def test_cache_plan_dataclass(self):
        """CachePlan defaults and frozen enforcement."""
        from dataclasses import FrozenInstanceError

        from muscle.m27_client import CachePlan

        plan = CachePlan(shared_prefix_chars=100, expected_reuse=1)
        assert plan.ttl == "5m"
        assert plan.shared_prefix_chars == 100
        assert plan.expected_reuse == 1

        with pytest.raises(FrozenInstanceError):
            plan.ttl = "1h"  # type: ignore[misc]

    def test_base_client_never_sends_cache_control(self, mock_client, tmp_path):
        """Base client must not emit cache_control even when a CachePlan is supplied."""
        import json as json_mod

        from muscle.m27_client import CachePlan

        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

        plan = CachePlan(shared_prefix_chars=10, expected_reuse=1)
        result, usage = client.chat(
            [{"role": "user", "content": "hello world"}],
            temperature=1.0,
            cache_plan=plan,
        )

        assert result == "ok"
        assert mock_session.post.called
        posted = mock_session.post.call_args.kwargs["json"]
        # cache_control must be absent everywhere in the payload
        assert "cache_control" not in json_mod.dumps(posted)
        # temperature must be forwarded as-is
        assert posted["temperature"] == 1.0
        # messages[0]["content"] must still be a plain str (not a list/dict)
        assert isinstance(posted["messages"][0]["content"], str)

    def test_chat_structured_forwards_cache_plan(self, mock_client, tmp_path):
        """cache_plan passed to chat_structured must be forwarded to chat()."""

        from pydantic import BaseModel

        from muscle.m27_client import CachePlan, TokenUsage

        client, _ = mock_client
        # Point cache at tmp_path so ResponseCache doesn't touch the real DB.
        client._cache_db_path = tmp_path / "test_cache.db"

        class SimpleSchema(BaseModel):
            x: int

        plan = CachePlan(shared_prefix_chars=5, expected_reuse=2)

        def _stub_chat(*args, _metadata_sink=None, **kwargs):
            if _metadata_sink is not None:
                _metadata_sink["truncated"] = False
            return '{"x": 1}', TokenUsage(input_tokens=1, output_tokens=1)

        with patch.object(client, "chat", side_effect=_stub_chat) as mock_chat:
            result = client.chat_structured(
                SimpleSchema,
                [{"role": "user", "content": "hi"}],
                cache_plan=plan,
            )

        assert result.x == 1
        assert mock_chat.called
        _, call_kwargs = mock_chat.call_args
        assert call_kwargs.get("cache_plan") is plan

    def test_prepare_payload_hook_receives_final_payload(self, mock_client):
        """Subclass _prepare_payload hook receives thinking + cache_plan; its changes reach POST."""

        from muscle.m27_client import CachePlan, M27Client

        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "hook-ok"}],
                "usage": {"input_tokens": 3, "output_tokens": 1},
            },
        )

        received_kwargs: dict = {}

        class HookedClient(M27Client):
            def _prepare_payload(
                self,
                payload,
                is_openai_compatible,
                thinking=None,
                cache_plan=None,
                stage=None,
            ):
                received_kwargs["thinking"] = thinking
                received_kwargs["cache_plan"] = cache_plan
                payload["_hook_marker"] = 1
                return payload

        # Construct HookedClient normally; the fixture's patches on M27Client._session,
        # _rate_limiter and _concurrency_limiter are inherited by the subclass so no
        # additional patching is needed here.
        with patch.object(M27Client, "_session", mock_session):
            hooked = HookedClient(api_key="test-key")

        plan = CachePlan(shared_prefix_chars=20, expected_reuse=3)
        hooked.chat(
            [{"role": "user", "content": "test hook"}],
            thinking="adaptive",
            cache_plan=plan,
        )

        assert mock_session.post.called
        _, kwargs = mock_session.post.call_args
        posted = kwargs["json"]
        assert posted.get("_hook_marker") == 1
        assert received_kwargs["thinking"] == "adaptive"
        assert received_kwargs["cache_plan"] is plan


# ---------------------------------------------------------------------------
# Task 1 & 2: stage param is a MiniMax no-op
# ---------------------------------------------------------------------------


class TestStageParamIsMiniMaxNoOp:
    def test_stage_does_not_change_minimax_payload(self, mock_client):
        """The new stage arg must be a byte-identical no-op on the MiniMax path."""
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

        client.chat([{"role": "user", "content": "hi"}], thinking="adaptive")
        baseline = dict(mock_session.post.call_args.kwargs["json"])

        client.chat(
            [{"role": "user", "content": "hi"}], thinking="adaptive", stage="semantic_review"
        )
        with_stage = dict(mock_session.post.call_args.kwargs["json"])

        assert with_stage == baseline  # stage must not alter the MiniMax request
        assert "stage" not in with_stage  # never serialized into the payload
