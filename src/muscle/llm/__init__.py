"""LLM Provider Abstraction Layer for MUSCLE.

Public API surface for all LLM interactions.
"""

from __future__ import annotations

from .adapters import (
    AnthropicClient,
    KimiClient,
    MiniMaxClient,
    OpenAIClient,
    OpenRouterClient,
    ZAIClient,
    create_client,
)
from .circuit_breaker import CircuitBreaker, MemoryCircuitBreaker
from .client import (
    LLMClient,
    LLMClientWrapper,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenTracker,
)
from .token_budget import BudgetConfig, BudgetPeriod, TokenBudget, TokenUsage
from .wrappers import (
    BudgetEnforcingLLMClient,
    CircuitBreakerLLMWrapper,
    FallbackLLMWrapper,
    RetryableLLMClient,
)

__all__ = [
    "LLMClient",
    "LLMClientWrapper",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamChunk",
    "TokenTracker",
    "BudgetConfig",
    "BudgetPeriod",
    "TokenBudget",
    "TokenUsage",
    "CircuitBreaker",
    "MemoryCircuitBreaker",
    "RetryableLLMClient",
    "CircuitBreakerLLMWrapper",
    "BudgetEnforcingLLMClient",
    "FallbackLLMWrapper",
    "MiniMaxClient",
    "OpenRouterClient",
    "OpenAIClient",
    "AnthropicClient",
    "KimiClient",
    "ZAIClient",
    "create_client",
]
