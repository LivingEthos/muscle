"""OpenRouter API client on MUSCLE's synchronous M27Client contract.

Architecture Decision Record (ADR):
- Keep OpenRouter behind the existing provider factory so review orchestration,
  response caching, telemetry, structured retries, and token accounting remain
  shared with other MUSCLE execution backends.
- Treat OpenRouter model identity as gateway-scoped unless the user supplies
  explicit trusted identity evidence elsewhere.
- Do not reuse MiniMax or Anthropic credentials on this path.
"""

from __future__ import annotations

import os
from typing import Any

from .m27_client import CachePlan, M27Client

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-4o-mini"


class OpenRouterApiClient(M27Client):
    """M27Client-compatible OpenRouter adapter.

    OpenRouter speaks the OpenAI-compatible chat-completions shape, so the base
    client can keep handling requests, structured-output retries, caching, and
    usage parsing. This subclass only owns credentials, headers, and provider
    payload cleanup.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = OPENROUTER_DEFAULT_MODEL,
        **kwargs: Any,
    ) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ValueError(
                "OpenRouter API key is required for the openrouter-api provider: pass "
                "api_key or set OPENROUTER_API_KEY."
            )
        super().__init__(
            api_key=key,
            base_url=OPENROUTER_API_BASE,
            model=model,
            **kwargs,
        )

    def _get_headers(self) -> dict[str, str]:
        """OpenRouter auth headers; never use Anthropic or MiniMax key aliases."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "HTTP-Referer": "https://muscle.local",
            "X-Title": "MUSCLE",
        }

    def _prepare_payload(
        self,
        payload: dict[str, Any],
        is_openai_compatible: bool,
        thinking: str | None = None,
        cache_plan: CachePlan | None = None,
        stage: str | None = None,
    ) -> dict[str, Any]:
        """Strip provider-specific fields OpenRouter should not receive."""
        payload.pop("thinking", None)
        payload.pop("reasoning_split", None)
        return payload
