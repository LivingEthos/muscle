"""Shared utilities for LLM adapter error handling.

Eliminates ~90 lines of duplication per adapter by centralizing
HTTP error classification and retryable vs permanent distinction.

Architecture Decision Record (ADR):
- classify_http_error() maps status codes to TransientLLMError or PermanentLLMError
- handle_llm_error() is the single entry point: returns (does not raise) the error
- Callers use: raise handle_llm_error(exc, ...) from exc
"""

from __future__ import annotations

import httpx

from muscle.exceptions import LLMError, PermanentLLMError, TransientLLMError


def classify_http_error(
    status_code: int,
    response_text: str,
    provider: str,
    model: str = "",
) -> LLMError:
    """Classify an HTTP error as transient or permanent.

    Returns the appropriate exception instance for the caller to raise.
    """
    if status_code == 429:
        return TransientLLMError(
            message=f"Rate limited: 429 — {response_text[:200]}",
            status_code=429,
            provider=provider,
            model=model,
        )
    if status_code >= 500:
        return TransientLLMError(
            message=f"Server error: {status_code} — {response_text[:200]}",
            status_code=status_code,
            provider=provider,
            model=model,
        )
    return PermanentLLMError(
        message=f"Client error: {status_code} — {response_text[:200]}. "
        f"Hint: Check your API key and provider configuration. "
        f"If using OpenRouter, verify your key at https://openrouter.ai/keys. "
        f"If using a direct provider (MiniMax/Kimi/ZAI), ensure the correct API key is set.",
        status_code=status_code,
        provider=provider,
        model=model,
    )


def handle_llm_error(
    exc: Exception,
    provider: str,
    model: str,
    context: str = "request",
) -> LLMError:
    """Convert an exception into the appropriate LLMError subclass.

    Returns (does not raise) the classified error. Callers should
    `raise handle_llm_error(exc, ...) from exc`.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_error(
            status_code=exc.response.status_code,
            response_text=exc.response.text,
            provider=provider,
            model=model,
        )
    if isinstance(exc, httpx.TimeoutException):
        return TransientLLMError(
            message=f"{provider} {context} timed out: {exc}",
            provider=provider,
            model=model,
        )
    return LLMError(f"{provider} {context} failed: {exc}")
