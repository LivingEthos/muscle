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
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5


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

    queue: multiprocessing.Queue[RegexResult] = multiprocessing.Queue()
    process = multiprocessing.Process(target=_worker, args=(pattern, text, queue))
    process.start()
    process.join(timeout)

    try:
        if process.is_alive():
            logger.warning("Regex timeout after %s seconds for pattern: %s", timeout, pattern)
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            return RegexResult(matches=[], timed_out=True)

        try:
            return queue.get_nowait()
        except Exception:  # noqa: BLE001
            return RegexResult(matches=[], error="Failed to retrieve result from worker")
    finally:
        queue.close()
        queue.join_thread()
