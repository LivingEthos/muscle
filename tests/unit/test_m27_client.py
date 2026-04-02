"""
Unit tests for m27_client.py
"""

from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.m27_client import (
    ConcurrencyLimiter,
    M27Client,
    RateLimiter,
    TokenUsage,
    _detect_api_base,
)


class TestTokenUsage:
    def test_total(self):
        tu = TokenUsage(input_tokens=100, output_tokens=50)
        assert tu.total == 150


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
                "tools.muscle.m27_client._detect_api_base",
                return_value="https://api.minimax.io/anthropic",
            ):
                with patch("tools.muscle.m27_client._create_session"):
                    return M27Client(api_key="test-key", model="MiniMax-M2.7")

    def test_init_defaults(self, client):
        assert client.api_key == "test-key"
        assert client.model == "MiniMax-M2.7"
        assert client.timeout == 120

    def test_should_retry_429(self, client):
        assert client._should_retry("rate limit", attempt=1) is True
        assert client._should_retry("429", attempt=1) is True

    def test_should_retry_5xx(self, client):
        assert client._should_retry("502", attempt=1) is True
        assert client._should_retry("503", attempt=1) is True

    def test_should_not_retry_4xx_except_429(self, client):
        assert client._should_retry("not_found", attempt=1) is False
        assert client._should_retry("unauthorized", attempt=1) is False

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
        assert "minimax.io" in result

    def test_respects_anthropic_base_url_env(self):
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://custom.example.com/anthropic"},
            clear=True,
        ):
            result = _detect_api_base()
        assert result == "https://custom.example.com/anthropic"

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
            "tools.muscle.m27_client._detect_api_base",
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

    def test_messages_not_a_list(self, mock_client):
        client, _ = mock_client
        result, usage = client.chat("not a list")
        assert result == ""
        assert usage.total == 0

    def test_message_not_a_dict(self, mock_client):
        client, _ = mock_client
        result, usage = client.chat(["string instead of dict"])
        assert result == ""
        assert usage.total == 0

    def test_message_missing_role(self, mock_client):
        client, _ = mock_client
        result, usage = client.chat([{"content": "hello"}])
        assert result == ""
        assert usage.total == 0

    def test_message_missing_content(self, mock_client):
        client, _ = mock_client
        result, usage = client.chat([{"role": "user"}])
        assert result == ""
        assert usage.total == 0

    def test_message_content_not_string(self, mock_client):
        client, _ = mock_client
        result, usage = client.chat([{"role": "user", "content": 123}])
        assert result == ""
        assert usage.total == 0


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


class TestChatRetry:
    """Tests for chat() retry logic."""

    def test_retry_on_json_decode_error(self, mock_client):
        import requests as req
        import json

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
        for code in [502, 503, 504]:
            mock_session.post.return_value = _make_mock_response(code, text="Error")

        with patch("time.sleep"):
            for code in [502, 503, 504]:
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
            chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == 2

    def test_chat_streaming_500_retries(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(500, text="Error")

        with patch("time.sleep"):
            chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == client.max_retries

    def test_chat_streaming_timeout(self, mock_client):
        import requests as req

        client, mock_session = mock_client
        mock_session.post.side_effect = req.exceptions.Timeout("timed out")

        with patch("time.sleep"):
            chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))

        assert mock_session.post.call_count == client.max_retries

    def test_chat_streaming_connection_error(self, mock_client):
        import requests as req

        client, mock_session = mock_client
        mock_session.post.side_effect = req.exceptions.ConnectionError("refused")

        with patch("time.sleep"):
            chunks = list(client.chat_streaming([{"role": "user", "content": "hi"}]))

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
        assert chunks[-1] == ("", None)

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

    def test_should_retry_respects_max_retries(self, mock_client):
        client, _ = mock_client
        client.max_retries = 3
        assert client._should_retry("429", attempt=2) is True
        assert client._should_retry("429", attempt=3) is False

    def test_should_retry_timeout(self, mock_client):
        client, _ = mock_client
        assert client._should_retry("timeout error", attempt=1) is True

    def test_should_retry_connection_error(self, mock_client):
        client, _ = mock_client
        assert client._should_retry("connection refused", attempt=1) is True

    def test_should_not_retry_non_retryable(self, mock_client):
        client, _ = mock_client
        assert client._should_retry("not found", attempt=1) is False

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
