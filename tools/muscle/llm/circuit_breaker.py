"""Circuit breaker base class and in-memory implementation.

Architecture Decision Record (ADR):
- CircuitBreaker is an ABC so we can add Redis-backed or distributed
  implementations in the future without changing wrapper code.
- MemoryCircuitBreaker uses asyncio.Lock for thread-safety.
- State transitions: closed -> open (on threshold failures) -> half-open
  (after recovery_timeout) -> closed (on success) or open (on failure).
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TypeVar

from tools.muscle.exceptions import CircuitBreakerOpenError

T = TypeVar("T")


class CircuitBreaker(ABC):
    """Circuit breaker interface."""

    @abstractmethod
    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Execute fn if breaker is closed, otherwise fail fast."""

    @property
    @abstractmethod
    def state(self) -> str:
        """Return 'closed', 'open', or 'half-open'."""


class MemoryCircuitBreaker(CircuitBreaker):
    """Simple in-memory circuit breaker."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 2,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._failures = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._state = "closed"
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        async with self._lock:
            self._failures = 0
            self._last_failure_time = None
            self._half_open_calls = 0
            self._state = "closed"

    def get_state(self) -> dict[str, object]:
        """Return current state and metrics."""
        return {
            "state": self._state,
            "failure_count": self._failures,
            "failure_threshold": self.failure_threshold,
            "last_failure_time": self._last_failure_time,
        }

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            if self._state == "open":
                assert self._last_failure_time is not None
                if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                    self._state = "half-open"
                    self._half_open_calls = 0
                else:
                    raise CircuitBreakerOpenError("Circuit breaker is open")
            if self._state == "half-open" and self._half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerOpenError("Circuit breaker is half-open and max calls reached")
            if self._state == "half-open":
                self._half_open_calls += 1

        try:
            result = await fn()
        except Exception as exc:
            async with self._lock:
                self._failures += 1
                self._last_failure_time = time.monotonic()
                if self._state == "half-open" or self._failures >= self.failure_threshold:
                    self._state = "open"
            raise exc

        async with self._lock:
            self._failures = 0
            self._last_failure_time = None
            self._state = "closed"
            self._half_open_calls = 0
        return result
