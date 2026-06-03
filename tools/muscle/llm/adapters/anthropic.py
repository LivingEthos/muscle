"""Anthropic Claude LLM adapter.

Uses Anthropic's native /messages API (not OpenAI-compatible).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

from tools.muscle.llm.adapters._shared import handle_llm_error
from tools.muscle.llm.client import LLMClient, LLMRequest, LLMResponse, LLMStreamChunk


class AnthropicClient(LLMClient):
    """Anthropic Claude adapter."""

    DEFAULT_MODEL = "claude-3-5-sonnet-20241022"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "x-api-key": self._api_key or "",
                "anthropic-version": "2023-06-01",
            },
            timeout=60.0,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def max_rpm(self) -> int:
        return 50

    @property
    def context_window(self) -> int:
        return 200_000

    def _build_messages(self, request: LLMRequest) -> tuple[str, list[dict[str, str]]]:
        """Extract system message and build Anthropic-format message list."""
        system_msg = ""
        messages = []
        for m in request.messages:
            if m.role == "system":
                system_msg = m.content
            else:
                messages.append({"role": m.role, "content": m.content})
        return system_msg, messages

    def _build_payload(
        self, request: LLMRequest, model: str, stream: bool = False
    ) -> dict[str, object]:
        system_msg, messages = self._build_messages(request)
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "temperature": request.temperature,
        }
        if system_msg:
            payload["system"] = system_msg
        if stream:
            payload["stream"] = True
        payload.update(request.extra)
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.DEFAULT_MODEL
        payload = self._build_payload(request, model)
        try:
            resp = await self._client.post("/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    content += block.get("text", "")
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            return LLMResponse(
                content=content,
                model=data.get("model", "unknown"),
                usage_tokens=input_tokens + output_tokens,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                finish_reason=data.get("stop_reason"),
            )
        except Exception as e:
            raise handle_llm_error(e, self.provider_name, model, "request") from e

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        model = request.model or self.DEFAULT_MODEL
        payload = self._build_payload(request, model, stream=True)

        async def _stream() -> AsyncIterator[LLMStreamChunk]:
            try:
                async with self._client.stream("POST", "/messages", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            if data.get("type") == "content_block_delta":
                                delta = data.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    yield LLMStreamChunk(content=text)
                            elif data.get("type") == "message_stop":
                                yield LLMStreamChunk(content="", finish_reason="stop")
            except Exception as e:
                raise handle_llm_error(e, self.provider_name, model, "stream") from e

        return _stream()

    async def health_check(self) -> bool:
        """Best-effort health check.

        Anthropic doesn't have a lightweight health endpoint, so we
        simply return True. Circuit breaker failure tracking handles
        real outages.
        """
        return True

    async def close(self) -> None:
        await self._client.aclose()
