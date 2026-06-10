"""LLM client wrappers: retry, circuit breaker, budget, fallback.

Architecture Decision Record (ADR):
- All wrappers MUST explicitly override stream(). Relying on LLMClientWrapper's
  default stream() delegation silently bypasses middleware for streaming calls.
- RetryableLLMClient: retries only stream initiation, not mid-stream errors.
- BudgetEnforcingLLMClient: reserve/commit pattern with asyncio.Lock.
  Lock is NOT held during the LLM call, enabling parallel requests.
- CircuitBreakerLLMWrapper: uses sentinel lambdas for stream success/failure
  recording since stream() returns an AsyncIterator, not a coroutine.
- FallbackLLMWrapper: tries primary then each fallback in order.
  Preserves the successful client as _current for property access.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from muscle.exceptions import CircuitBreakerOpenError, LLMError, TransientLLMError
from muscle.llm.circuit_breaker import CircuitBreaker
from muscle.llm.client import (
    LLMClient,
    LLMClientWrapper,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
)
from muscle.llm.token_budget import TokenBudget

logger = logging.getLogger(__name__)


def _is_transient(exc: BaseException) -> bool:
    """Return True if the exception is retryable (transient)."""
    return isinstance(exc, TransientLLMError)


class RetryableLLMClient(LLMClientWrapper):
    """Wraps an LLMClient with retry logic for transient errors.

    For complete(): retries with exponential backoff.
    For stream(): retries stream initiation only; once the first
    chunk arrives, mid-stream errors are not retried.
    """

    def __init__(
        self,
        inner: LLMClient,
        max_retries: int = 3,
        min_wait: float = 1.0,
        max_wait: float = 60.0,
    ) -> None:
        super().__init__(inner)
        self._max_retries = max_retries
        self._min_wait = min_wait
        self._max_wait = max_wait

        self._retry = retry(
            retry=retry_if_exception(_is_transient),
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        @self._retry
        async def _call() -> LLMResponse:
            return await self._inner.complete(request)

        return await _call()

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        async def _retryable_stream() -> AsyncIterator[LLMStreamChunk]:
            first_chunk_received = False

            @self._retry
            async def _start_stream() -> AsyncIterator[LLMStreamChunk]:
                return self._inner.stream(request).__aiter__()

            stream_iter = await _start_stream()

            try:
                async for chunk in stream_iter:
                    first_chunk_received = True
                    yield chunk
            except TransientLLMError:
                if not first_chunk_received:
                    raise
                raise
            except Exception:
                raise

        return _retryable_stream()


class CircuitBreakerLLMWrapper(LLMClientWrapper):
    """Wraps an LLMClient with circuit breaker protection.

    For complete(): uses breaker.call() which handles state transitions.
    For stream(): checks state before streaming, then records
    success/failure after the stream completes or errors.
    """

    def __init__(self, inner: LLMClient, breaker: CircuitBreaker) -> None:
        super().__init__(inner)
        self._breaker = breaker

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self._breaker.call(lambda: self._inner.complete(request))

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        async def _guarded_stream() -> AsyncIterator[LLMStreamChunk]:
            if self._breaker.state == "open":
                raise CircuitBreakerOpenError("Circuit breaker is open")

            try:
                async for chunk in self._inner.stream(request):
                    yield chunk
            except Exception:

                async def _fail() -> None:
                    raise

                try:
                    await self._breaker.call(_fail)
                except CircuitBreakerOpenError:
                    pass
                raise
            else:

                async def _succeed() -> bool:
                    return True

                await self._breaker.call(_succeed)

        return _guarded_stream()


class BudgetEnforcingLLMClient(LLMClientWrapper):
    """Wraps an LLMClient to enforce token budget limits.

    Uses reserve/commit pattern: the lock is held only during budget
    check+reserve and commit/release, NOT during the actual LLM call.
    This allows concurrent calls to proceed in parallel.
    """

    def __init__(
        self,
        inner: LLMClient,
        budget: TokenBudget,
    ) -> None:
        super().__init__(inner)
        self._budget = budget
        self._lock = asyncio.Lock()

    def _estimate_tokens(self, request: LLMRequest) -> int:
        """Rough token estimate: ~4 chars per token."""
        total_chars = sum(len(m.content) for m in request.messages)
        return max(1, total_chars // 4)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        estimated = self._estimate_tokens(request)

        async with self._lock:
            rid = self._budget.reserve_tokens(estimated)

        try:
            response = await self._inner.complete(request)
        except Exception:
            async with self._lock:
                self._budget.release_reservation(rid)
            raise

        async with self._lock:
            prompt_tokens = response.prompt_tokens or 0
            completion_tokens = response.completion_tokens or 0
            self._budget.commit_reservation(
                rid=rid,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                provider=self.provider_name,
                model=response.model,
                operation="complete",
            )

        return response

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        async def _guarded_stream() -> AsyncIterator[LLMStreamChunk]:
            estimated = self._estimate_tokens(request)
            model = request.model or ""

            async with self._lock:
                rid = self._budget.reserve_tokens(estimated)

            # `committed` guards the finally block so the reservation is always
            # resolved exactly once, even if the consumer breaks early (GeneratorExit)
            # or the inner stream raises mid-flight. Completion tokens are estimated
            # from accumulated content length (~4 chars/token), not chunk count, which
            # has no relationship to token volume.
            content_chars = 0
            committed = False
            try:
                async for chunk in self._inner.stream(request):
                    content_chars += len(chunk.content)
                    yield chunk
                async with self._lock:
                    self._budget.commit_reservation(
                        rid=rid,
                        prompt_tokens=estimated,
                        completion_tokens=max(1, content_chars // 4),
                        provider=self.provider_name,
                        model=model,
                        operation="stream",
                    )
                committed = True
            finally:
                if not committed:
                    async with self._lock:
                        self._budget.release_reservation(rid)

        return _guarded_stream()


class FallbackLLMWrapper(LLMClient):
    """Wraps a primary LLM client with fallback providers.

    If the primary provider fails, automatically tries fallback providers
    in order until one succeeds or all fail.
    """

    def __init__(self, primary: LLMClient, fallbacks: list[LLMClient]) -> None:
        self._primary = primary
        self._fallbacks = fallbacks
        self._current = primary

    @property
    def provider_name(self) -> str:
        return self._current.provider_name

    @property
    def max_rpm(self) -> int:
        return self._current.max_rpm

    @property
    def context_window(self) -> int:
        return self._current.context_window

    async def complete(self, request: LLMRequest) -> LLMResponse:
        errors: list[str] = []

        for client in [self._primary] + self._fallbacks:
            self._current = client
            try:
                return await client.complete(request)
            except Exception as exc:
                errors.append(f"{client.provider_name}: {exc}")
                continue

        raise LLMError(f"All LLM providers failed. Errors: {'; '.join(errors)}")

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        async def _stream_with_fallback() -> AsyncIterator[LLMStreamChunk]:
            errors: list[str] = []

            for client in [self._primary] + self._fallbacks:
                self._current = client
                try:
                    async for chunk in client.stream(request):
                        yield chunk
                    return
                except Exception as exc:
                    errors.append(f"{client.provider_name}: {exc}")
                    continue

            raise LLMError(f"All LLM providers failed. Errors: {'; '.join(errors)}")

        return _stream_with_fallback()

    async def health_check(self) -> bool:
        for client in [self._primary] + self._fallbacks:
            try:
                if await client.health_check():
                    return True
            except Exception:
                continue
        return False

    async def close(self) -> None:
        for client in [self._primary] + self._fallbacks:
            await client.close()
