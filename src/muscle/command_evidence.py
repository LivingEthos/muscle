"""
Command evidence helpers for MUSCLE tool execution.

Architecture Decision Record (ADR):
- Keep raw command output in project-local review artifacts, not in prompts.
- Preserve existing evaluator return contracts while attaching structured
  evidence for diagnostics, savings reporting, and parser health.
- Degrade safely: compact output is always available even when raw artifacts
  cannot be written.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .io_safety import atomic_write_json, atomic_write_text

logger = logging.getLogger(__name__)

DEFAULT_COMPACT_MAX_CHARS = 4_000
DEFAULT_RAW_ARTIFACT_MAX_CHARS = 200_000
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
FAILURE_PATTERN = re.compile(r"\b(error|failed|failure|traceback|exception)\b", re.IGNORECASE)


class ParserTier(str, Enum):
    """Parse quality for command output."""

    FULL = "FULL"
    DEGRADED = "DEGRADED"
    PASSTHROUGH = "PASSTHROUGH"


@dataclass
class CommandEvidence:
    """Structured evidence for a command run."""

    command: list[str]
    cwd: str
    exit_code: int
    duration_ms: int
    raw_stdout_path: str | None = None
    raw_stderr_path: str | None = None
    compact_stdout: str = ""
    compact_stderr: str = ""
    parser_tier: str = ParserTier.FULL.value
    tokens_raw_estimate: int = 0
    tokens_compact_estimate: int = 0
    warnings: list[str] = field(default_factory=list)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    artifact_dir: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    @property
    def tokens_saved_estimate(self) -> int:
        """Estimated tokens saved by compacting raw command output."""
        return max(0, self.tokens_raw_estimate - self.tokens_compact_estimate)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        data = asdict(self)
        data["tokens_saved_estimate"] = self.tokens_saved_estimate
        return data


def estimate_tokens(text: str) -> int:
    """Estimate model tokens from text length."""
    if not text:
        return 0
    return int(math.ceil(len(text) / 4))


def compact_output(text: str, max_chars: int = DEFAULT_COMPACT_MAX_CHARS) -> tuple[str, bool]:
    """Compact command output without hiding failure signals."""
    if not text:
        return "", False

    lines = [line.rstrip() for line in text.replace("\r\n", "\n").splitlines()]
    compacted_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line.strip():
            if previous_blank:
                continue
            previous_blank = True
            compacted_lines.append("")
            continue
        previous_blank = False
        compacted_lines.append(line)

    compacted = "\n".join(compacted_lines).strip()
    if len(compacted) <= max_chars:
        return compacted, False

    head_budget = max_chars // 2
    tail_budget = max_chars - head_budget
    omitted = len(compacted) - max_chars
    truncated = (
        compacted[:head_budget].rstrip()
        + f"\n... [command output truncated, {omitted} chars omitted] ...\n"
        + compacted[-tail_budget:].lstrip()
    )
    return truncated, True


def command_label(command: list[str]) -> str:
    """Return a stable display label for a command list."""
    return " ".join(command)


def find_project_root(start: str | Path) -> Path:
    """Find the nearest MUSCLE project root, falling back to the start path."""
    path = Path(start).resolve()
    cursor = path if path.is_dir() else path.parent
    for candidate in [cursor, *cursor.parents]:
        if (candidate / ".muscle").exists():
            return candidate
    return cursor


def _safe_slug(command: list[str]) -> str:
    label = command_label(command) or "command"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-").lower()
    return slug[:48] or "command"


def _artifact_dir(cwd: str | Path, command: list[str]) -> Path:
    project_root = find_project_root(cwd)
    digest = hashlib.sha256(
        f"{time.time_ns()}:{command_label(command)}:{project_root}".encode()
    ).hexdigest()[:12]
    return (
        project_root
        / ".muscle"
        / "review_artifacts"
        / "command-evidence"
        / (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_safe_slug(command)}-{digest}"
        )
    )


def _write_raw(path: Path, text: str, max_chars: int) -> tuple[str | None, bool, list[str]]:
    warnings: list[str] = []
    if not text:
        return None, False, warnings
    truncated = len(text) > max_chars
    payload = text
    if truncated:
        payload = text[:max_chars] + f"\n... [raw output truncated at {max_chars} chars]"
        warnings.append(f"raw output truncated at {max_chars} chars")
    atomic_write_text(path, payload)
    return str(path), truncated, warnings


def persist_command_evidence(
    evidence: CommandEvidence,
    *,
    raw_stdout: str,
    raw_stderr: str,
    store_raw: bool,
    raw_max_chars: int = DEFAULT_RAW_ARTIFACT_MAX_CHARS,
) -> CommandEvidence:
    """Persist evidence JSON and optional raw output files under review artifacts."""
    artifact_dir = _artifact_dir(evidence.cwd, evidence.command)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    evidence.artifact_dir = str(artifact_dir)

    if store_raw:
        stdout_path, stdout_truncated, stdout_warnings = _write_raw(
            artifact_dir / "stdout.log",
            raw_stdout,
            raw_max_chars,
        )
        stderr_path, stderr_truncated, stderr_warnings = _write_raw(
            artifact_dir / "stderr.log",
            raw_stderr,
            raw_max_chars,
        )
        evidence.raw_stdout_path = stdout_path
        evidence.raw_stderr_path = stderr_path
        evidence.stdout_truncated = evidence.stdout_truncated or stdout_truncated
        evidence.stderr_truncated = evidence.stderr_truncated or stderr_truncated
        evidence.warnings.extend(stdout_warnings)
        evidence.warnings.extend(stderr_warnings)

    atomic_write_json(artifact_dir / "command-evidence.json", evidence.to_dict(), indent=2)
    return evidence


def build_command_evidence(
    *,
    command: list[str],
    cwd: str,
    exit_code: int,
    duration_ms: int,
    raw_stdout: str,
    raw_stderr: str,
    parser_tier: ParserTier | str = ParserTier.FULL,
    warnings: list[str] | None = None,
    compact_max_chars: int = DEFAULT_COMPACT_MAX_CHARS,
    force_raw_artifact: bool = False,
) -> CommandEvidence:
    """Build and persist command evidence for one command run."""
    project_root = find_project_root(cwd)
    filter_warnings: list[str] = []
    filtered_stdout = raw_stdout
    filtered_stderr = raw_stderr
    try:
        from .output_filters import apply_output_filters

        filtered_stdout, stdout_filter_warnings = apply_output_filters(
            command_label(command),
            raw_stdout,
            project_root,
        )
        filtered_stderr, stderr_filter_warnings = apply_output_filters(
            command_label(command),
            raw_stderr,
            project_root,
        )
        filter_warnings.extend(stdout_filter_warnings)
        filter_warnings.extend(stderr_filter_warnings)
    except ImportError:
        pass
    except Exception as exc:
        filter_warnings.append(f"output filter application failed: {exc}")

    compact_stdout, stdout_truncated = compact_output(filtered_stdout, compact_max_chars)
    compact_stderr, stderr_truncated = compact_output(filtered_stderr, compact_max_chars)
    raw_combined = raw_stdout + raw_stderr
    compact_combined = compact_stdout + compact_stderr
    tier_value = parser_tier.value if isinstance(parser_tier, ParserTier) else str(parser_tier)

    evidence = CommandEvidence(
        command=command,
        cwd=str(Path(cwd).resolve()),
        exit_code=exit_code,
        duration_ms=duration_ms,
        compact_stdout=compact_stdout,
        compact_stderr=compact_stderr,
        parser_tier=tier_value,
        tokens_raw_estimate=estimate_tokens(raw_combined),
        tokens_compact_estimate=estimate_tokens(compact_combined),
        warnings=[*(warnings or []), *filter_warnings],
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )

    store_raw = (
        force_raw_artifact
        or exit_code != 0
        or stdout_truncated
        or stderr_truncated
        or tier_value != ParserTier.FULL.value
    )
    try:
        return persist_command_evidence(
            evidence,
            raw_stdout=raw_stdout,
            raw_stderr=raw_stderr,
            store_raw=store_raw,
        )
    except Exception as exc:
        logger.warning("Failed to persist command evidence for %s: %s", command_label(command), exc)
        evidence.warnings.append(f"evidence persistence failed: {exc}")
        return evidence


def run_command_with_evidence(
    command: list[str],
    cwd: str,
    *,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    parser_tier: ParserTier | str = ParserTier.FULL,
    warnings: list[str] | None = None,
    compact_max_chars: int = DEFAULT_COMPACT_MAX_CHARS,
) -> tuple[int, str, str, CommandEvidence]:
    """Run a command and return its exit code, raw stdout/stderr, and evidence."""
    started = time.time()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration_ms = int((time.time() - started) * 1000)
        evidence = build_command_evidence(
            command=command,
            cwd=cwd,
            exit_code=result.returncode,
            duration_ms=duration_ms,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            parser_tier=parser_tier,
            warnings=warnings,
            compact_max_chars=compact_max_chars,
        )
        return result.returncode, result.stdout, result.stderr, evidence
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - started) * 1000)
        stderr = f"Command timed out after {timeout_seconds}s"
        evidence = build_command_evidence(
            command=command,
            cwd=cwd,
            exit_code=-1,
            duration_ms=duration_ms,
            raw_stdout="",
            raw_stderr=stderr,
            parser_tier=ParserTier.PASSTHROUGH,
            warnings=[stderr],
            force_raw_artifact=True,
        )
        return -1, "", evidence.compact_stderr, evidence
    except FileNotFoundError:
        duration_ms = int((time.time() - started) * 1000)
        stderr = f"Command not found: {command[0]}"
        evidence = build_command_evidence(
            command=command,
            cwd=cwd,
            exit_code=-2,
            duration_ms=duration_ms,
            raw_stdout="",
            raw_stderr=stderr,
            parser_tier=ParserTier.PASSTHROUGH,
            warnings=[stderr],
            force_raw_artifact=True,
        )
        return -2, "", evidence.compact_stderr, evidence
    except Exception as exc:
        duration_ms = int((time.time() - started) * 1000)
        stderr = str(exc)
        evidence = build_command_evidence(
            command=command,
            cwd=cwd,
            exit_code=-3,
            duration_ms=duration_ms,
            raw_stdout="",
            raw_stderr=stderr,
            parser_tier=ParserTier.PASSTHROUGH,
            warnings=[stderr],
            force_raw_artifact=True,
        )
        return -3, "", evidence.compact_stderr, evidence


def iter_command_evidence(project_path: str | Path, limit: int = 500) -> list[dict[str, Any]]:
    """Load recent command evidence artifacts for a project."""
    root = Path(project_path).resolve() / ".muscle" / "review_artifacts" / "command-evidence"
    if not root.exists():
        return []
    files = sorted(
        root.glob("*/command-evidence.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data.setdefault("artifact_json_path", str(path))
            rows.append(data)
        except (OSError, json.JSONDecodeError):
            logger.warning("Skipping unreadable command evidence artifact: %s", path)
    return rows
