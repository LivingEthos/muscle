"""OpenRouter LLM adapter.

Supports multiple models via a single API endpoint.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

from tools.muscle.llm.adapters._shared import handle_llm_error
from tools.muscle.llm.client import LLMClient, LLMRequest, LLMResponse, LLMStreamChunk


class OpenRouterClient(LLMClient):
    """OpenRouter adapter supporting multiple models via a single API."""

    DEFAULT_MODEL = "openai/gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "https://muscle-v2.local",
            },
            timeout=60.0,
        )

    @property
    def provider_name(self) -> str:
        return "openrouter"

    @property
    def max_rpm(self) -> int:
        return 20

    @property
    def context_window(self) -> int:
        return 128_000

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.DEFAULT_MODEL
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        payload.update(request.extra)

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            usage = data.get("usage", {})
            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", "unknown"),
                usage_tokens=usage.get("total_tokens"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                finish_reason=choice.get("finish_reason"),
            )
        except Exception as e:
            raise handle_llm_error(e, self.provider_name, model, "request") from e

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        model = request.model or self.DEFAULT_MODEL

        async def _stream() -> AsyncIterator[LLMStreamChunk]:
            payload = {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in request.messages],
                "temperature": request.temperature,
                "stream": True,
            }
            if request.max_tokens:
                payload["max_tokens"] = request.max_tokens

            try:
                async with self._client.stream(
                    "POST", "/chat/completions", json=payload
                ) as response:
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
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            finish = data["choices"][0].get("finish_reason")
                            if content or finish:
                                yield LLMStreamChunk(content=content, finish_reason=finish)
            except Exception as e:
                raise handle_llm_error(e, self.provider_name, model, "stream") from e

        return _stream()

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()
