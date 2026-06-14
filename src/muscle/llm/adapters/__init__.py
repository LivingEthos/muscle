"""LLM adapter factory and exports."""

from __future__ import annotations

from muscle.llm.client import LLMClient

from .anthropic import AnthropicClient
from .kimi import KimiClient
from .minimax import MiniMaxClient
from .openai import OpenAIClient
from .openrouter import OpenRouterClient
from .zai import ZAIClient

__all__ = [
    "AnthropicClient",
    "KimiClient",
    "MiniMaxClient",
    "OpenAIClient",
    "OpenRouterClient",
    "ZAIClient",
    "create_client",
]

# Provider name -> adapter class mapping
_ADAPTER_REGISTRY: dict[str, type[LLMClient]] = {
    "minimax": MiniMaxClient,
    "openrouter": OpenRouterClient,
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "kimi": KimiClient,
    "zai": ZAIClient,
}


def create_client(
    provider: str,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: object,
) -> LLMClient:
    """Create an LLM client by provider name.

    Args:
        provider: Provider name (minimax, openrouter, openai, anthropic, kimi, zai).
        api_key: API key. If None, reads from environment variable.
        base_url: Override base URL for the provider.
        **kwargs: Additional arguments passed to the adapter constructor.

    Returns:
        Configured LLMClient instance.

    Raises:
        ConfigError: If provider is not recognized.
    """
    from muscle.exceptions import ConfigError

    provider_lower = provider.lower()
    if provider_lower not in _ADAPTER_REGISTRY:
        raise ConfigError(
            f"Unknown LLM provider: {provider}. Supported: {', '.join(_ADAPTER_REGISTRY.keys())}"
        )

    adapter_cls = _ADAPTER_REGISTRY[provider_lower]
    init_kwargs: dict[str, object] = {}
    if api_key is not None:
        init_kwargs["api_key"] = api_key
    if base_url is not None:
        init_kwargs["base_url"] = base_url
    init_kwargs.update(kwargs)
    return adapter_cls(**init_kwargs)
