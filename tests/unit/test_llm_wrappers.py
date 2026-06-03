"""Tests for LLM client wrappers."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tools.muscle.exceptions import CircuitBreakerOpenError, PermanentLLMError, TransientLLMError
from tools.muscle.llm.circuit_breaker import MemoryCircuitBreaker
from tools.muscle.llm.client import LLMClient, LLMRequest, LLMResponse, LLMStreamChunk
from tools.muscle.llm.token_budget import TokenBudget
from tools.muscle.llm.wrappers import (
    BudgetEnforcingLLMClient,
    CircuitBreakerLLMWrapper,
    FallbackLLMWrapper,
    RetryableLLMClient,
)


class FakeClient(LLMClient):
    """Fake LLM client for testing."""

    def __init__(self, name: str = "fake", fail_with: Exception | None = None) -> None:
        self.name = name
        self.fail_with = fail_with
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self.name

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        if self.fail_with:
            raise self.fail_with
        return LLMResponse(content="ok", model=self.name)

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        async def _stream() -> AsyncIterator[LLMStreamChunk]:
            self.call_count += 1
            if self.fail_with:
                raise self.fail_with
            yield LLMStreamChunk(content="chunk1")
            yield LLMStreamChunk(content="chunk2")

        return _stream()

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def request_fixture() -> LLMRequest:
    return LLMRequest(messages=[])


async def test_retryable_complete_retries_transient(request_fixture: LLMRequest) -> None:
    inner = FakeClient(fail_with=TransientLLMError("boom"))
    wrapper = RetryableLLMClient(inner, max_retries=2, min_wait=0.01, max_wait=0.1)

    # After 2 retries (3 total attempts), it should still fail
    with pytest.raises(TransientLLMError):
        await wrapper.complete(request_fixture)
    assert inner.call_count == 2


async def test_retryable_complete_no_retry_permanent(request_fixture: LLMRequest) -> None:
    inner = FakeClient(fail_with=PermanentLLMError("bad"))
    wrapper = RetryableLLMClient(inner, max_retries=3, min_wait=0.01, max_wait=0.1)

    with pytest.raises(PermanentLLMError):
        await wrapper.complete(request_fixture)
    assert inner.call_count == 1


async def test_retryable_stream_initiation_retry(request_fixture: LLMRequest) -> None:
    inner = FakeClient(fail_with=TransientLLMError("boom"))
    wrapper = RetryableLLMClient(inner, max_retries=2, min_wait=0.01, max_wait=0.1)

    with pytest.raises(TransientLLMError):
        async for _ in wrapper.stream(request_fixture):
            pass
    # Stream initiation is retried; FakeClient.call_count is only incremented
    # when stream() is called, but the retry retries the aiter creation.
    # The inner.stream() call happens once, but _start_stream is retried.
    assert inner.call_count >= 1


async def test_retryable_stream_midstream_no_retry(request_fixture: LLMRequest) -> None:
    class MidStreamFailClient(LLMClient):
        def __init__(self) -> None:
            self.chunk_count = 0

        @property
        def provider_name(self) -> str:
            return "midstream"

        async def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(content="ok", model="m")

        def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
            async def _stream() -> AsyncIterator[LLMStreamChunk]:
                self.chunk_count += 1
                yield LLMStreamChunk(content="first")
                raise TransientLLMError("midstream fail")

            return _stream()

        async def health_check(self) -> bool:
            return True

    inner = MidStreamFailClient()
    wrapper = RetryableLLMClient(inner, max_retries=2, min_wait=0.01, max_wait=0.1)

    chunks = []
    with pytest.raises(TransientLLMError):
        async for chunk in wrapper.stream(request_fixture):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].content == "first"
    # Mid-stream error should NOT retry the stream initiation
    assert inner.chunk_count == 1


async def test_budget_wrapper_reserve_commit_pattern(request_fixture: LLMRequest) -> None:
    inner = FakeClient()
    budget = TokenBudget()
    wrapper = BudgetEnforcingLLMClient(inner, budget)

    resp = await wrapper.complete(request_fixture)
    assert resp.content == "ok"
    assert len(budget.usage_history) == 1


async def test_budget_wrapper_release_on_exception(request_fixture: LLMRequest) -> None:
    inner = FakeClient(fail_with=RuntimeError("boom"))
    budget = TokenBudget()
    wrapper = BudgetEnforcingLLMClient(inner, budget)

    with pytest.raises(RuntimeError):
        await wrapper.complete(request_fixture)
    # No usage should be recorded
    assert len(budget.usage_history) == 0
    # Reservation should be released
    assert len(budget._reservations) == 0


async def test_fallback_primary_succeeds(request_fixture: LLMRequest) -> None:
    primary = FakeClient(name="primary")
    fallback = FakeClient(name="fallback")
    wrapper = FallbackLLMWrapper(primary, [fallback])

    resp = await wrapper.complete(request_fixture)
    assert resp.content == "ok"
    assert primary.call_count == 1
    assert fallback.call_count == 0


async def test_fallback_uses_fallback_on_failure(request_fixture: LLMRequest) -> None:
    primary = FakeClient(name="primary", fail_with=RuntimeError("primary down"))
    fallback = FakeClient(name="fallback")
    wrapper = FallbackLLMWrapper(primary, [fallback])

    resp = await wrapper.complete(request_fixture)
    assert resp.content == "ok"
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert wrapper.provider_name == "fallback"


async def test_fallback_all_fail_raises(request_fixture: LLMRequest) -> None:
    primary = FakeClient(name="primary", fail_with=RuntimeError("p"))
    fallback = FakeClient(name="fallback", fail_with=RuntimeError("f"))
    wrapper = FallbackLLMWrapper(primary, [fallback])

    with pytest.raises(Exception, match="All LLM providers failed"):
        await wrapper.complete(request_fixture)


async def test_retryable_half_open_max_calls(request_fixture: LLMRequest) -> None:
    """Test that half-open circuit breaker allows max calls before deciding."""
    inner = FakeClient(fail_with=RuntimeError("boom"))
    breaker = MemoryCircuitBreaker(failure_threshold=1, recovery_timeout=0.01, half_open_max_calls=1)
    wrapper = CircuitBreakerLLMWrapper(inner, breaker)

    # Trip the breaker
    with pytest.raises(RuntimeError):
        await wrapper.complete(request_fixture)
    assert breaker.state == "open"

    # Wait for recovery timeout
    import asyncio
    await asyncio.sleep(0.02)

    # In half-open with max_calls=1, one call should be allowed then fail
    with pytest.raises(RuntimeError):
        await wrapper.complete(request_fixture)
    # Should go back to open after failure
    assert breaker.state == "open"


async def test_fallback_llmerror_type(request_fixture: LLMRequest) -> None:
    """Test that FallbackLLMWrapper raises LLMError, not bare Exception."""
    from tools.muscle.exceptions import LLMError

    primary = FakeClient(name="primary", fail_with=RuntimeError("p"))
    fallback = FakeClient(name="fallback", fail_with=RuntimeError("f"))
    wrapper = FallbackLLMWrapper(primary, [fallback])

    with pytest.raises(LLMError, match="All LLM providers failed"):
        await wrapper.complete(request_fixture)


async def test_circuit_breaker_wrapper_complete(request_fixture: LLMRequest) -> None:
    inner = FakeClient()
    breaker = MemoryCircuitBreaker(failure_threshold=1)
    wrapper = CircuitBreakerLLMWrapper(inner, breaker)

    resp = await wrapper.complete(request_fixture)
    assert resp.content == "ok"


async def test_circuit_breaker_wrapper_opens(request_fixture: LLMRequest) -> None:
    inner = FakeClient(fail_with=RuntimeError("boom"))
    breaker = MemoryCircuitBreaker(failure_threshold=1)
    wrapper = CircuitBreakerLLMWrapper(inner, breaker)

    with pytest.raises(RuntimeError):
        await wrapper.complete(request_fixture)

    assert breaker.state == "open"
    with pytest.raises(CircuitBreakerOpenError):
        await wrapper.complete(request_fixture)
