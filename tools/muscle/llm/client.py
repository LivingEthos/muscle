"""LLM client interface and data types for MUSCLE.

Architecture Decision Record (ADR):
- ABC with async methods aligns with v2's clean architecture
- MODEL_CONTEXT_WINDOWS uses segment-based matching (split on "/" and "-")
  to avoid false positives from naive substring matching
- LLMClientWrapper provides transparent middleware composition
- TokenTracker is mutable (not frozen) by design — accumulates across calls
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

# Known context window sizes by (provider, model_pattern).
# Keys matched against model segments split on "/" and "-".
# Sorted by specificity: longer patterns checked first.
MODEL_CONTEXT_WINDOWS: dict[tuple[str, str], int] = {
    # OpenRouter
    ("openrouter", "gpt-4o-mini"): 128_000,
    ("openrouter", "gpt-4o"): 128_000,
    ("openrouter", "gpt-4-turbo"): 128_000,
    ("openrouter", "claude-3.5-sonnet"): 200_000,
    ("openrouter", "claude-3-5-sonnet"): 200_000,
    ("openrouter", "claude-3-opus"): 200_000,
    ("openrouter", "claude-3-haiku"): 200_000,
    ("openrouter", "gemini-pro"): 32_000,
    ("openrouter", "gemini-1.5-pro"): 2_000_000,
    ("openrouter", "gemini-1.5-flash"): 1_000_000,
    # OpenAI
    ("openai", "gpt-4o-mini"): 128_000,
    ("openai", "gpt-4o"): 128_000,
    ("openai", "gpt-4-turbo"): 128_000,
    # Anthropic
    ("anthropic", "claude-3.5-sonnet"): 200_000,
    ("anthropic", "claude-3-5-sonnet"): 200_000,
    ("anthropic", "claude-3-opus"): 200_000,
    ("anthropic", "claude-3-haiku"): 200_000,
    ("anthropic", "claude-sonnet-4"): 200_000,
    # MiniMax
    ("minimax", "m3"): 1_000_000,
    ("minimax", "m2.7"): 204_800,
    # Kimi
    ("kimi", "k2.6"): 256_000,
    # ZAI/GLM
    ("zai", "glm-5.1"): 128_000,
}


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMRequest:
    messages: Sequence[LLMMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    model: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage_tokens: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class TokenTracker:
    """Tracks token usage across all LLM calls."""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

    def record(self, response: LLMResponse) -> None:
        """Record token usage from a response."""
        self.call_count += 1
        if response.prompt_tokens is not None:
            self.total_prompt_tokens += response.prompt_tokens
        if response.completion_tokens is not None:
            self.total_completion_tokens += response.completion_tokens
        if response.usage_tokens is not None:
            self.total_tokens += response.usage_tokens

    def summary(self) -> str:
        """Return a formatted summary of token usage."""
        return (
            f"Token Usage: {self.total_tokens:,} total "
            f"({self.total_prompt_tokens:,} prompt + {self.total_completion_tokens:,} completion) "
            f"across {self.call_count} calls"
        )


@dataclass(frozen=True)
class LLMStreamChunk:
    content: str
    finish_reason: str | None = None


class LLMClient(ABC):
    """Abstract LLM client. All providers implement this.

    Supports async context manager usage:
        async with client:
            response = await client.complete(request)
    """

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Non-streaming completion."""
        ...

    @abstractmethod
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Streaming completion. Yields chunks."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Quick health check for circuit breaker."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    def max_rpm(self) -> int:
        """Maximum requests per minute. Override in subclasses."""
        return 60

    @property
    def context_window(self) -> int:
        """Context window for the default model."""
        return 128_000

    def get_context_window(self, model: str | None = None) -> int:
        """Get context window for a specific model with segment-based matching.

        Splits model name on "/" and "-" to avoid false substring matches.
        Longer patterns are checked first for most-specific match.
        Falls back to the class-level context_window property.
        """
        if model:
            model_lower = model.lower()
            model_segments: set[str] = set()
            for part in model_lower.split("/"):
                for segment in part.split("-"):
                    if segment:
                        model_segments.add(segment)
                model_segments.add(part)

            best_match_len = 0
            best_window = 0
            for (provider, pattern), window in MODEL_CONTEXT_WINDOWS.items():
                if provider != self.provider_name:
                    continue
                pattern_lower = pattern.lower()
                # Only match against segments to avoid substring false positives
                if pattern_lower in model_segments and len(pattern_lower) > best_match_len:
                    best_match_len = len(pattern_lower)
                    best_window = window
            if best_match_len > 0:
                return best_window
        return self.context_window

    async def close(self) -> None:
        """Clean up resources. Override if adapter holds connections."""
        return None

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class LLMClientWrapper(LLMClient):
    """Base class for LLM client wrappers.

    Forwards all property access and non-overridden methods to the inner
    client. Subclasses MUST override complete() and stream() explicitly —
    do NOT rely on default delegation for stream(), or middleware will be
    silently bypassed.
    """

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    @property
    def max_rpm(self) -> int:
        return self._inner.max_rpm

    @property
    def context_window(self) -> int:
        return self._inner.context_window

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await self._inner.complete(request)

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        return self._inner.stream(request)

    async def health_check(self) -> bool:
        return await self._inner.health_check()

    async def close(self) -> None:
        await self._inner.close()
