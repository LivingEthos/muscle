"""MiniMax LLM adapter using Anthropic-compatible API.

Architecture Decision Record (ADR):
- Uses httpx.AsyncClient for async I/O (v2 pattern, replacing v1's requests)
- Preserves v1's telemetry/identity/cache via M27Client facade (see integration section)
- DEFAULT_MODEL="MiniMax-M3" matches v1's canonical default model
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx

from muscle.llm.adapters._shared import handle_llm_error
from muscle.llm.client import LLMClient, LLMRequest, LLMResponse, LLMStreamChunk
from muscle.llm.tool_schema_compat import normalize_openai_compatible_payload


class MiniMaxClient(LLMClient):
    """MiniMax adapter using their Anthropic-compatible API endpoint."""

    DEFAULT_MODEL = "MiniMax-M3"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.minimax.io/v1",
    ) -> None:
        self._api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    @property
    def provider_name(self) -> str:
        return "minimax"

    @property
    def max_rpm(self) -> int:
        return 20

    @property
    def context_window(self) -> int:
        return 1_000_000

    def _build_messages(self, request: LLMRequest) -> tuple[str, list[dict[str, str]]]:
        """Extract system message and build message list."""
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
        return normalize_openai_compatible_payload(payload).payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self.DEFAULT_MODEL
        payload = self._build_payload(request, model)
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")
            usage = data.get("usage", {})
            return LLMResponse(
                content=content,
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
        payload = self._build_payload(request, model, stream=True)

        async def _stream() -> AsyncIterator[LLMStreamChunk]:
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
