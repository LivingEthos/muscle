"""
Unit tests for m27_client.py
"""

from unittest.mock import patch

import pytest

from tools.muscle.m27_client import ConcurrencyLimiter, M27Client, RateLimiter, TokenUsage


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
