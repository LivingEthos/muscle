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

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from .optimization.types import TelemetryContext

logger = logging.getLogger(__name__)

ANTHROPIC_BASE_URL_COM = "https://api.minimaxi.com/anthropic"
ANTHROPIC_BASE_URL_IO = "https://api.minimax.io/anthropic"
OPENAI_BASE_URL_IO = "https://api.minimax.io/v1"
DEFAULT_MODEL = "MiniMax-M3"

DEFAULT_TIMEOUT = 120
MAX_RETRIES = 5
RATE_LIMIT_DELAY = 1.0

# Per-model output-token ceilings. MiniMax-M3 supports far larger outputs than
# the legacy 8192 default. The exact M3 ceiling is undocumented; 32768 is a
# conservative value well within a 1M-context frontier model. Confirm against
# MiniMax docs before relying on outputs near this size.
DEFAULT_MAX_OUTPUT_TOKENS = 8192
MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "minimax-m3": 32768,
}

# MiniMax-M3 request-time thinking modes. "adaptive" is MiniMax's recommended
# mode (the model decides reasoning depth); "disabled" turns reasoning off for
# latency-sensitive calls; "enabled" forces reasoning.
VALID_THINKING_MODES = frozenset({"disabled", "adaptive", "enabled"})

DEFAULT_SYSTEM_PROMPT = """You are an expert Python/Coding assistant with strong self-correction abilities.
You are working in a self-improvement loop where you generate code, receive errors, and iterate.
Your strengths: excellent at following precise formats, thorough error analysis, specific recommendations.

OUTPUT FORMAT: You must respond with valid JSON when a JSON schema is provided.
EXAMPLES: When given an example format, follow it exactly.
REASONING: For complex issues, briefly explain your reasoning before the answer.
THINKING: If uncertain, state your assumptions clearly before proceeding.
CODE: Always use proper code blocks with language identifiers."""

# Temperature presets for different task types
TEMP_PRECISE = 0.2  # Fix generation, exact JSON output
TEMP_FOCUSED = 0.3  # Code review analysis, structured output
TEMP_BALANCED = 0.4  # Code generation with some creativity
TEMP_CREATIVE = 0.5  # Strategy evolution, creative solutions


class M27StructuredError(Exception):
    """Raised when chat_structured fails to produce valid JSON after retries."""

    pass


def _strip_json_fences(text: str) -> str:
    """Extract JSON body if wrapped in ```json or ``` fences."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json") :].lstrip("\n")
    elif text.startswith("```"):
        text = text[len("```") :].lstrip("\n")
    if text.endswith("```"):
        text = text[: -len("```")].rstrip("\n")
    return text.strip()


def _strip_thinking_tags(text: str) -> str:
    """Remove model thinking tags that can precede structured JSON."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _max_output_tokens_for(model: str) -> int:
    """Resolve the output-token ceiling for a model (model-aware cap)."""
    key = (model or "").strip().lower()
    for pattern, cap in MODEL_MAX_OUTPUT_TOKENS.items():
        if pattern in key:
            return cap
    return DEFAULT_MAX_OUTPUT_TOKENS


def _apply_thinking_param(
    payload: dict[str, Any],
    thinking: str | None,
    is_openai_compatible: bool,
) -> None:
    """Inject MiniMax-M3's request-time thinking control into a request payload.

    No-op when ``thinking`` is None (keeps legacy requests byte-identical) or an
    unrecognized mode is passed (fail-safe). MiniMax ignores unknown request
    fields, so a wrong-shaped field is dropped server-side rather than rejected.

    - OpenAI-compatible endpoint: boolean ``reasoning_split``.
    - Anthropic-compatible endpoint: ``thinking: {"type": <mode>}``.
    """
    if thinking is None:
        return
    mode = str(thinking).strip().lower()
    if mode not in VALID_THINKING_MODES:
        return
    if is_openai_compatible:
        payload["reasoning_split"] = mode != "disabled"
    else:
        payload["thinking"] = {"type": mode}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    # Subset of input_tokens served from MiniMax-M3's passive prefix cache at the
    # discounted cache-hit rate. input_tokens is normalized to the full prompt size
    # (fresh + cached), so cached_input_tokens <= input_tokens always holds. Captured
    # from the provider usage payload so cost accounting can credit the discount and
    # the cache-hit rate stays observable.
    cached_input_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class StructuredCallMetadata:
    """Metadata about one `chat_structured` execution."""

    usage: TokenUsage
    cache_hit: bool = False
    cache_key: str | None = None
    tokens_saved_estimate: int = 0
    # Fix: H4. True when the underlying generation was cut off by the output
    # token ceiling (stop_reason/finish_reason in {max_tokens, length}). A
    # truncated result is never cached and callers can detect incompleteness.
    truncated: bool = False


class RateLimiter:
    def __init__(self, calls_per_second: float = 10.0):
        self.calls_per_second = max(0.1, calls_per_second)
        self.min_interval = 1.0 / self.calls_per_second
        self.last_call = 0.0
        self.lock = threading.Lock()

    def wait(self) -> None:
        # Compute the sleep duration and reserve the next slot under the lock, then
        # sleep OUTSIDE the lock so concurrent callers space out in parallel rather
        # than serializing behind a single held lock.
        with self.lock:
            now = time.time()
            elapsed = now - self.last_call
            sleep_for = self.min_interval - elapsed if elapsed < self.min_interval else 0.0
            # Advance the slot to account for the sleep we are about to perform.
            self.last_call = now + sleep_for
        if sleep_for > 0:
            time.sleep(sleep_for)


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


def _host_is_minimax(url: str) -> bool:
    """True only when the URL's HOSTNAME identifies a MiniMax endpoint.

    Substring-matching the whole URL is spoofable (e.g.
    ``https://evil.com/minimax/path`` puts "minimax" only in the path), so we
    parse out the hostname with ``urlsplit`` and check that alone. Covers
    ``api.minimax.io``, ``api.minimaxi.com``, and regional variants by looking
    for "minimax" anywhere in the hostname labels.
    """
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        return False
    return "minimax" in host.lower()


def _detect_api_base() -> str:
    explicit = os.environ.get("ANTHROPIC_BASE_URL")
    if explicit:
        # Security (credential-leak guard): MUSCLE only ever talks to MiniMax,
        # and MINIMAX_API_KEY / its ANTHROPIC_API_KEY alias are MiniMax
        # credentials. Hosts like Claude Code export
        # ANTHROPIC_BASE_URL=https://api.anthropic.com into every shell; honoring
        # it would silently POST the MiniMax key to a third party. Only honor an
        # explicit base URL that points at a MiniMax host, unless the operator
        # opts in via MUSCLE_ALLOW_CUSTOM_BASE_URL=1 (proxies/gateways).
        if _host_is_minimax(explicit) or os.environ.get("MUSCLE_ALLOW_CUSTOM_BASE_URL") == "1":
            return explicit
        logger.warning(
            "Ignoring ANTHROPIC_BASE_URL=%r: it points at a non-MiniMax host and "
            "MUSCLE only authenticates to MiniMax (sending the MiniMax credential "
            "elsewhere would leak it). Falling back to the MiniMax default. Set "
            "MUSCLE_ALLOW_CUSTOM_BASE_URL=1 to allow a custom proxy/gateway URL.",
            explicit,
        )
    explicit_io = os.environ.get("MINIMAX_API_BASE")
    if explicit_io == "io":
        return ANTHROPIC_BASE_URL_IO
    elif explicit_io == "com":
        return ANTHROPIC_BASE_URL_COM
    elif explicit_io == "openai":
        return OPENAI_BASE_URL_IO
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


STREAM_ERROR_PREFIX = "__MUSCLE_STREAM_ERROR__:"

# Maximum wait for a 429 Retry-After, in seconds. Protects against
# malformed/malicious headers that could otherwise stall the worker for
# arbitrary durations. Fix: M27-03.
MAX_RETRY_AFTER_SECONDS = 300.0


def _parse_retry_after(retry_after: str | None, default: float) -> float:
    """Parse a ``Retry-After`` header value, clamped to a sane range.

    Accepts integers and floats (including scientific notation). Returns
    ``default`` for missing, malformed, or non-finite values. Clamps results
    to ``[0, MAX_RETRY_AFTER_SECONDS]``. Fix: M27-03.
    """
    if not retry_after:
        return default
    try:
        value = float(retry_after.strip())
    except (ValueError, AttributeError):
        return default
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return max(0.0, min(value, MAX_RETRY_AFTER_SECONDS))


class M27Client:
    _rate_limit: float | None = None
    _max_concurrent: int | None = None
    _rate_limiter: RateLimiter | None = None
    _concurrency_limiter: ConcurrencyLimiter | None = None
    _session: requests.Session | None = None
    # Single consolidated init lock covers session + limiter configuration to
    # avoid lock-ordering deadlocks (fix: M27-08).
    _init_lock = threading.RLock()

    @classmethod
    def _get_session(cls) -> requests.Session:
        """Return the shared HTTP session, initializing it once under lock.

        Fix: M27-01 (race condition), M27-02 (null check on consumer side).
        """
        session = cls._session
        if session is None:
            with cls._init_lock:
                if cls._session is None:
                    cls._session = _create_session()
                session = cls._session
        if session is None:  # pragma: no cover - defensive
            raise RuntimeError("M27Client session failed to initialize")
        return session

    # Default TTL for response cache entries (14 days in seconds).
    DEFAULT_CACHE_TTL = 14 * 24 * 60 * 60

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        rate_limit: float | None = None,
        max_concurrent: int | None = None,
        cache_db_path: Path | None = None,
        cache_pack_id: str | None = None,
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

        # Ensure shared session is initialized before first request.
        M27Client._get_session()

        self._configure_limiters(rate_limit, max_concurrent)

        self._rate_limit_errors = 0
        self._last_request_time: float | None = None
        self._telemetry_sink: Any | None = None
        self._model_identity: dict[str, Any] = {}
        from .response_cache import DEFAULT_DB

        self._cache_db_path: Path | None = cache_db_path or DEFAULT_DB
        self._cache_pack_id: str | None = cache_pack_id
        self._structured_metrics_lock = threading.Lock()
        self._structured_cache_hits = 0
        self._structured_cache_tokens_saved = 0

    def _configure_limiters(self, rate_limit: float | None, max_concurrent: int | None) -> None:
        with M27Client._init_lock:
            env_rate = self._parse_positive_float_env("MUSCLE_RATE_LIMIT", 10.0)
            env_concurrent = self._parse_positive_int_env("MUSCLE_MAX_CONCURRENT", 5)

            requested_rate = max(0.1, rate_limit if rate_limit is not None else env_rate)
            requested_concurrent = max(
                1,
                max_concurrent if max_concurrent is not None else env_concurrent,
            )

            if (
                M27Client._rate_limiter is None
                or M27Client._rate_limit != requested_rate
                or M27Client._max_concurrent != requested_concurrent
            ):
                if M27Client._rate_limiter is not None:
                    logger.info(
                        "Reconfiguring M27 limiters: rate=%s concurrency=%s",
                        requested_rate,
                        requested_concurrent,
                    )
                M27Client._rate_limit = requested_rate
                M27Client._max_concurrent = requested_concurrent
                M27Client._rate_limiter = RateLimiter(calls_per_second=M27Client._rate_limit)
                M27Client._concurrency_limiter = ConcurrencyLimiter(
                    max_concurrent=M27Client._max_concurrent
                )

    @staticmethod
    def _parse_positive_float_env(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError:
            logger.warning("Invalid %s=%r; using default %s", name, raw, default)
            return default
        if value <= 0:
            logger.warning("Invalid %s=%r; using default %s", name, raw, default)
            return default
        return value

    @staticmethod
    def _parse_positive_int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            logger.warning("Invalid %s=%r; using default %s", name, raw, default)
            return default
        if value <= 0:
            logger.warning("Invalid %s=%r; using default %s", name, raw, default)
            return default
        return value

    def _get_headers(self) -> dict[str, str]:
        """Return request headers for MiniMax Anthropic and OpenAI-compatible endpoints."""
        api_key = str(self.api_key)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "MUSCLE/1.0",
        }
        if self.base_url.rstrip("/").endswith("/anthropic") and api_key.startswith("sk-cp-"):
            headers["X-Api-Key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["Authorization"] = f"Bearer {api_key}"
            if self.base_url.rstrip("/").endswith("/anthropic"):
                headers["anthropic-version"] = "2023-06-01"
        return headers

    def set_telemetry_sink(self, telemetry_sink: Any | None) -> None:
        """Attach a best-effort telemetry sink."""
        self._telemetry_sink = telemetry_sink

    def set_model_identity(self, model_identity: dict[str, Any] | None) -> None:
        """Attach the resolved canonical model identity for telemetry."""
        self._model_identity = dict(model_identity or {})

    def _telemetry_model_identity(self) -> dict[str, Any]:
        """Return normalized model identity fields for telemetry persistence."""
        from .model_identity import endpoint_fingerprint

        requested_label = self._model_identity.get("requested_label", self.model)
        provider_endpoint = self._model_identity.get("provider_endpoint", self.base_url)
        provider_fingerprint = self._model_identity.get("provider_fingerprint")
        if provider_fingerprint is None:
            provider_fingerprint = endpoint_fingerprint(provider_endpoint)
        return {
            "requested_label": requested_label,
            "provider_endpoint": provider_endpoint,
            "provider_fingerprint": provider_fingerprint,
            "canonical_model_key": self._model_identity.get("canonical_model_key"),
            "identity_source": self._model_identity.get("identity_source", "client_default"),
            "confidence": float(self._model_identity.get("confidence", 0.0) or 0.0),
            "manual_override": bool(self._model_identity.get("manual_override")),
        }

    def _should_adopt_model_identity(self, candidate_identity: dict[str, Any]) -> bool:
        """Return whether stronger provider evidence should replace current identity."""
        if not candidate_identity:
            return False
        current_identity = self._telemetry_model_identity()
        if current_identity.get("manual_override"):
            return False

        current_key = current_identity.get("canonical_model_key")
        candidate_key = candidate_identity.get("canonical_model_key")
        current_confidence = float(current_identity.get("confidence", 0.0) or 0.0)
        candidate_confidence = float(candidate_identity.get("confidence", 0.0) or 0.0)

        if not current_key and candidate_key:
            return True
        if (
            candidate_key
            and candidate_key != current_key
            and candidate_confidence >= current_confidence
        ):
            return True
        if (
            candidate_key == current_key
            and candidate_identity.get("identity_source") == "provider_introspection"
            and current_identity.get("identity_source") != "provider_introspection"
        ):
            return True
        return candidate_confidence > current_confidence + 1e-9

    def _record_model_identity_history(
        self,
        telemetry_context: TelemetryContext | None,
        model_identity: dict[str, Any],
    ) -> None:
        """Persist refined model identity when a telemetry sink supports it."""
        if telemetry_context is None or self._telemetry_sink is None:
            return
        record_fn = getattr(self._telemetry_sink, "record_model_identity_history", None)
        if not callable(record_fn):
            return
        try:
            record_fn(telemetry_context.project_path, model_identity)
        except Exception:
            logger.debug("Model identity recording failed", exc_info=True)

    def _maybe_refresh_model_identity_from_response(
        self,
        response_payload: dict[str, Any],
        telemetry_context: TelemetryContext | None,
    ) -> None:
        """Refine model identity from trusted provider response evidence."""
        try:
            from .model_identity import introspect_provider_response_identity

            candidate = introspect_provider_response_identity(
                requested_label=str(
                    self._model_identity.get("requested_label") or self.model or ""
                ),
                provider_endpoint=str(
                    self._model_identity.get("provider_endpoint") or self.base_url
                ),
                response_payload=response_payload,
                manual_override=bool(self._model_identity.get("manual_override")),
            )
            if candidate is None or not self._should_adopt_model_identity(candidate.__dict__):
                return
            self._model_identity = candidate.__dict__
            self._record_model_identity_history(telemetry_context, candidate.__dict__)
        except Exception:
            logger.debug("Provider-specific model introspection failed", exc_info=True)

    def _record_telemetry(
        self,
        telemetry_context: TelemetryContext | None,
        usage: TokenUsage,
        duration_ms: int,
        success: bool,
    ) -> None:
        if telemetry_context is None or self._telemetry_sink is None:
            return
        try:
            from .optimization import LLMCallEvent

            metadata = dict(telemetry_context.metadata)
            model_identity = self._telemetry_model_identity()
            metadata.setdefault("language", telemetry_context.language or "unknown")
            metadata.setdefault("complexity", telemetry_context.complexity or "unknown")
            metadata.setdefault("target_type", telemetry_context.target_type or "unknown")
            metadata.setdefault("task_category", telemetry_context.task_category or "unknown")
            metadata["requested_label"] = model_identity["requested_label"]
            metadata["provider_endpoint"] = model_identity["provider_endpoint"]
            metadata["provider_fingerprint"] = model_identity["provider_fingerprint"]
            metadata["canonical_model_key"] = model_identity["canonical_model_key"]
            metadata["identity_source"] = model_identity["identity_source"]
            metadata["identity_confidence"] = model_identity["confidence"]
            metadata["manual_override"] = model_identity["manual_override"]
            # Persist prefix-cache hits so the savings report can credit the
            # discount and surface cache-hit rate (savings.build_savings_report
            # aggregates the "cached_input_tokens" metadata key).
            if usage.cached_input_tokens:
                metadata["cached_input_tokens"] = usage.cached_input_tokens
            self._telemetry_sink.record_llm_call(
                LLMCallEvent(
                    project_path=telemetry_context.project_path,
                    call_id=telemetry_context.call_id,
                    session_id=telemetry_context.session_id,
                    stage=telemetry_context.stage,
                    workflow_name=telemetry_context.workflow_name,
                    review_mode=telemetry_context.review_mode,
                    model=self.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    duration_ms=duration_ms,
                    success=success,
                    context_chars=telemetry_context.context_chars,
                    context_strategy=telemetry_context.context_strategy,
                    requested_label=model_identity["requested_label"],
                    provider_endpoint=model_identity["provider_endpoint"],
                    provider_fingerprint=model_identity["provider_fingerprint"],
                    canonical_model_key=model_identity["canonical_model_key"],
                    identity_source=model_identity["identity_source"],
                    identity_confidence=model_identity["confidence"],
                    manual_override=model_identity["manual_override"],
                    metadata_json=json.dumps(metadata, sort_keys=True),
                )
            )
        except Exception:
            logger.debug("Telemetry recording failed", exc_info=True)

    def update_telemetry_call(
        self,
        call_id: str,
        parse_success: bool | None = None,
        validation_success: bool | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> None:
        """Forward outcome updates to the attached telemetry sink."""
        if self._telemetry_sink is None:
            return
        try:
            self._telemetry_sink.update_llm_call(
                call_id=call_id,
                parse_success=parse_success,
                validation_success=validation_success,
                metadata_updates=metadata_updates or {},
            )
        except Exception:
            logger.debug("Telemetry update failed", exc_info=True)

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        stream: bool = False,
        telemetry_context: TelemetryContext | None = None,
        thinking: str | None = None,
        response_format: dict[str, Any] | None = None,
        _metadata_sink: dict[str, Any] | None = None,
    ) -> tuple[str, TokenUsage]:
        # Type errors are programming bugs, not recoverable conditions: a plain
        # string passed where a list is expected used to log and return an empty
        # ("", TokenUsage()) success, silently masking the caller's mistake. Raise
        # so the bug surfaces at the call site. (Check type before truthiness so a
        # non-list — e.g. "" — raises rather than being treated as "empty".)
        if not isinstance(messages, list):
            raise TypeError(f"messages must be a list, got {type(messages).__name__}")

        if not messages:
            logger.error("Empty messages list provided to chat()")
            return "", TokenUsage()

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                raise TypeError(f"messages[{i}] must be a dict, got {type(msg).__name__}")
            if "role" not in msg or "content" not in msg:
                raise ValueError(f"messages[{i}] missing 'role' or 'content'")
            if not isinstance(msg.get("content", ""), str):
                raise TypeError(f"messages[{i}]['content'] must be a string")

        has_system_in_messages = any(msg.get("role") == "system" for msg in messages)
        effective_system = (
            (system or DEFAULT_SYSTEM_PROMPT)[:2000] if not has_system_in_messages else ""
        )

        max_tokens = max(1, min(max_tokens, _max_output_tokens_for(self.model)))
        temperature = max(0.0, min(temperature, 2.0))

        endpoint_base = self.base_url.rstrip("/")
        is_openai_compatible = endpoint_base.endswith("/v1")
        payload_messages = [dict(message) for message in messages]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if effective_system:
            if is_openai_compatible:
                payload_messages.insert(0, {"role": "system", "content": effective_system})
            else:
                payload["system"] = effective_system

        _apply_thinking_param(payload, thinking, is_openai_compatible)
        if response_format is not None:
            payload["response_format"] = response_format

        # Fix: M27/M9. Estimate input tokens from the actual prompt size (all
        # message contents + system prompt, ~4 chars/token) for use as a fallback
        # when the provider omits usage. Using output length for input badly
        # under-counts input and corrupts cost accounting.
        prompt_chars = sum(len(str(m.get("content", ""))) for m in payload_messages)
        prompt_chars += len(effective_system)
        estimated_input_tokens = max(1, prompt_chars // 4)

        last_error = None
        backoff = 1.0
        thinking_only_count = 0
        started_at = time.perf_counter()
        endpoint_path = "/chat/completions" if is_openai_compatible else "/v1/messages"

        for attempt in range(self.max_retries):
            try:
                if M27Client._rate_limiter:
                    M27Client._rate_limiter.wait()

                if M27Client._concurrency_limiter:
                    with M27Client._concurrency_limiter:
                        session = M27Client._get_session()
                        response = session.post(
                            f"{endpoint_base}{endpoint_path}",
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

                    self._maybe_refresh_model_identity_from_response(data, telemetry_context)

                    # Fix: H4. Surface a truncation signal so callers (chat_structured)
                    # can avoid caching/treating a length-truncated reply as complete.
                    if _metadata_sink is not None:
                        stop_reason = data.get("stop_reason")
                        choices_for_finish = data.get("choices")
                        if not stop_reason and isinstance(choices_for_finish, list):
                            if choices_for_finish and isinstance(choices_for_finish[0], dict):
                                stop_reason = choices_for_finish[0].get("finish_reason")
                        _metadata_sink["stop_reason"] = stop_reason
                        _metadata_sink["truncated"] = str(stop_reason or "").lower() in {
                            "max_tokens",
                            "length",
                        }

                    usage_payload = data.get("usage") or {}
                    if not isinstance(usage_payload, dict):
                        usage_payload = {}
                    input_tokens = int(
                        usage_payload.get("input_tokens") or usage_payload.get("prompt_tokens") or 0
                    )
                    output_tokens = int(
                        usage_payload.get("output_tokens")
                        or usage_payload.get("completion_tokens")
                        or 0
                    )
                    if input_tokens == 0 and output_tokens == 0:
                        total_tokens = int(usage_payload.get("total_tokens") or 0)
                        if total_tokens > 0:
                            # Fix: M27/M9. Split a bare total into input/output using
                            # the estimated prompt size rather than attributing the
                            # entire total to input, which under-counts output.
                            input_tokens = min(estimated_input_tokens, total_tokens)
                            output_tokens = total_tokens - input_tokens
                    # MiniMax-M3 reports reasoning/thinking tokens either as a flat
                    # field (Anthropic-shape) or nested under completion_tokens_details
                    # (OpenAI-shape). Capture either for thinking-mode telemetry.
                    completion_details = usage_payload.get("completion_tokens_details")
                    reasoning_tokens = int(
                        usage_payload.get("reasoning_tokens")
                        or (
                            completion_details.get("reasoning_tokens")
                            if isinstance(completion_details, dict)
                            else 0
                        )
                        or 0
                    )
                    # Prefix-cache hits, normalized so input_tokens is always the
                    # FULL prompt size and cached_input_tokens is the cached subset.
                    # The two API shapes disagree on what input_tokens counts
                    # (verified against live MiniMax-M3 responses):
                    #   Anthropic shape (MiniMax /anthropic): `input_tokens` counts
                    #     only FRESH input; `cache_read_input_tokens` is DISJOINT, so
                    #     the full prompt is their sum. Fold cached back in.
                    #   OpenAI shape: `prompt_tokens` already INCLUDES cached, exposed
                    #     as a subset under `prompt_tokens_details.cached_tokens`.
                    cache_read = int(usage_payload.get("cache_read_input_tokens") or 0)
                    prompt_details = usage_payload.get("prompt_tokens_details")
                    openai_cached = int(
                        (
                            prompt_details.get("cached_tokens")
                            if isinstance(prompt_details, dict)
                            else 0
                        )
                        or usage_payload.get("cached_tokens")
                        or 0
                    )
                    if cache_read:
                        input_tokens += cache_read
                        cached_input_tokens = cache_read
                    else:
                        cached_input_tokens = min(openai_cached, input_tokens)
                    usage = TokenUsage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        reasoning_tokens=reasoning_tokens,
                        cached_input_tokens=cached_input_tokens,
                    )
                    # Fix: M27-06. Non-empty 200 response with zero tokens on both
                    # sides is almost always a provider telemetry gap worth
                    # surfacing in logs so cost accounting is auditable.
                    if (
                        usage.input_tokens == 0
                        and usage.output_tokens == 0
                        and isinstance(data.get("content"), list)
                        and data.get("content")
                    ):
                        logger.warning("Provider returned zero token usage on non-empty response")

                    text_content = ""
                    has_text = False
                    thinking_only = True

                    if is_openai_compatible:
                        choices = data.get("choices", [])
                        if isinstance(choices, list) and choices:
                            first_choice = choices[0]
                            if isinstance(first_choice, dict):
                                message = first_choice.get("message", {})
                                if isinstance(message, dict):
                                    text_content = str(message.get("content") or "")
                                    has_text = bool(text_content)
                                    thinking_only = False
                    else:
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

                    if usage.input_tokens == 0 and usage.output_tokens == 0 and text_content:
                        # Fix: M27/M9. Estimate input from the actual prompt size and
                        # output from the response length, rather than using the
                        # response length for both (which under-counts input).
                        usage = TokenUsage(
                            input_tokens=estimated_input_tokens,
                            output_tokens=max(1, len(text_content) // 4),
                        )

                    if has_text and text_content.strip():
                        self._record_telemetry(
                            telemetry_context,
                            usage,
                            int((time.perf_counter() - started_at) * 1000),
                            True,
                        )
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
                    wait_time = _parse_retry_after(response.headers.get("Retry-After"), backoff)

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

            except ValueError as e:
                # Fix: M27-05. ValueError indicates a programming error (e.g. bad
                # argument) that retrying will not resolve — break immediately.
                last_error = f"Value error (non-retryable): {e}"
                logger.error(f"Non-retryable error: {last_error}")
                break

            except (requests.RequestException, json.JSONDecodeError) as e:
                # Fix: M27-05. Transient network / parse errors — retry.
                last_error = f"Transient error: {type(e).__name__}: {e}"
                logger.warning(
                    f"Transient error (attempt {attempt + 1}/{self.max_retries}): {last_error}"
                )
                time.sleep(backoff)
                backoff *= 2
                continue

        logger.error(f"All {self.max_retries} attempts failed. Last error: {last_error}")
        failure_usage = TokenUsage()
        self._record_telemetry(
            telemetry_context,
            failure_usage,
            int((time.perf_counter() - started_at) * 1000),
            False,
        )
        return "", failure_usage

    def chat_streaming(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        timeout: int | None = None,
        telemetry_context: TelemetryContext | None = None,
        thinking: str | None = None,
    ) -> Iterator[tuple[str, TokenUsage | None]]:
        # Same contract as chat(): a non-list messages argument is a caller bug,
        # not a recoverable condition. Raise rather than streaming garbage.
        if not isinstance(messages, list):
            raise TypeError(f"messages must be a list, got {type(messages).__name__}")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max(1, min(max_tokens, _max_output_tokens_for(self.model))),
            "temperature": temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system
        # Streaming always posts to the Anthropic /v1/messages path below, so use
        # the Anthropic-shaped thinking control.
        _apply_thinking_param(payload, thinking, is_openai_compatible=False)

        request_timeout = timeout or self.timeout
        last_error = None
        backoff = 1.0
        started_at = time.perf_counter()
        # Fix: C2. Once any chunk has been yielded to the consumer, a mid-stream
        # failure must NOT trigger a fresh retry — restarting the stream re-emits
        # already-delivered cumulative text and corrupts the consumer's view.
        streamed_any = False

        for attempt in range(self.max_retries):
            try:
                if M27Client._rate_limiter:
                    M27Client._rate_limiter.wait()

                if M27Client._concurrency_limiter:
                    with M27Client._concurrency_limiter:
                        session = M27Client._get_session()
                        response = session.post(
                            f"{self.base_url}/v1/messages",
                            headers=self._get_headers(),
                            json=payload,
                            timeout=request_timeout,
                            stream=True,
                        )

                if response.status_code == 200:
                    self._rate_limit_errors = 0
                    final_usage: TokenUsage | None = None
                    stream_failed = False
                    for accumulated_text, usage in self._parse_sse_stream(
                        response,
                        telemetry_context=telemetry_context,
                    ):
                        # Fix: H3. A sentinel-prefixed payload signals a provider
                        # mid-stream error; record failure and stop, do not retry.
                        if accumulated_text.startswith(STREAM_ERROR_PREFIX):
                            stream_failed = True
                            last_error = accumulated_text[len(STREAM_ERROR_PREFIX) :]
                            yield accumulated_text, usage
                            break
                        if usage is not None:
                            final_usage = usage
                        streamed_any = True
                        yield accumulated_text, usage
                    self._record_telemetry(
                        telemetry_context,
                        final_usage or TokenUsage(),
                        int((time.perf_counter() - started_at) * 1000),
                        not stream_failed,
                    )
                    return

                elif response.status_code == 429:
                    response.close()
                    self._rate_limit_errors += 1
                    last_error = "Rate limited (429)"
                    wait_time = _parse_retry_after(response.headers.get("Retry-After"), backoff)

                    logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    backoff *= 2
                    continue

                elif response.status_code >= 500:
                    last_error = f"Server error ({response.status_code})"
                    response.close()
                    logger.warning(f"Server error: {response.status_code}, retrying...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                else:
                    last_error = f"API error: {response.status_code} - {response.text[:200]}"
                    response.close()
                    logger.error(f"API error: {last_error}")
                    break

            except requests.exceptions.Timeout as e:
                last_error = f"Timeout: {e}"
                if streamed_any:
                    logger.error(f"Mid-stream timeout after partial output: {last_error}")
                    break
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue

            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {e}"
                if streamed_any:
                    logger.error(f"Mid-stream connection error after partial output: {last_error}")
                    break
                logger.warning(f"Connection error (attempt {attempt + 1}/{self.max_retries})")
                time.sleep(backoff)
                backoff *= 2
                continue

            except ValueError as e:
                # Fix: M27-05. ValueError is non-retryable in streaming path too.
                last_error = f"Value error (non-retryable): {e}"
                logger.error(f"Non-retryable streaming error: {last_error}")
                break

            except (requests.RequestException, json.JSONDecodeError) as e:
                # Fix: M27-05. Transient errors in streaming path — retry.
                last_error = f"Transient error: {type(e).__name__}: {e}"
                if streamed_any:
                    # Fix: C2. Already delivered partial output; do not restart.
                    logger.error(f"Mid-stream transient error after partial output: {last_error}")
                    break
                logger.warning(
                    f"Transient streaming error (attempt {attempt + 1}/{self.max_retries}):"
                    f" {last_error}"
                )
                time.sleep(backoff)
                backoff *= 2
                continue

        logger.error(f"All {self.max_retries} attempts failed. Last error: {last_error}")
        self._record_telemetry(
            telemetry_context,
            TokenUsage(),
            int((time.perf_counter() - started_at) * 1000),
            False,
        )
        # Fix: M27-04. Emit a sentinel-prefixed error payload so downstream
        # consumers (code_generator, evolver, tests) can distinguish an upstream
        # failure from a legitimate empty end-of-stream event.
        yield f"{STREAM_ERROR_PREFIX}{last_error or 'streaming failed'}", None

    def _parse_sse_stream(
        self,
        response: requests.Response,
        telemetry_context: TelemetryContext | None = None,
    ) -> Iterator[tuple[str, TokenUsage | None]]:
        accumulated_text = ""
        usage = None

        # Fix: C1. Always close the streaming response so the underlying socket
        # is released back to the pool, even if the consumer abandons iteration.
        try:
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

                    if isinstance(event_data, dict):
                        self._maybe_refresh_model_identity_from_response(
                            event_data, telemetry_context
                        )

                    if "content" in event_data:
                        for block in event_data.get("content", []):
                            if block.get("type") == "text":
                                delta = block.get("text", "")
                                if delta:
                                    accumulated_text += delta
                                    yield accumulated_text, None

                    if "usage" in event_data:
                        stream_usage = event_data["usage"]
                        stream_input = int(stream_usage.get("input_tokens", 0) or 0)
                        # Anthropic-shape streaming reports cache_read_input_tokens
                        # disjoint from input_tokens; fold it in so input_tokens is the
                        # full prompt and cached_input_tokens is a subset (matches chat()).
                        stream_cache_read = int(stream_usage.get("cache_read_input_tokens", 0) or 0)
                        usage = TokenUsage(
                            input_tokens=stream_input + stream_cache_read,
                            output_tokens=int(stream_usage.get("output_tokens", 0) or 0),
                            cached_input_tokens=stream_cache_read,
                        )
                        yield accumulated_text, usage

                    if "error" in event_data:
                        error_msg = event_data.get("error", {}).get("message", "Unknown error")
                        logger.error(f"Streaming error: {error_msg}")
                        # Fix: H3. Surface a provider mid-stream error as a sentinel
                        # so chat_streaming records success=False instead of falling
                        # through to a clean end-of-stream that looks successful.
                        yield f"{STREAM_ERROR_PREFIX}{error_msg}", None
                        return
        finally:
            response.close()

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

    def _ensure_structured_metrics_state(self) -> None:
        if not hasattr(self, "_structured_metrics_lock"):
            self._structured_metrics_lock = threading.Lock()
        if not hasattr(self, "_structured_cache_hits"):
            self._structured_cache_hits = 0
        if not hasattr(self, "_structured_cache_tokens_saved"):
            self._structured_cache_tokens_saved = 0

    def consume_structured_cache_metrics(self) -> dict[str, int]:
        """Return and reset aggregate structured-call cache metrics."""
        self._ensure_structured_metrics_state()
        with self._structured_metrics_lock:
            metrics = {
                "cache_hits": self._structured_cache_hits,
                "cache_tokens_saved": self._structured_cache_tokens_saved,
            }
            self._structured_cache_hits = 0
            self._structured_cache_tokens_saved = 0
            return metrics

    def chat_structured(
        self,
        schema: type[Any],
        messages: list[dict],
        system: str = "",
        max_tokens: int = 4096,
        retries: int = 2,
        telemetry_context: TelemetryContext | None = None,
        include_metadata: bool = False,
        thinking: str | None = None,
    ) -> Any:
        """Call M2.7, parse response as JSON, validate against Pydantic schema.

        Retries on ValidationError with a schema-corrective follow-up.
        Raises M27StructuredError after retries + 1 total attempts.

        Fix: B.5. If self._cache_pack_id is set, it is included in the cache
        key so that pack updates invalidate stale cache entries.
        """
        from pydantic import ValidationError

        from .response_cache import ResponseCache

        schema_hint = (
            f"Reply ONLY with valid JSON matching this schema:\n{schema.model_json_schema()}"
        )
        system_with_schema = f"{system}\n\n{schema_hint}" if system else schema_hint

        # --- Cache lookup ---
        # Fix: L12. Derive the cache key from a hash of the FULL serialized message
        # list (roles + content, in order), not just concatenated user turns. The
        # previous key ignored assistant/history turns, so two multi-turn calls that
        # shared user messages but differed in history collided into a stale hit.
        user_content = hashlib.sha256(
            json.dumps(
                [(m.get("role", ""), m.get("content", "")) for m in messages],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        cache: ResponseCache | None = None
        cache_key: str | None = None
        if self._cache_db_path is not None:
            cache = ResponseCache(self._cache_db_path)
            cache_key = ResponseCache.build_key(
                model_id=self.model,
                system_prompt=system_with_schema,
                user_prompt=user_content,
                pack_id=self._cache_pack_id,  # Fix: B.5 wire pack content-hash
            )
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug("ResponseCache hit for chat_structured key=%s", cache_key[:12])
                self._ensure_structured_metrics_state()
                with self._structured_metrics_lock:
                    self._structured_cache_hits += 1
                    self._structured_cache_tokens_saved += max_tokens
                validated = schema.model_validate(cached)
                # A cache hit costs ZERO new tokens, so report zero usage.
                # Synthesizing max_tokens//2 / max_tokens//2 here fabricated spend
                # that flowed into ReviewStats and delegation cost accounting as if
                # real. tokens_saved_estimate keeps the heuristic (max_tokens): the
                # ResponseCache only persists the validated response dict plus a
                # tokens_saved column it never returns from get(), so the original
                # call's real input/output split is not recoverable on a hit.
                cached_usage = TokenUsage()
                metadata = StructuredCallMetadata(
                    usage=cached_usage,
                    cache_hit=True,
                    cache_key=cache_key,
                    tokens_saved_estimate=max_tokens,
                )
                if include_metadata:
                    return validated, metadata
                return validated

        last_error: Exception | None = None
        working_messages = list(messages)

        for attempt in range(retries + 1):
            call_meta: dict[str, Any] = {}
            response_text, usage = self.chat(
                messages=working_messages,
                system=system_with_schema,
                max_tokens=max_tokens,
                temperature=0.1,
                telemetry_context=telemetry_context,
                thinking=thinking,
                _metadata_sink=call_meta,
            )
            truncated = bool(call_meta.get("truncated"))
            parsed_text = _strip_json_fences(_strip_thinking_tags(response_text))
            try:
                data = json.loads(parsed_text)
                validated = schema.model_validate(data)
                if telemetry_context is not None:
                    self.update_telemetry_call(
                        telemetry_context.call_id,
                        parse_success=True,
                        validation_success=True,
                    )
                # --- Cache store on success ---
                # Fix: H4. Never cache a length-truncated response: it parsed and
                # validated by luck but is not the complete intended output, and a
                # 14-day TTL would serve the partial answer to every future caller.
                if cache is not None and cache_key is not None and not truncated:
                    cache.put(
                        key=cache_key,
                        model_id=self.model,
                        response=data,
                        ttl_seconds=M27Client.DEFAULT_CACHE_TTL,
                    )
                metadata = StructuredCallMetadata(
                    usage=usage,
                    cache_hit=False,
                    cache_key=cache_key,
                    truncated=truncated,
                )
                if include_metadata:
                    return validated, metadata
                return validated
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                if telemetry_context is not None:
                    self.update_telemetry_call(
                        telemetry_context.call_id,
                        parse_success=not isinstance(e, json.JSONDecodeError),
                        validation_success=not isinstance(e, ValidationError),
                        metadata_updates={"schema_error": str(e)},
                    )
                if attempt < retries:
                    working_messages.append({"role": "assistant", "content": response_text})
                    working_messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Your last response did not match the schema: {e}. "
                                "Reply ONLY with valid JSON matching the schema."
                            ),
                        }
                    )
                else:
                    raise M27StructuredError(
                        f"Failed to produce schema-valid response after {retries + 1} "
                        f"attempts. Last error: {e}"
                    ) from e
        raise M27StructuredError(f"Unreachable: {last_error}")
