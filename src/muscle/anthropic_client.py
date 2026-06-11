"""Direct Anthropic API client for the anthropic-api provider (Opus only).

Per the repo contract (CLAUDE.md): sampling params (temperature/top_p/top_k)
are stripped on this path — Opus 4.8 returns 400 on them. MUSCLE's per-stage
thinking policy maps onto Opus effort: adaptive stages -> effort "high",
disabled stages -> effort "medium". Opus-only is a hard product decision.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any

from .m27_client import CachePlan, M27Client

logger = logging.getLogger("muscle.anthropic_client")

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

# The only model this provider speaks. Hard product decision: never Sonnet or
# Haiku — MUSCLE's cheap bulk execution lives on MiniMax; the Anthropic path
# exists exclusively for top-tier Opus reasoning.
ANTHROPIC_OPUS_MODEL = "claude-opus-4-8"

# MUSCLE thinking-policy stage mode -> Opus 4.8 effort. Adaptive thinking is
# the only on-mode on Opus 4.8 (disabled stages simply omit the thinking key),
# so "enabled" collapses to adaptive + high effort.
_EFFORT_FOR_THINKING: dict[str | None, str] = {
    "adaptive": "high",
    "enabled": "high",
    "disabled": "medium",
    None: "medium",
}


def _host_is_anthropic(url: str) -> bool:
    """True only when the URL's HOSTNAME identifies an Anthropic endpoint.

    Substring-matching the whole URL is spoofable (e.g.
    ``https://evil.example.com/anthropic.com`` puts "anthropic.com" only in
    the path), so parse out the hostname and check that alone.
    """
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        return False
    host = host.lower()
    return host == "anthropic.com" or host.endswith(".anthropic.com")


def _detect_anthropic_api_base() -> str:
    """Resolve the Anthropic API base URL, guarding against credential leaks.

    Mirror of ``m27_client._detect_api_base`` with the host check inverted:
    this provider holds a real Anthropic credential, so an ANTHROPIC_BASE_URL
    pointing anywhere other than an Anthropic host would leak it.
    """
    explicit = os.environ.get("ANTHROPIC_BASE_URL")
    if explicit:
        if _host_is_anthropic(explicit) or os.environ.get("MUSCLE_ALLOW_CUSTOM_BASE_URL") == "1":
            return explicit
        logger.warning(
            "Ignoring ANTHROPIC_BASE_URL=%r for the anthropic-api provider: it does not "
            "point at an Anthropic host (sending the Anthropic credential elsewhere would "
            "leak it). Set MUSCLE_ALLOW_CUSTOM_BASE_URL=1 for a custom proxy/gateway.",
            explicit,
        )
    return ANTHROPIC_API_BASE


class AnthropicApiClient(M27Client):
    """M27Client variant speaking to the real Anthropic API with Opus 4.8.

    Inherits chat()/chat_structured() (schema hints, validation, response
    cache) from M27Client; this subclass only swaps endpoint, headers, and the
    payload contract via the ``_prepare_payload`` provider hook.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = ANTHROPIC_OPUS_MODEL,
        **kwargs: Any,
    ) -> None:
        if model != ANTHROPIC_OPUS_MODEL:
            raise ValueError(
                f"AnthropicApiClient is Opus-only (hard product decision): model must be "
                f"{ANTHROPIC_OPUS_MODEL!r}, got {model!r}. Sonnet/Haiku are intentionally "
                "unsupported — cheap bulk execution belongs on the MiniMax provider."
            )
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "Anthropic API key is required for the anthropic-api provider: pass "
                "api_key or set the ANTHROPIC_API_KEY environment variable."
            )
        if (
            not key.startswith("sk-ant-")
            and os.environ.get("MUSCLE_ALLOW_NONSTANDARD_ANTHROPIC_KEY") != "1"
        ):
            raise ValueError(
                "Refusing to use a credential without the 'sk-ant-' prefix on the "
                "anthropic-api provider: in this repo ANTHROPIC_API_KEY is historically "
                "a MiniMax alias, and sending a possibly-MiniMax credential to "
                "api.anthropic.com would leak it. Set "
                "MUSCLE_ALLOW_NONSTANDARD_ANTHROPIC_KEY=1 to allow a non-standard key."
            )
        super().__init__(
            api_key=key,
            base_url=_detect_anthropic_api_base(),
            model=model,
            **kwargs,
        )

    def _get_headers(self) -> dict[str, str]:
        """Anthropic auth headers (x-api-key, never an Authorization bearer)."""
        return {
            "x-api-key": str(self.api_key),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _prepare_payload(
        self,
        payload: dict[str, Any],
        is_openai_compatible: bool,
        thinking: str | None = None,
        cache_plan: CachePlan | None = None,
    ) -> dict[str, Any]:
        """Adapt the MiniMax-shaped payload to the Opus 4.8 request contract."""
        # Opus 4.8 returns 400 on sampling params — never send them.
        for param in ("temperature", "top_p", "top_k"):
            payload.pop(param, None)

        mode = str(thinking).strip().lower() if thinking is not None else None
        if mode in ("adaptive", "enabled"):
            # Adaptive is the only on-mode on Opus 4.8.
            payload["thinking"] = {"type": "adaptive"}
        else:
            # Disabled/None: omit the thinking key entirely (the safe off-shape).
            payload.pop("thinking", None)
        payload["output_config"] = {"effort": _EFFORT_FOR_THINKING.get(mode, "medium")}

        # Write-amortization rule: a cache write only pays off when at least
        # one more call is expected to reuse the prefix within the TTL.
        if cache_plan is not None and cache_plan.expected_reuse >= 1:
            self._insert_cache_breakpoint(payload, cache_plan)
        return payload

    @staticmethod
    def _insert_cache_breakpoint(payload: dict[str, Any], plan: CachePlan) -> None:
        """Split the first user message at the shared-prefix boundary and mark it.

        Converts a plain-string content into Anthropic text blocks with a
        ``cache_control`` breakpoint on the shared prefix. No-op when the
        content is not a plain string or the split point is zero.
        """
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return
        first = messages[0]
        if not isinstance(first, dict):
            return
        content = first.get("content")
        if not isinstance(content, str):
            return
        split = min(plan.shared_prefix_chars, len(content))
        if split <= 0:
            return
        cache_control: dict[str, str] = {"type": "ephemeral"}
        if plan.ttl == "1h":
            cache_control["ttl"] = "1h"
        blocks: list[dict[str, Any]] = [
            {"type": "text", "text": content[:split], "cache_control": cache_control}
        ]
        suffix = content[split:]
        if suffix:
            blocks.append({"type": "text", "text": suffix})
        first["content"] = blocks
