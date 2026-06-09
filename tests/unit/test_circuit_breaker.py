"""Tests for circuit breaker implementation."""

from __future__ import annotations

import asyncio

import pytest

from tools.muscle.exceptions import CircuitBreakerOpenError
from tools.muscle.llm.circuit_breaker import MemoryCircuitBreaker


async def test_circuit_breaker_closed_allows_calls():
    breaker = MemoryCircuitBreaker()
    result = await breaker.call(lambda: asyncio.sleep(0))
    assert result is None
    assert breaker.state == "closed"


async def test_circuit_breaker_opens_after_threshold():
    breaker = MemoryCircuitBreaker(failure_threshold=2)

    async def _fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    assert breaker.state == "closed"
    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    assert breaker.state == "open"

    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(_fail)


async def test_circuit_breaker_half_open_recovery():
    breaker = MemoryCircuitBreaker(failure_threshold=1, recovery_timeout=0.1)

    async def _fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    assert breaker.state == "open"

    await asyncio.sleep(0.15)
    # Should transition to half-open
    result = await breaker.call(lambda: asyncio.sleep(0))
    assert result is None
    assert breaker.state == "closed"


async def test_circuit_breaker_reset():
    breaker = MemoryCircuitBreaker(failure_threshold=1)

    async def _fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await breaker.call(_fail)
    assert breaker.state == "open"

    await breaker.reset()
    assert breaker.state == "closed"
    assert breaker._failures == 0


def test_circuit_breaker_get_state():
    breaker = MemoryCircuitBreaker(failure_threshold=3)
    state = breaker.get_state()
    assert state["state"] == "closed"
    assert state["failure_count"] == 0
    assert state["failure_threshold"] == 3


async def test_open_with_missing_failure_time_fails_safe():
    """Fix: M8. If state is open but the failure timestamp is missing, fail safe
    (stay open) rather than relying on an assert stripped under `python -O`."""
    breaker = MemoryCircuitBreaker(failure_threshold=1)
    breaker._state = "open"
    breaker._last_failure_time = None

    with pytest.raises(CircuitBreakerOpenError):
        await breaker.call(lambda: asyncio.sleep(0))
