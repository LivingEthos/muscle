"""Tests for LLM client interface and data types."""

from __future__ import annotations

import pytest

from tools.muscle.llm.client import (
    LLMClient,
    LLMClientWrapper,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenTracker,
)


class FakeClient(LLMClient):
    """Fake LLM client for testing."""

    @property
    def provider_name(self) -> str:
        return "fake"

    async def complete(self, request: LLMRequest):
        return LLMResponse(content="hi", model="fake-model")

    def stream(self, request: LLMRequest):
        return iter([])

    async def health_check(self):
        return True


class FakeWrapper(LLMClientWrapper):
    pass


def test_llm_request_frozen():
    req = LLMRequest(messages=[LLMMessage(role="user", content="hello")])
    with pytest.raises(AttributeError):
        req.temperature = 0.5


def test_llm_response_fields():
    resp = LLMResponse(
        content="hello",
        model="gpt-4o",
        usage_tokens=10,
        prompt_tokens=5,
        completion_tokens=5,
        finish_reason="stop",
    )
    assert resp.content == "hello"
    assert resp.model == "gpt-4o"
    assert resp.usage_tokens == 10
    assert resp.prompt_tokens == 5
    assert resp.completion_tokens == 5
    assert resp.finish_reason == "stop"


def test_token_tracker_record():
    tracker = TokenTracker()
    resp = LLMResponse(
        content="hi", model="m", usage_tokens=10, prompt_tokens=4, completion_tokens=6
    )
    tracker.record(resp)
    assert tracker.call_count == 1
    assert tracker.total_tokens == 10
    assert tracker.total_prompt_tokens == 4
    assert tracker.total_completion_tokens == 6


def test_token_tracker_summary():
    tracker = TokenTracker()
    resp = LLMResponse(
        content="hi", model="m", usage_tokens=10, prompt_tokens=4, completion_tokens=6
    )
    tracker.record(resp)
    summary = tracker.summary()
    assert "10 total" in summary
    assert "4 prompt" in summary
    assert "6 completion" in summary
    assert "1 calls" in summary


def test_wrapper_delegates_properties():
    inner = FakeClient()
    wrapper = FakeWrapper(inner)
    assert wrapper.provider_name == "fake"
    assert wrapper.max_rpm == 60
    assert wrapper.context_window == 128_000


def test_get_context_window_exact_match():
    # FakeClient provider_name is "fake", so no exact match in MODEL_CONTEXT_WINDOWS
    # Use a provider that exists in the registry
    from tools.muscle.llm.adapters.openai import OpenAIClient

    oai = OpenAIClient(api_key="test")
    assert oai.get_context_window("gpt-4o") == 128_000


def test_get_context_window_segment_match():
    from tools.muscle.llm.adapters.openrouter import OpenRouterClient

    or_client = OpenRouterClient(api_key="test")
    assert or_client.get_context_window("openai/gpt-4o-mini") == 128_000
    assert or_client.get_context_window("anthropic/claude-3-5-sonnet") == 200_000


def test_get_context_window_fallback():
    from tools.muscle.llm.adapters.openai import OpenAIClient

    oai = OpenAIClient(api_key="test")
    assert oai.get_context_window("unknown-model-xyz") == 128_000
    assert oai.get_context_window(None) == 128_000


def test_llm_stream_chunk():
    chunk = LLMStreamChunk(content="hello", finish_reason="stop")
    assert chunk.content == "hello"
    assert chunk.finish_reason == "stop"

    chunk2 = LLMStreamChunk(content="")
    assert chunk2.finish_reason is None
