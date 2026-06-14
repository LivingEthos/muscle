"""
Shared HTTP helpers for MUSCLE adapters.

Architecture Decision Record (ADR):
- Centralize timeout defaults so adapter calls do not hang indefinitely
- Apply bounded retry/backoff for 429 and transient 5xx responses
- Keep the helper requests-compatible for both module and Session callers
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, cast

import requests

logger = logging.getLogger(__name__)

DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_HTTP_RETRIES = 3


# --- Credential redaction ---------------------------------------------------
# Fix: AD-03. Adapters occasionally include token-bearing strings in warnings
# and error messages. These helpers make it trivial to scrub them before
# anything hits the log stream.

_BEARER_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/=]{8,})")
_TOKEN_PARAM_RE = re.compile(
    r"(?i)((?:access_token|api[_-]?key|token|secret|password)\s*[:=]\s*)"
    r"([A-Za-z0-9\-._~+/=]{8,})"
)
_GHP_RE = re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr|glpat)_[A-Za-z0-9]{20,})\b")


def redact_secrets(text: str | None) -> str:
    """Return ``text`` with obvious tokens/secrets replaced by a placeholder.

    Intended for log/error messages and handoff artifacts. Not a replacement
    for not-logging-the-secret in the first place, but a belt-and-suspenders
    guard so a stray ``logger.debug(f"... {headers}")`` cannot leak a PAT.
    """
    if not text:
        return text or ""
    cleaned = _BEARER_RE.sub(r"\1***REDACTED***", str(text))
    cleaned = _TOKEN_PARAM_RE.sub(r"\1***REDACTED***", cleaned)
    cleaned = _GHP_RE.sub("***REDACTED***", cleaned)
    return cleaned


def request_with_retries(
    client: Any,
    method: str,
    url: str,
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    retries: int = DEFAULT_HTTP_RETRIES,
    **kwargs: Any,
) -> requests.Response:
    """Execute an HTTP request with timeouts and bounded retry/backoff."""
    method_name = method.lower()
    method_fn = getattr(client, method_name, None)
    request_fn = getattr(client, "request", None)

    last_response: requests.Response | None = None
    for attempt in range(retries):
        try:
            if callable(method_fn):
                response = method_fn(url, timeout=timeout, **kwargs)
            elif callable(request_fn):
                response = request_fn(method, url, timeout=timeout, **kwargs)
            else:
                response = requests.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            wait_seconds = float(attempt + 1)
            logger.warning(
                "HTTP request error calling %s %s; retrying in %.1fs",
                method,
                url,
                wait_seconds,
            )
            time.sleep(wait_seconds)
            continue
        last_response = cast(requests.Response, response)

        if last_response.status_code == 429 and attempt < retries - 1:
            retry_after = last_response.headers.get("Retry-After", "")
            wait_seconds = float(retry_after) if retry_after.isdigit() else float(attempt + 1)
            logger.warning(
                "Rate limited calling %s %s; retrying in %.1fs", method, url, wait_seconds
            )
            time.sleep(wait_seconds)
            continue

        if last_response.status_code >= 500 and attempt < retries - 1:
            wait_seconds = float(attempt + 1)
            logger.warning(
                "Transient server error calling %s %s (%s); retrying in %.1fs",
                method,
                url,
                last_response.status_code,
                wait_seconds,
            )
            time.sleep(wait_seconds)
            continue

        return last_response

    if last_response is None:
        msg = f"HTTP request failed without a response: {method} {url}"
        raise RuntimeError(msg)
    return last_response
