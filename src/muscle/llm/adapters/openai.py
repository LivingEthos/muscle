"""OpenAI LLM adapter.

Uses lazy client initialization with asyncio.Lock to avoid
race conditions in concurrent usage.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator

import httpx

from muscle.llm.adapters._shared import handle_llm_error
from muscle.llm.client import LLMClient, LLMRequest, LLMResponse, LLMStreamChunk


class OpenAIClient(LLMClient):
    """OpenAI GPT provider adapter."""

    BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or self.BASE_URL
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def max_rpm(self) -> int:
        return 60

    @property
    def context_window(self) -> int:
        return 128_000

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=self.timeout,
                )
            return self._client

    def _build_payload(self, request: LLMRequest) -> dict[str, object]:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        payload: dict[str, object] = {
            "model": request.model or self.DEFAULT_MODEL,
            "messages": messages,
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        payload.update(request.extra)
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        client = await self._get_client()
        payload = self._build_payload(request)
        model = request.model or self.DEFAULT_MODEL
        try:
            resp = await client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            usage = data.get("usage", {})
            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", model),
                usage_tokens=usage.get("total_tokens"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                finish_reason=choice.get("finish_reason"),
            )
        except Exception as exc:
            raise handle_llm_error(exc, self.provider_name, model, "request") from exc

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        model = request.model or self.DEFAULT_MODEL

        async def _stream() -> AsyncIterator[LLMStreamChunk]:
            client = await self._get_client()
            payload = self._build_payload(request)
            payload["stream"] = True
            try:
                async with client.stream("POST", "/chat/completions", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break

                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            choice = data.get("choices", [{}])[0]
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            finish = choice.get("finish_reason")
                            if content or finish:
                                yield LLMStreamChunk(content=content or "", finish_reason=finish)
            except Exception as exc:
                raise handle_llm_error(exc, self.provider_name, model, "stream") from exc

        return _stream()

    async def health_check(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/models", timeout=10.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        async with self._client_lock:
            if self._client and not self._client.is_closed:
                await self._client.aclose()
