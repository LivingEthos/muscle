"""
Tool-output crusher: host-side context compression with reversible storage.

Architecture Decision Record (ADR):
- Compress large tool outputs (JSON payloads, logs, command output) *before* they
  enter the host model's (Claude Fable 5 / Codex) context, where tokens cost
  10-20x MUSCLE's M3 rates. Exposed via ``muscle crush`` / ``muscle expand``.
- Strategies are deterministic and rule-based so identical input always yields
  byte-identical output (host prompt caching is prefix-matched; a nondeterministic
  compressor would silently invalidate it).
- Accuracy first: anomaly lines (errors, warnings, failures, tracebacks) are never
  collapsed or elided, and every omission is explicit in the output with a count.
  No silent truncation.
- Reversible: originals are saved to a bounded content-addressed store under
  ``.muscle/ccr/`` and retrievable by handle. Loads re-hash the content and fail
  closed on mismatch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..io_safety import advisory_file_lock
from .structured_compactor import compact_records

HANDLE_PREFIX = "ccr:"
_HANDLE_RE = re.compile(r"^ccr:[0-9a-f]{16}$")

DEFAULT_LINE_BUDGET = 200
DEFAULT_RECORD_CAP = 100
_HEAD_FRACTION = 0.6  # share of the line budget given to the head window

# Lines matching any of these are load-bearing signal and are always kept verbatim.
_ANOMALY_RE = re.compile(
    r"\b(error|errors|warn|warning|fail|failed|failure|exception|traceback|fatal|"
    r"panic|denied|refused|critical|assert|assertion)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CrushResult:
    """Outcome of one crush attempt. ``text`` is always safe to embed verbatim."""

    text: str
    applied: bool
    strategy: str
    original_chars: int
    compact_chars: int
    original_lines: int
    kept_lines: int
    estimated_tokens_saved: int
    handle: str | None = None

    def to_metadata(self) -> dict[str, object]:
        """Return a JSON-serializable telemetry payload."""
        return {
            "crush_applied": self.applied,
            "crush_strategy": self.strategy,
            "crush_original_chars": self.original_chars,
            "crush_compact_chars": self.compact_chars,
            "crush_original_lines": self.original_lines,
            "crush_kept_lines": self.kept_lines,
            "crush_estimated_tokens_saved": self.estimated_tokens_saved,
            "crush_handle": self.handle,
        }


class CcrStoreError(RuntimeError):
    """Raised when a stored original is missing or fails integrity verification."""


class CcrStore:
    """Bounded content-addressed store for crushed originals (reversibility).

    Files are named by the content hash, so integrity is inherent in the name;
    ``load`` re-hashes and fails closed on mismatch. Writes are atomic
    (temp file + fsync + ``os.replace``) so a crash never leaves a partial
    original behind.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        max_entries: int = 256,
        max_total_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.root = Path(root)
        self.max_entries = max_entries
        self.max_total_bytes = max_total_bytes

    @staticmethod
    def _digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    def _path_for(self, digest: str) -> Path:
        return self.root / f"{digest}.txt"

    def _lock_target(self) -> Path:
        """Sentinel path whose advisory lock serializes save+prune for the store."""
        return self.root / ".prune"

    def save(self, text: str) -> str:
        """Persist ``text`` and return its retrieval handle (``ccr:<hash16>``).

        Save and prune run as a unit under a store-wide advisory lock so a
        concurrent pruner cannot evict this entry in the window between its write
        and the prune scan (which would silently break a later ``load``).
        """
        data = text.encode("utf-8")
        digest = self._digest(data)
        path = self._path_for(digest)
        self.root.mkdir(parents=True, exist_ok=True)
        with advisory_file_lock(self._lock_target()):
            if not path.exists():
                fd, tmp_name = tempfile.mkstemp(dir=self.root, suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(data)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.chmod(tmp_name, 0o600)
                    os.replace(tmp_name, path)
                except BaseException:
                    Path(tmp_name).unlink(missing_ok=True)
                    raise
                self._prune()
        return f"{HANDLE_PREFIX}{digest}"

    def load(self, handle: str) -> str:
        """Return the original text for ``handle``; fail closed on any mismatch."""
        if not _HANDLE_RE.match(handle):
            raise CcrStoreError(f"malformed handle: {handle!r}")
        digest = handle[len(HANDLE_PREFIX) :]
        path = self._path_for(digest)
        if not path.is_file():
            raise CcrStoreError(f"no stored original for {handle} (it may have been pruned)")
        data = path.read_bytes()
        if self._digest(data) != digest:
            raise CcrStoreError(f"integrity check failed for {handle}; refusing to return content")
        return data.decode("utf-8")

    def _prune(self) -> int:
        """Drop oldest entries beyond the entry/byte bounds. Returns count removed.

        Must be called while holding the store-wide advisory lock (see ``save``);
        the scan + delete is otherwise racy with a concurrent writer's save. The
        lock is intentionally not re-acquired here because ``advisory_file_lock``
        is not reentrant within a process (it opens a fresh fd per call).
        """
        entries = sorted(
            (p for p in self.root.glob("*.txt") if p.is_file()),
            key=lambda p: (p.stat().st_mtime, p.name),
        )
        removed = 0
        total_bytes = sum(p.stat().st_size for p in entries)
        while entries and (len(entries) > self.max_entries or total_bytes > self.max_total_bytes):
            victim = entries.pop(0)
            total_bytes -= victim.stat().st_size
            victim.unlink(missing_ok=True)
            removed += 1
        return removed


def _is_anomaly(line: str) -> bool:
    return bool(_ANOMALY_RE.search(line))


def _try_parse_records(text: str) -> list[dict[str, Any]] | None:
    """Return the payload as a list of dict records when it is one, else None."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        # Common wrapper shapes: {"results": [...]}, {"items": [...]}, etc.
        lists = [v for v in payload.values() if isinstance(v, list) and v]
        payload = lists[0] if len(lists) == 1 else payload
    if (
        isinstance(payload, list)
        and len(payload) >= 2
        and all(isinstance(item, dict) for item in payload)
    ):
        return payload
    return None


def _record_anomalous(record: dict[str, Any]) -> bool:
    try:
        flat = json.dumps(record, default=str)
    except (TypeError, ValueError):
        flat = str(record)
    return _is_anomaly(flat)


def _crush_records(records: list[dict[str, Any]], label: str, record_cap: int) -> str | None:
    """Compact records to a table; cap row count keeping head/tail + anomalies."""
    if len(records) > record_cap:
        head_n = max(1, int(record_cap * _HEAD_FRACTION))
        tail_n = max(1, record_cap - head_n)
        kept_idx = set(range(head_n)) | set(range(len(records) - tail_n, len(records)))
        kept_idx |= {i for i, rec in enumerate(records) if _record_anomalous(rec)}
        selected = [records[i] for i in sorted(kept_idx)]
        omitted = len(records) - len(selected)
        result = compact_records(selected, label=label)
        if not result.applied:
            return None
        note = f"[crush: {omitted} of {len(records)} {label} omitted; full set via handle]"
        return f"{result.text}\n{note}" if omitted else result.text
    result = compact_records(records, label=label)
    return result.text if result.applied else None


def _dedupe_lines(lines: list[str]) -> list[str]:
    """Collapse consecutive duplicate non-anomaly lines into ``line  [xN]``."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i + 1
        while j < len(lines) and lines[j] == line:
            j += 1
        count = j - i
        if count > 1 and not _is_anomaly(line):
            out.append(f"{line}  [x{count}]")
        else:
            out.extend(lines[i:j])
        i = j
    return out


def _window_lines(lines: list[str], line_budget: int) -> list[str]:
    """Keep head/tail within budget plus every anomaly line, eliding explicitly."""
    if len(lines) <= line_budget:
        return lines
    head_n = max(1, int(line_budget * _HEAD_FRACTION))
    tail_n = max(1, line_budget - head_n)
    kept_idx = set(range(head_n)) | set(range(len(lines) - tail_n, len(lines)))
    kept_idx |= {i for i, line in enumerate(lines) if _is_anomaly(line)}

    out: list[str] = []
    prev = -1
    for idx in sorted(kept_idx):
        gap = idx - prev - 1
        if gap > 0:
            out.append(f"[crush: {gap} lines omitted]")
        out.append(lines[idx])
        prev = idx
    return out


def crush_text(
    text: str,
    *,
    label: str = "records",
    line_budget: int = DEFAULT_LINE_BUDGET,
    record_cap: int = DEFAULT_RECORD_CAP,
    store: CcrStore | None = None,
) -> CrushResult:
    """Compress a tool output for host-model consumption.

    Routes by content: JSON array-of-records payloads become deterministic tables
    (reusing the structured compactor); other text gets consecutive-duplicate
    collapsing and, when still over ``line_budget`` lines, anomaly-preserving
    head/tail windowing. When nothing helps, the input is returned unchanged with
    ``applied=False`` — the result always says exactly what happened.
    """
    original_chars = len(text)
    original_lines = text.count("\n") + 1 if text else 0

    # Routing policy: losslessness is preferred over raw size for structured
    # record payloads. The json_records table transform is lossless (it preserves
    # every field of every kept record); the dedupe/window path is lossy (it
    # *elides* whole lines, marking but dropping content). Live benchmarking on
    # structured analyzer JSON showed the lossy window candidate can be far smaller
    # than the table (e.g. 46% vs 91% of original) yet silently discards records —
    # the wrong default for structured data. So when the payload parses as JSON
    # records AND the table beats the original, the table WINS outright, regardless
    # of how small a dedupe/window candidate might be. The dedupe/window path is
    # the candidate for non-record payloads, and the fallback when the table does
    # not beat the original.
    strategy = "none"
    crushed: str | None = None

    records = _try_parse_records(text)
    if records is not None:
        table = _crush_records(records, label, record_cap)
        if table is not None and len(table) < original_chars:
            return _build_result(text, table, "json_records", store)

    lines = text.split("\n")
    deduped = _dedupe_lines(lines)
    applied_parts: list[str] = []
    if len(deduped) < len(lines):
        applied_parts.append("dedupe")
    windowed = _window_lines(deduped, line_budget)
    if len(windowed) < len(deduped):
        applied_parts.append("window")
    if applied_parts:
        candidate = "\n".join(windowed)
        if len(candidate) < original_chars:
            strategy, crushed = "+".join(applied_parts), candidate

    if crushed is None or len(crushed) >= original_chars:
        return CrushResult(
            text=text,
            applied=False,
            strategy="none",
            original_chars=original_chars,
            compact_chars=original_chars,
            original_lines=original_lines,
            kept_lines=original_lines,
            estimated_tokens_saved=0,
            handle=None,
        )

    return _build_result(text, crushed, strategy, store)


def _build_result(
    text: str,
    crushed: str,
    strategy: str,
    store: CcrStore | None,
) -> CrushResult:
    """Assemble an applied ``CrushResult``, persisting the original when a store is set."""
    original_chars = len(text)
    handle = store.save(text) if store is not None else None
    return CrushResult(
        text=crushed,
        applied=True,
        strategy=strategy,
        original_chars=original_chars,
        compact_chars=len(crushed),
        original_lines=text.count("\n") + 1 if text else 0,
        kept_lines=crushed.count("\n") + 1,
        estimated_tokens_saved=max(0, (original_chars - len(crushed)) // 4),
        handle=handle,
    )
