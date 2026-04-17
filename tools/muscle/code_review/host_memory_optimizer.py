"""Non-destructive optimizer for host-model memory files (CLAUDE.md, AGENTS.md).

Contract:
- User content OUTSIDE MUSCLE_PUBLISHED_START/END markers is never touched.
- If markers are absent, append them at end-of-file and inject the pinned block.
- Inside markers: pinned sections (Methodology, Delegation Protocol, Effort)
  are written in canonical order, followed by existing MUSCLE dynamic sections.
- Pure and deterministic: no M2.7 calls here. Reserved for claude_publisher
  consolidation when size caps fire.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from pathlib import Path

from ..backup_manager import BackupManager
from ..project_memory import ProjectMemory
from .host_memory_templates import (
    PINNED_SECTION_ORDER,
    render_pinned_block,
)

logger = logging.getLogger(__name__)

PUBLISHED_START = "<!-- MUSCLE_PUBLISHED_START -->"
PUBLISHED_END = "<!-- MUSCLE_PUBLISHED_END -->"

DEFAULT_TARGETS: tuple[str, ...] = ("CLAUDE.md", "AGENTS.md")


@dataclass
class OptimizeResult:
    """Result of optimizing a single target file."""

    filename: str
    changed: bool
    diff: str  # unified diff (empty string if changed=False)
    reason: str  # human-readable summary


class HostMemoryOptimizer:
    """Non-destructive rewriter for root CLAUDE.md / AGENTS.md."""

    def __init__(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path)
        self._pm = ProjectMemory(str(self.project_path))
        self._backup = BackupManager(self._pm, str(self.project_path))

    def plan(self, filename: str) -> OptimizeResult:
        """Return what the optimizer WOULD do for this file, without writing."""
        target = self.project_path / filename
        if not target.exists():
            # Missing file: plan = create with just the pinned block + empty
            # marker structure. User content outside markers is trivially
            # preserved (there is none).
            new_content = self._render_new_file()
            return OptimizeResult(
                filename=filename,
                changed=True,
                diff=self._diff("", new_content, filename),
                reason=f"{filename} absent; would create with pinned block",
            )

        original = target.read_text()
        new_content = self._rewrite_region(original)
        if new_content == original:
            return OptimizeResult(
                filename=filename,
                changed=False,
                diff="",
                reason=f"{filename} already optimal",
            )
        return OptimizeResult(
            filename=filename,
            changed=True,
            diff=self._diff(original, new_content, filename),
            reason=f"{filename} would be updated inside MUSCLE_PUBLISHED markers",
        )

    def apply(self, filename: str) -> OptimizeResult:
        """Back up and apply the plan. Caller is responsible for confirmation."""
        result = self.plan(filename)
        if not result.changed:
            return result

        target = self.project_path / filename
        # Back up first (no-op if target doesn't exist).
        try:
            if target.exists():
                self._backup.create_backup("claude_md")
        except Exception as e:  # pragma: no cover — defensive
            logger.error(f"Backup failed for {filename}: {e}")
            raise

        if not target.exists():
            target.write_text(self._render_new_file())
        else:
            original = target.read_text()
            target.write_text(self._rewrite_region(original))
        logger.info(f"Optimized {filename}")
        return result

    # --- internals ---------------------------------------------------------

    def _render_new_file(self) -> str:
        """Content for a freshly-created target."""
        return (
            f"# Host Memory\n\n"
            f"{PUBLISHED_START}\n"
            f"{render_pinned_block()}"
            f"{PUBLISHED_END}\n"
        )

    def _rewrite_region(self, original: str) -> str:
        """Rewrite only the region inside PUBLISHED_START/END.

        If markers are absent, append them at end of file.
        User content outside markers is byte-preserved.
        """
        start_idx = original.find(PUBLISHED_START)
        end_idx = original.find(PUBLISHED_END)

        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            # No markers: append a new managed region at end of file.
            sep = "" if original.endswith("\n") else "\n"
            return (
                f"{original}{sep}\n"
                f"{PUBLISHED_START}\n"
                f"{render_pinned_block()}"
                f"{PUBLISHED_END}\n"
            )

        # Markers present: extract dynamic body (anything after the pinned
        # sections, if pinned is already there) and reassemble.
        before = original[:start_idx]
        after = original[end_idx + len(PUBLISHED_END):]

        body_start = start_idx + len(PUBLISHED_START)
        body = original[body_start:end_idx]

        dynamic_tail = self._strip_pinned_from_body(body)

        new_region = (
            f"{PUBLISHED_START}\n"
            f"{render_pinned_block()}"
            f"{dynamic_tail}"
            f"{PUBLISHED_END}"
        )
        return f"{before}{new_region}{after}"

    def _strip_pinned_from_body(self, body: str) -> str:
        """Remove any existing pinned-section headings + their content from
        the managed body so we can replace them cleanly with the canonical
        PINNED_TEMPLATE. Dynamic sections (everything after the last pinned
        heading, or everything if no pinned headings) is preserved verbatim.
        """
        lines = body.splitlines(keepends=True)
        keep_from = 0
        for i, line in enumerate(lines):
            stripped = line.rstrip("\n").rstrip()
            if stripped.startswith("### ") and stripped not in PINNED_SECTION_ORDER:
                keep_from = i
                break
        else:
            # No non-pinned sections found: body is pinned-only or empty.
            return ""
        return "".join(lines[keep_from:])

    @staticmethod
    def _diff(original: str, new: str, filename: str) -> str:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
            )
        )


def run_optimizer(
    project_path: str | Path,
    only: str | None = None,
    skip_agents: bool = False,
    dry_run: bool = False,
) -> list[OptimizeResult]:
    """High-level entry point used by the CLI."""
    targets: list[str]
    if only:
        targets = [only]
    elif skip_agents:
        targets = ["CLAUDE.md"]
    else:
        targets = list(DEFAULT_TARGETS)

    opt = HostMemoryOptimizer(project_path)
    results: list[OptimizeResult] = []
    for t in targets:
        results.append(opt.plan(t) if dry_run else opt.apply(t))
    return results
