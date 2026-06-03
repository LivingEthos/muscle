"""MUSCLE exception hierarchy.

Centralizes all custom exceptions to avoid scattered definitions.
"""

from __future__ import annotations


class MuscleError(Exception):
    """Base exception for MUSCLE."""

    def __init__(self, message: str = "", exit_code: int = 1) -> None:
        self.message = message
        self.exit_code = exit_code
        super().__init__(message)


class LLMError(MuscleError):
    """Raised when LLM communication fails."""

    pass


class TransientLLMError(LLMError):
    """Retryable LLM failures (429, 5xx, timeouts)."""

    def __init__(
        self,
        message: str = "",
        status_code: int | None = None,
        retry_after: float | None = None,
        provider: str = "",
        model: str = "",
    ) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        self.provider = provider
        self.model = model
        super().__init__(message, exit_code=2)


class PermanentLLMError(LLMError):
    """Non-retryable LLM failures (400, 401, 403)."""

    def __init__(
        self,
        message: str = "",
        status_code: int | None = None,
        provider: str = "",
        model: str = "",
    ) -> None:
        self.status_code = status_code
        self.provider = provider
        self.model = model
        super().__init__(message, exit_code=3)


class CircuitBreakerOpenError(LLMError):
    """Raised when the circuit breaker is open."""

    pass


class BudgetExceededError(MuscleError):
    """Raised when token budget is exceeded."""

    pass


class ConfigError(MuscleError):
    """Raised when configuration is invalid."""

    pass
