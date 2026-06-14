"""
Regex execution with subprocess-based timeout protection.

Architecture Decision Record (ADR):
- Uses multiprocessing.Process to isolate regex matching from the main process
- Prevents catastrophic backtracking (ReDoS) from untrusted patterns
- Falls back to standard re module for simple patterns when safe
"""

from __future__ import annotations

import logging
import multiprocessing
import queue as queue_module
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5


def _get_regex_process_context() -> Any:
    """Return the fastest available process context for short regex workers."""
    try:
        return multiprocessing.get_context("fork")
    except ValueError:  # pragma: no cover - Windows fallback
        return multiprocessing.get_context()


@dataclass(frozen=True)
class RegexMatch:
    """Result of a single regex match."""

    start: int
    end: int
    groups: tuple[str, ...]


@dataclass(frozen=True)
class RegexResult:
    """Aggregated result of a regex search with timeout and error reporting."""

    matches: list[RegexMatch]
    timed_out: bool = False
    error: str | None = None


def _worker(pattern: str, text: str, queue: multiprocessing.Queue[RegexResult]) -> None:
    """Worker function executed in a separate process."""
    matches: list[RegexMatch] = []
    try:
        for m in re.finditer(pattern, text):
            matches.append(RegexMatch(start=m.start(), end=m.end(), groups=m.groups()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Regex error in worker: %s", exc)
        queue.put(RegexResult(matches=[], error=str(exc)))
        return
    queue.put(RegexResult(matches=matches))


def regex_finditer(
    pattern: str,
    text: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> RegexResult:
    """Find all regex matches with subprocess timeout protection.

    Args:
        pattern: Regular expression pattern string.
        text: Text to search.
        timeout: Maximum seconds to wait for matching.

    Returns:
        RegexResult containing matches, timeout flag, and optional error message.
    """
    if timeout <= 0:
        raise ValueError(f"timeout must be positive, got {timeout}")
    try:
        re.compile(pattern)
    except re.error as exc:
        return RegexResult(matches=[], error=str(exc))

    ctx = _get_regex_process_context()
    result_queue: multiprocessing.Queue[RegexResult] = ctx.Queue()
    process = ctx.Process(target=_worker, args=(pattern, text, result_queue))
    process.start()

    try:
        try:
            result = result_queue.get(timeout=timeout)
        except queue_module.Empty:
            result = None

        if result is not None:
            process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            return result

        if process.is_alive():
            logger.warning("Regex timeout after %s seconds for pattern: %s", timeout, pattern)
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            return RegexResult(matches=[], timed_out=True)

        return RegexResult(matches=[], error="Failed to retrieve result from worker")
    finally:
        # Do NOT join_thread() here: when the worker is hard-killed (process.kill()
        # above) mid-write, the parent's queue feeder thread is left blocked on a
        # dead pipe, and join_thread() would then deadlock the caller indefinitely
        # (documented CPython multiprocessing behavior). cancel_join_thread() lets
        # the feeder abandon any unflushed bytes — the result was already drained
        # (or the worker timed out) so there is nothing left worth flushing.
        result_queue.cancel_join_thread()
        result_queue.close()
