"""
Prompt compaction helpers for MUSCLE-authored runtime prose.

Architecture Decision Record (ADR):
- Compact prompts at render time only so stored traces remain authoritative
- Preserve code blocks, commands, URLs, JSON, stack traces, and path-heavy lines verbatim
- Enable default compaction only for benchmark-gated low-risk stages
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SAFE_COMPACTION_STAGES = frozenset({"generate", "evolve", "handoff"})

_FENCE_RE = re.compile(r"^\s*```")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
_COMMAND_RE = re.compile(
    r"^\s*(?:\$|uv run|python(?:3)?|pytest|git|npm|pnpm|yarn|cargo|go test|make|bash|sh)\b"
)
_PATH_RE = re.compile(r"(?:^|[\s`'\"(])(?:/|\.?/|[A-Za-z0-9_.-]+/)[^\s`'\")]+")
_URL_RE = re.compile(r"https?://")
_JSON_LIKE_RE = re.compile(r"^\s*(?:[{[]|\"[^\"]+\"\s*:)")
_STACK_TRACE_RE = re.compile(
    r'^\s*(?:Traceback \(most recent call last\):|File ".*", line \d+|[A-Za-z_][A-Za-z0-9_]*Error:)'
)

_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Your task is to:", re.IGNORECASE), "Task:"),
    (re.compile(r"\bYour goal is to\b", re.IGNORECASE), "Goal:"),
    (
        re.compile(r"\bProvide your findings in JSON format\.", re.IGNORECASE),
        "Return JSON findings.",
    ),
    (re.compile(r"\bProvide your review in JSON format\.", re.IGNORECASE), "Return a JSON review."),
    (re.compile(r"\bProvide your response in JSON format\.", re.IGNORECASE), "Return JSON."),
    (
        re.compile(
            r"\bPlease investigate this thoroughly and provide your findings and proposed solutions\.",
            re.IGNORECASE,
        ),
        "Investigate thoroughly and propose validated fixes.",
    ),
    (re.compile(r"Focus areas for this pressure test:", re.IGNORECASE), "Focus:"),
    (re.compile(r"\bPlease\b\s*", re.IGNORECASE), ""),
    (re.compile(r"\bin JSON format\b", re.IGNORECASE), "as JSON"),
)


@dataclass(frozen=True)
class PromptCompactionMetrics:
    """Telemetry-friendly prompt compaction metrics."""

    applied: bool
    original_chars: int
    compacted_chars: int
    compaction_ratio: float
    estimated_tokens_saved: int

    def to_metadata(self) -> dict[str, object]:
        """Return a JSON-serializable metadata payload."""
        return {
            "prompt_compaction_applied": self.applied,
            "prompt_compaction_original_chars": self.original_chars,
            "prompt_compaction_compacted_chars": self.compacted_chars,
            "prompt_compaction_ratio": self.compaction_ratio,
            "prompt_compaction_estimated_tokens_saved": self.estimated_tokens_saved,
        }


def should_compact_stage(stage: str) -> bool:
    """Return whether prompt compaction is benchmark-gated on for this stage."""
    return stage in SAFE_COMPACTION_STAGES


def compact_prompt_text(prompt: str) -> tuple[str, PromptCompactionMetrics]:
    """Compact a prompt while preserving protected content classes verbatim."""
    original_chars = len(prompt)
    if not prompt.strip():
        return prompt, _build_metrics(prompt, prompt)

    compacted = _compact_lines(prompt)
    if len(compacted) >= original_chars:
        compacted = prompt
    return compacted, _build_metrics(prompt, compacted)


def _compact_lines(prompt: str) -> str:
    lines = prompt.splitlines()
    compacted_lines: list[str] = []
    prose_buffer: list[str] = []
    in_fence = False

    def flush_prose() -> None:
        if not prose_buffer:
            return
        compacted_lines.extend(_compact_prose_buffer(prose_buffer))
        prose_buffer.clear()

    for line in lines:
        if _FENCE_RE.match(line):
            flush_prose()
            compacted_lines.append(line)
            in_fence = not in_fence
            continue

        if in_fence or _is_protected_line(line):
            flush_prose()
            compacted_lines.append(line)
            continue

        if not line.strip():
            flush_prose()
            if compacted_lines and compacted_lines[-1] != "":
                compacted_lines.append("")
            continue

        prose_buffer.append(line)

    flush_prose()
    while compacted_lines and compacted_lines[-1] == "":
        compacted_lines.pop()
    return "\n".join(compacted_lines)


def _compact_prose_buffer(lines: list[str]) -> list[str]:
    compacted: list[str] = []
    for line in lines:
        compacted_line = _compact_prose_line(line)
        if compacted_line:
            compacted.append(compacted_line)
    return compacted


def _compact_prose_line(line: str) -> str:
    collapsed = re.sub(r"\s+", " ", line.strip())
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        collapsed = pattern.sub(replacement, collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    return collapsed


def _is_protected_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return any(
        (
            _LIST_MARKER_RE.match(line),
            _COMMAND_RE.match(line),
            _URL_RE.search(line),
            _PATH_RE.search(line),
            _JSON_LIKE_RE.match(line),
            _STACK_TRACE_RE.match(line),
        )
    )


def _build_metrics(original_prompt: str, compacted_prompt: str) -> PromptCompactionMetrics:
    original_chars = len(original_prompt)
    compacted_chars = len(compacted_prompt)
    saved_chars = max(0, original_chars - compacted_chars)
    return PromptCompactionMetrics(
        applied=saved_chars > 0,
        original_chars=original_chars,
        compacted_chars=compacted_chars,
        compaction_ratio=(compacted_chars / original_chars) if original_chars else 1.0,
        estimated_tokens_saved=max(0, saved_chars // 4),
    )
