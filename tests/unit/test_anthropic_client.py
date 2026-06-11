"""Unit tests for anthropic_client.py (the anthropic-api provider, Opus-only)."""

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from muscle.anthropic_client import (
    ANTHROPIC_API_BASE,
    ANTHROPIC_VERSION,
    AnthropicApiClient,
    _detect_anthropic_api_base,
)
from muscle.m27_client import CachePlan, M27Client

TEST_KEY = "sk-ant-test-key"


def _make_mock_response(status_code: int, json_data: dict | None = None):
    import requests

    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.text = ""
    response.headers = {}
    if json_data is not None:
        response.json = MagicMock(return_value=json_data)
    return response


def _default_response_payload() -> dict:
    return {
        "content": [{"type": "text", "text": "Hello world"}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def _make_mock_session():
    import requests

    mock_session = MagicMock(spec=requests.Session)
    mock_session.post.return_value = _make_mock_response(
        200, json_data=_default_response_payload()
    )
    return mock_session


@contextmanager
def _patched_client(mock_session, env: dict | None = None, **client_kwargs):
    """Construct an AnthropicApiClient with mocked session/limiters and clean env."""
    client_kwargs.setdefault("api_key", TEST_KEY)
    with patch.dict("os.environ", env or {}, clear=True):
        with patch.object(M27Client, "_session", mock_session):
            with patch.object(M27Client, "_rate_limiter"):
                with patch.object(M27Client, "_concurrency_limiter"):
                    yield AnthropicApiClient(**client_kwargs)


@pytest.fixture
def mock_client():
    mock_session = _make_mock_session()
    with _patched_client(mock_session) as client:
        yield client, mock_session


def _posted_payload(mock_session) -> dict:
    call = mock_session.post.call_args
    return call.kwargs.get("json") or call[1]["json"]


def _posted_headers(mock_session) -> dict:
    call = mock_session.post.call_args
    return call.kwargs.get("headers") or call[1]["headers"]


class _TrivialSchema(BaseModel):
    ok: bool


class TestSamplingParamStrip:
    def test_strips_sampling_params(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], temperature=0.7)
        payload = _posted_payload(mock_session)
        assert "temperature" not in payload
        assert "top_p" not in payload
        assert "top_k" not in payload

    def test_chat_structured_internal_temperature_is_stripped(self, tmp_path):
        mock_session = _make_mock_session()
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
        with _patched_client(mock_session, cache_db_path=tmp_path / "cache.db") as client:
            result = client.chat_structured(
                _TrivialSchema, [{"role": "user", "content": "hi"}]
            )
        assert result.ok is True
        # chat_structured passes temperature=0.1 internally — must still be stripped.
        payload = _posted_payload(mock_session)
        assert "temperature" not in payload
        assert "top_p" not in payload
        assert "top_k" not in payload


class TestThinkingEffortMapping:
    def test_thinking_adaptive_maps_to_adaptive_plus_high_effort(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking="adaptive")
        payload = _posted_payload(mock_session)
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "high"}

    def test_thinking_disabled_omits_thinking_and_uses_medium_effort(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking="disabled")
        payload = _posted_payload(mock_session)
        assert "thinking" not in payload
        assert payload["output_config"] == {"effort": "medium"}

    def test_thinking_none_defaults_to_medium_effort(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking=None)
        payload = _posted_payload(mock_session)
        assert "thinking" not in payload
        assert payload["output_config"] == {"effort": "medium"}


class TestModelGuard:
    def test_model_is_opus_only(self, mock_client):
        client, _ = mock_client
        assert client.model == "claude-opus-4-8"

    def test_non_opus_model_rejected(self):
        with pytest.raises(ValueError, match="Opus-only"):
            AnthropicApiClient(model="claude-sonnet-4-6", api_key="sk-ant-x")


class TestKeyGuard:
    def test_requires_real_anthropic_key(self):
        # JWT-looking key — likely the MiniMax credential aliased as
        # ANTHROPIC_API_KEY in this repo. Must refuse to send it to Anthropic.
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="MiniMax"):
                AnthropicApiClient(api_key="eyJhbGciOi...")

    def test_nonstandard_key_escape_hatch(self):
        mock_session = _make_mock_session()
        with _patched_client(
            mock_session,
            env={"MUSCLE_ALLOW_NONSTANDARD_ANTHROPIC_KEY": "1"},
            api_key="eyJhbGciOi...",
        ) as client:
            assert client.api_key == "eyJhbGciOi..."

    def test_missing_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                AnthropicApiClient()


class TestHeaders:
    def test_headers(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}])
        headers = _posted_headers(mock_session)
        assert headers["x-api-key"] == TEST_KEY
        assert headers["anthropic-version"] == ANTHROPIC_VERSION
        assert headers["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in headers

    def test_posts_to_v1_messages_on_anthropic_base(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}])
        url = mock_session.post.call_args[0][0]
        assert url == f"{ANTHROPIC_API_BASE}/v1/messages"


class TestCachePlan:
    def test_cache_plan_inserts_breakpoint(self, mock_client):
        client, mock_session = mock_client
        client.chat(
            [{"role": "user", "content": "PREFIXSUFFIX"}],
            cache_plan=CachePlan(shared_prefix_chars=6, expected_reuse=1),
        )
        payload = _posted_payload(mock_session)
        assert payload["messages"][0]["content"] == [
            {"type": "text", "text": "PREFIX", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "SUFFIX"},
        ]

    def test_cache_plan_zero_reuse_no_breakpoint(self, mock_client):
        client, mock_session = mock_client
        client.chat(
            [{"role": "user", "content": "PREFIXSUFFIX"}],
            cache_plan=CachePlan(shared_prefix_chars=6, expected_reuse=0),
        )
        payload = _posted_payload(mock_session)
        # Write-amortization rule: no expected reuse -> not worth a cache write.
        assert payload["messages"][0]["content"] == "PREFIXSUFFIX"

    def test_cache_plan_1h_ttl(self, mock_client):
        client, mock_session = mock_client
        client.chat(
            [{"role": "user", "content": "PREFIXSUFFIX"}],
            cache_plan=CachePlan(shared_prefix_chars=6, expected_reuse=3, ttl="1h"),
        )
        payload = _posted_payload(mock_session)
        first_block = payload["messages"][0]["content"][0]
        assert first_block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_cache_plan_prefix_covers_whole_message(self, mock_client):
        client, mock_session = mock_client
        client.chat(
            [{"role": "user", "content": "SHORT"}],
            cache_plan=CachePlan(shared_prefix_chars=999, expected_reuse=1),
        )
        payload = _posted_payload(mock_session)
        assert payload["messages"][0]["content"] == [
            {"type": "text", "text": "SHORT", "cache_control": {"type": "ephemeral"}},
        ]


class TestUsageParsing:
    def test_usage_parses_cache_creation_and_read(self, mock_client):
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 90,
                    "cache_creation_input_tokens": 40,
                    "output_tokens": 5,
                },
            },
        )
        _, usage = client.chat([{"role": "user", "content": "hi"}])
        # Full prompt = fresh + cache_read + cache_creation.
        assert usage.input_tokens == 140
        assert usage.cached_input_tokens == 90
        assert usage.cache_creation_input_tokens == 40
        assert usage.output_tokens == 5

    def test_usage_cache_creation_only_first_write(self, mock_client):
        """cache_creation=40, cache_read=0 (first cache write): input folded correctly."""
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 40,
                    "output_tokens": 5,
                },
            },
        )
        _, usage = client.chat([{"role": "user", "content": "hi"}])
        # input_tokens = fresh(10) + cache_creation(40) = 50; no cache read
        assert usage.input_tokens == 50
        assert usage.cached_input_tokens == 0
        assert usage.cache_creation_input_tokens == 40
        assert usage.output_tokens == 5

    def test_usage_cache_read_only_pure_hit(self, mock_client):
        """cache_read=90, cache_creation=0 (pure cache hit): input folded correctly."""
        client, mock_session = mock_client
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "Hello"}],
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 90,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": 5,
                },
            },
        )
        _, usage = client.chat([{"role": "user", "content": "hi"}])
        # input_tokens = fresh(10) + cache_read(90) = 100; cached = 90
        assert usage.input_tokens == 100
        assert usage.cached_input_tokens == 90
        assert usage.cache_creation_input_tokens == 0
        assert usage.output_tokens == 5

    def test_prompt_size_estimate_uses_pre_hook_content(self, mock_client):
        """Regression: prompt-size estimate must be computed BEFORE _prepare_payload.

        When a CachePlan is active, AnthropicApiClient._insert_cache_breakpoint
        converts the first message's plain-string content into a list of text
        blocks (cache_control dicts).  If the estimate ran AFTER that mutation,
        str(list_of_dicts) would repr-inflate the char count and produce a
        significantly larger estimated_input_tokens than the original text
        would justify.

        Setup: zero-usage response forces the fallback estimate path
        (input_tokens == 0 AND output_tokens == 0 with non-empty text).
        """
        client, mock_session = mock_client
        content = "PREFIXSUFFIX"
        system = "SYS"
        # Zero-usage response: forces the fallback estimation path.
        mock_session.post.return_value = _make_mock_response(
            200,
            json_data={
                "content": [{"type": "text", "text": "response text"}],
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        )
        _, usage = client.chat(
            [{"role": "user", "content": content}],
            system=system,
            cache_plan=CachePlan(shared_prefix_chars=6, expected_reuse=1),
        )
        # Correct estimate: based on original string chars only (before hook).
        # effective_system = system[:2000] = "SYS" (len 3)
        # prompt_chars = len("PREFIXSUFFIX") + len("SYS") = 12 + 3 = 15
        # estimated_input_tokens = max(1, 15 // 4) = 3
        expected = max(1, (len(content) + len(system)) // 4)
        assert usage.input_tokens == expected, (
            f"Expected estimate based on original text ({expected}), "
            f"got {usage.input_tokens} — likely inflated by repr() of cache blocks"
        )


class TestDetectAnthropicApiBase:
    def test_guard_honors_anthropic_host(self):
        with patch.dict(
            "os.environ", {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}, clear=True
        ):
            assert _detect_anthropic_api_base() == "https://api.anthropic.com"

    def test_guard_rejects_non_anthropic_host(self, caplog):
        # "anthropic.com" only in the path — hostname is evil.example.com.
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_BASE_URL": "https://evil.example.com/anthropic.com"},
            clear=True,
        ):
            with caplog.at_level(logging.WARNING, logger="muscle.anthropic_client"):
                result = _detect_anthropic_api_base()
        assert result == ANTHROPIC_API_BASE
        assert any("Ignoring ANTHROPIC_BASE_URL" in rec.message for rec in caplog.records)

    def test_guard_escape_hatch(self):
        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_BASE_URL": "https://my-gateway.example.com",
                "MUSCLE_ALLOW_CUSTOM_BASE_URL": "1",
            },
            clear=True,
        ):
            assert _detect_anthropic_api_base() == "https://my-gateway.example.com"

    def test_default_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _detect_anthropic_api_base() == ANTHROPIC_API_BASE
