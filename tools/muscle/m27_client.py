"""
MiniMax M2.7 API client for MUSCLE.

Architecture Decision Record (ADR):
- Using direct HTTP calls with robust error handling
- Token usage tracking for budget management
- Streaming support for long responses
- Rate limiting with exponential backoff retry
- Connection pooling for concurrent requests
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

ANTHROPIC_BASE_URL_COM = "https://api.minimaxi.com/anthropic"
ANTHROPIC_BASE_URL_IO = "https://api.minimax.io/anthropic"
DEFAULT_MODEL = "MiniMax-M2.7"

DEFAULT_TIMEOUT = 120
MAX_RETRIES = 5
RATE_LIMIT_DELAY = 1.0

DEFAULT_SYSTEM_PROMPT = """You are a helpful coding assistant.
IMPORTANT: You must respond with TEXT content only in your responses.
Do NOT include thinking blocks in your output.
Start your response directly with the answer or content requested.
Code should always be in proper code blocks with language identifiers."""


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class RateLimiter:
    def __init__(self, calls_per_second: float = 10.0):
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call = time.time()


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int = 5) -> None:
        self.semaphore = threading.Semaphore(max_concurrent)
        self.active = 0
        self.lock = threading.Lock()

    def __enter__(self) -> ConcurrencyLimiter:
        self.semaphore.acquire()
        with self.lock:
            self.active += 1
        return self

    def __exit__(self, *args: Any) -> None:
        with self.lock:
            self.active -= 1
        self.semaphore.release()


def _detect_api_base() -> str:
    explicit = os.environ.get("ANTHROPIC_BASE_URL")
    if explicit:
        return explicit
    explicit_io = os.environ.get("MINIMAX_API_BASE")
    if explicit_io == "io":
        return ANTHROPIC_BASE_URL_IO
    elif explicit_io == "com":
        return ANTHROPIC_BASE_URL_COM
    return ANTHROPIC_BASE_URL_IO


def _create_session() -> requests.Session:
    session = requests.Session()

    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20,
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


class M27Client:
    _global_rate_limiter = RateLimiter(calls_per_second=10.0)
    _global_concurrency_limiter = ConcurrencyLimiter(max_concurrent=5)
    _session: requests.Session | None = None
    _session_lock = threading.Lock()

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        self.api_key = (
            api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "API key is required. Set ANTHROPIC_API_KEY or MINIMAX_API_KEY environment variable."
            )

        self.base_url = base_url or _detect_api_base()
        self.model = model
        self.timeout = max(10, min(timeout, 300))
        self.max_retries = max(1, min(max_retries, 10))

        with self._session_lock:
            if M27Client._session is None:
                M27Client._session = _create_session()

        self._rate_limit_errors = 0
        self._last_request_time: float | None = None

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "anthropic-version": "2023-06-01",
            "User-Agent": "MUSCLE/1.0",
        }

    def _should_retry(self, error: str, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False

        retryable = [
            "429",
            "rate limit",
            "timeout",
            "502",
            "503",
            "504",
            "connection",
            "timeout",
        ]

        return any(r.lower() in error.lower() for r in retryable)

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        stream: bool = False,
    ) -> tuple[str, TokenUsage]:
        if not messages:
            logger.error("Empty messages list provided to chat()")
            return "", TokenUsage()

        if not isinstance(messages, list):
            logger.error(f"Messages must be a list, got {type(messages).__name__}")
            return "", TokenUsage()

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                logger.error(f"Message at index {i} is not a dict: {type(msg).__name__}")
                return "", TokenUsage()
            if "role" not in msg or "content" not in msg:
                logger.error(f"Message at index {i} missing 'role' or 'content'")
                return "", TokenUsage()
            if not isinstance(msg.get("content", ""), str):
                logger.error(f"Message content at index {i} is not a string")
                return "", TokenUsage()

        has_system_in_messages = any(msg.get("role") == "system" for msg in messages)
        effective_system = (
            (system or DEFAULT_SYSTEM_PROMPT)[:2000] if not has_system_in_messages else ""
        )

        max_tokens = max(1, min(max_tokens, 8192))
        temperature = max(0.0, min(temperature, 2.0))

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if effective_system:
            payload["system"] = effective_system

        last_error = None
        backoff = 1.0
        thinking_only_count = 0

        for attempt in range(self.max_retries):
            try:
                M27Client._global_rate_limiter.wait()

                with M27Client._global_concurrency_limiter:
                    session: Any = M27Client._session
                    response = session.post(
                        f"{self.base_url}/v1/messages",
                        headers=self._get_headers(),
                        json=payload,
                        timeout=self.timeout,
                    )

                if response.status_code == 200:
                    self._rate_limit_errors = 0
                    try:
                        data = response.json()
                    except json.JSONDecodeError as e:
                        last_error = f"Failed to parse response JSON: {e}"
                        logger.error(f"Attempt {attempt + 1}: {last_error}")
                        time.sleep(backoff)
                        backoff *= 2
                        continue

                    if not isinstance(data, dict):
                        last_error = f"Invalid response type: {type(data).__name__}"
                        logger.error(f"Attempt {attempt + 1}: {last_error}")
                        time.sleep(backoff)
                        backoff *= 2
                        continue

                    usage = TokenUsage(
                        input_tokens=data.get("usage", {}).get("input_tokens", 0) or 0,
                        output_tokens=data.get("usage", {}).get("output_tokens", 0) or 0,
                    )

                    text_content = ""
                    has_text = False
                    thinking_only = True

                    content_blocks = data.get("content", [])
                    if not isinstance(content_blocks, list):
                        content_blocks = []

                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type", "")
                        if block_type == "text":
                            text_content = block.get("text", "") or ""
                            has_text = True
                            thinking_only = False
                            break

                    if has_text and text_content.strip():
                        return text_content.strip(), usage

                    if thinking_only:
                        thinking_only_count += 1
                        if thinking_only_count >= 2:
                            last_error = "Model only returned thinking blocks, no text generated"
                            logger.warning(f"Attempt {attempt + 1}: {last_error}")
                            time.sleep(backoff)
                            backoff *= 2
                            continue

                    if not text_content.strip():
                        last_error = "Empty text response from API"
                        logger.warning(f"Attempt {attempt + 1}: Empty response, retrying...")
                        time.sleep(backoff)
                        backoff *= 2
                        continue

                    return text_content.strip(), usage

                elif response.status_code == 429:
                    self._rate_limit_errors += 1
                    last_error = "Rate limited (429)"
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait_time = (
                            float(retry_after)
                            if retry_after and retry_after.replace(".", "").isdigit()
                            else backoff
                        )
                    except (ValueError, TypeError):
                        wait_time = backoff

                    logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    backoff *= 2
                    continue

                elif response.status_code == 401:
                    last_error = "Authentication error (401). Check your API key."
                    logger.error(f"API error: {last_error}")
                    break

                elif response.status_code == 403:
                    last_error = "Forbidden (403). Check your permissions."
                    logger.error(f"API error: {last_error}")
                    break

                elif response.status_code == 404:
                    last_error = "Not found (404). API endpoint may have changed."
                    logger.error(f"API error: {last_error}")
                    break

                elif response.status_code >= 500:
                    last_error = f"Server error ({response.status_code})"
                    logger.warning(f"Server error: {response.status_code}, retrying...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                else:
                    try:
                        error_text = response.text[:500] if response.text else "No response body"
                    except Exception:
                        error_text = "Could not read response"
                    last_error = f"API error: {response.status_code} - {error_text}"
                    logger.error(f"API error: {last_error}")
                    break

            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {e}"
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue

            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue

            except Exception as e:
                last_error = f"Unexpected error: {type(e).__name__}: {e}"
                logger.error(f"Unexpected error: {last_error}")
                break

        logger.error(f"All {self.max_retries} attempts failed. Last error: {last_error}")
        return "", TokenUsage()

    def chat_streaming(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        timeout: int | None = None,
    ) -> Iterator[tuple[str, TokenUsage | None]]:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system

        request_timeout = timeout or self.timeout
        last_error = None
        backoff = 1.0

        for attempt in range(self.max_retries):
            try:
                M27Client._global_rate_limiter.wait()

                with M27Client._global_concurrency_limiter:
                    session: Any = M27Client._session
                    response = session.post(
                        f"{self.base_url}/v1/messages",
                        headers=self._get_headers(),
                        json=payload,
                        timeout=request_timeout,
                        stream=True,
                    )

                if response.status_code == 200:
                    self._rate_limit_errors = 0
                    yield from self._parse_sse_stream(response)
                    return

                elif response.status_code == 429:
                    self._rate_limit_errors += 1
                    last_error = "Rate limited (429)"
                    retry_after = response.headers.get("Retry-After", str(backoff))
                    wait_time = float(retry_after) if retry_after.isdigit() else backoff

                    logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    backoff *= 2
                    continue

                elif response.status_code >= 500:
                    last_error = f"Server error ({response.status_code})"
                    logger.warning(f"Server error: {response.status_code}, retrying...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                else:
                    last_error = f"API error: {response.status_code} - {response.text[:200]}"
                    logger.error(f"API error: {last_error}")
                    break

            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {e}"
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue

            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue

            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.error(f"Unexpected error: {e}")
                break

        logger.error(f"All {self.max_retries} attempts failed. Last error: {last_error}")
        yield "", None

    def _parse_sse_stream(
        self, response: requests.Response
    ) -> Iterator[tuple[str, TokenUsage | None]]:
        accumulated_text = ""
        usage = None

        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue

            if line.startswith("data: "):
                data = line[6:]

                if data.strip() == "[DONE]":
                    break

                try:
                    event_data = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if "content" in event_data:
                    for block in event_data.get("content", []):
                        if block.get("type") == "text":
                            delta = block.get("text", "")
                            if delta:
                                accumulated_text += delta
                                yield accumulated_text, None

                if "usage" in event_data:
                    usage = TokenUsage(
                        input_tokens=event_data["usage"].get("input_tokens", 0),
                        output_tokens=event_data["usage"].get("output_tokens", 0),
                    )
                    yield accumulated_text, usage

                if "error" in event_data:
                    error_msg = event_data.get("error", {}).get("message", "Unknown error")
                    logger.error(f"Streaming error: {error_msg}")
                    break

        yield "", usage

    def chat_with_history(
        self,
        user_message: str,
        history: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, TokenUsage]:
        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        return self.chat(messages=messages, system=system, max_tokens=max_tokens)

    def format_messages(self, user_message: str, history: list[dict] | None = None) -> list[dict]:
        msgs = []
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_message})
        return msgs

    def get_rate_limit_status(self) -> dict:
        return {
            "rate_limit_errors": self._rate_limit_errors,
            "base_url": self.base_url,
            "model": self.model,
        }

    def reset_rate_limits(self) -> None:
        self._rate_limit_errors = 0
