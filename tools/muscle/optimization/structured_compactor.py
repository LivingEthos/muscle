"""
Structured (tabular) payload compaction for MUSCLE prompts.

Architecture Decision Record (ADR):
- Compact only homogeneous "array of records" payloads (analyzer findings, error
  rows) where the same keys repeat across rows; leave code and free prose alone.
- Render a deterministic header + one line per record so the same input is always
  byte-identical (keeps MiniMax-M3 prefix-cache hits stable) and ~40-60% smaller
  than indented JSON.
- Stay reversible: ``expand_records`` reconstructs the records (values normalized
  to strings) so the transform is lossless for the field content the model reads.
- Fall back to JSON whenever the input is not record-shaped or compaction would
  not actually save characters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_COLUMN_SEP = " | "
_HEADER_MARKER = "; columns: "


@dataclass(frozen=True)
class CompactionResult:
    """Outcome of one structured-compaction attempt."""

    text: str
    applied: bool
    original_chars: int
    compact_chars: int
    estimated_tokens_saved: int

    def to_metadata(self) -> dict[str, object]:
        """Return a JSON-serializable telemetry payload."""
        return {
            "structured_compaction_applied": self.applied,
            "structured_compaction_original_chars": self.original_chars,
            "structured_compaction_compact_chars": self.compact_chars,
            "structured_compaction_estimated_tokens_saved": self.estimated_tokens_saved,
        }


def _escape(value: object) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\n", "\\n")
    return text


def _unescape(cell: str) -> str:
    out: list[str] = []
    chars = iter(cell)
    for ch in chars:
        if ch != "\\":
            out.append(ch)
            continue
        nxt = next(chars, "")
        if nxt == "n":
            out.append("\n")
        elif nxt == "|":
            out.append("|")
        elif nxt == "\\":
            out.append("\\")
        else:
            out.append(nxt)
    return "".join(out)


def _json_baseline(records: list[Any]) -> str:
    try:
        return json.dumps(records, indent=2, default=str)
    except (TypeError, ValueError):
        return str(records)


def compact_records(records: list[dict[str, Any]], *, label: str = "records") -> CompactionResult:
    """Compact a list of flat records into a deterministic table.

    Returns a :class:`CompactionResult`. When the payload is empty, not
    record-shaped, or would not shrink, ``applied`` is ``False`` and ``text``
    holds a JSON fallback the caller can still embed verbatim.
    """
    baseline = _json_baseline(list(records))
    if not records:
        return CompactionResult("", False, 0, 0, 0)
    if not all(isinstance(record, dict) for record in records):
        return CompactionResult(baseline, False, len(baseline), len(baseline), 0)

    columns: list[str] = sorted({str(key) for record in records for key in record})
    header = f"{label} ({len(records)}){_HEADER_MARKER}" + _COLUMN_SEP.join(
        _escape(col) for col in columns
    )
    rows = [_COLUMN_SEP.join(_escape(record.get(col, "")) for col in columns) for record in records]
    text = "\n".join([header, *rows])

    original_chars = len(baseline)
    compact_chars = len(text)
    if compact_chars >= original_chars:
        return CompactionResult(baseline, False, original_chars, original_chars, 0)
    return CompactionResult(
        text=text,
        applied=True,
        original_chars=original_chars,
        compact_chars=compact_chars,
        estimated_tokens_saved=max(0, (original_chars - compact_chars) // 4),
    )


def expand_records(text: str) -> list[dict[str, str]]:
    """Reconstruct records from :func:`compact_records` output (values as strings)."""
    if not text.strip():
        return []
    lines = [line for line in text.split("\n") if line]
    if not lines or _HEADER_MARKER not in lines[0]:
        return []

    _, _, col_part = lines[0].partition(_HEADER_MARKER)
    columns = [_unescape(col) for col in col_part.split(_COLUMN_SEP)] if col_part else []
    records: list[dict[str, str]] = []
    for line in lines[1:]:
        cells = [_unescape(cell) for cell in line.split(_COLUMN_SEP)]
        records.append(
            {col: cells[idx] if idx < len(cells) else "" for idx, col in enumerate(columns)}
        )
    return records
