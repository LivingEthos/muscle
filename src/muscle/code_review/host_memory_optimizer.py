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
from ..claude_publisher import (
    host_doc_lock_sentinel,
    reconcile_pending_published_revisions,
)
from ..io_safety import advisory_file_lock, atomic_write_text
from ..project_memory import ProjectMemory
from .host_memory_templates import (
    PINNED_SECTION_ORDER,
    render_pinned_block,
    resolve_host_fragment_keys,
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
        # Host-model doc fragments selected by the resolved host profile, so this
        # writer stays consistent with ClaudePublisher (both append the same
        # fragments inside the pinned region). Resolved once: deterministic for a
        # fixed host, and reused at all three render sites.
        self._fragment_keys = resolve_host_fragment_keys(self.project_path)
        self._pm = ProjectMemory(str(self.project_path))
        self._backup = BackupManager(self._pm, str(self.project_path))
        # Reconcile any revision left 'pending' by a crash between the file swap
        # and the commit-mark (check-on-next-use; no background daemon). This is
        # the same shared logic ClaudePublisher runs, so a revision staged here
        # is reconciled whichever writer constructs next, and vice versa.
        reconcile_pending_published_revisions(self._pm, str(self.project_path))

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
        # Back up first (no-op if target doesn't exist). Backup is a hard
        # precondition: if it fails we refuse to write rather than silently
        # degrading the rollback guarantee.
        try:
            if target.exists():
                self._backup.create_backup("claude_md")
        except Exception as e:  # pragma: no cover — defensive
            logger.error(f"Backup failed for {filename}: {e}")
            raise

        # Serialize the read-modify-write with the other host-doc writers
        # (ClaudePublisher) so a concurrent publish of the same file cannot
        # silently lose this update; the swap alone is atomic, the RMW is not.
        with advisory_file_lock(host_doc_lock_sentinel(self.project_path, target)):
            self._apply_locked(target)
        logger.info(f"Optimized {filename}")
        return result

    def _apply_locked(self, target: Path) -> None:
        """Two-phase publish of ``target``; the host-doc lock must be held."""
        if not target.exists():
            new_content = self._render_new_file()
        else:
            original = target.read_text()
            new_content = self._rewrite_region(original)

        # Two-phase publish, identical to ClaudePublisher.publish so both writers
        # of the authoritative marker region share the same crash-recovery
        # invariant:
        #   Phase 1: stage the new content as a 'pending' revision in the DB.
        #   Phase 2: atomic swap (temp + fsync + os.replace) so a crash mid-write
        #            never leaves the file truncated.
        #   Phase 3: mark the staged revision committed.
        # If we crash between phases 2 and 3, the next HostMemoryOptimizer /
        # ClaudePublisher init reconciles the pending row by comparing the
        # on-disk hash to the staged hash.
        revision_id = self._pm.stage_published_revision(
            project_path=str(self.project_path),
            target_path=str(target),
            content=new_content,
        )
        try:
            atomic_write_text(target, new_content)
        except Exception:
            # The swap never completed; abort the staged revision so it is not
            # later mistaken for an interrupted-but-successful swap. The file is
            # untouched (atomic_write_text replaces only on success).
            self._pm.abort_published_revision(revision_id)
            raise
        if not self._pm.commit_published_revision(revision_id):
            # A concurrent reconcile resolved this revision while the swap was in
            # flight; the file content is live, only the audit row is mis-labeled.
            logger.warning(
                f"Publish revision {revision_id} for {target.name} was no longer "
                "pending at commit time (resolved by a concurrent reconcile)."
            )

    # --- internals ---------------------------------------------------------

    def _render_new_file(self) -> str:
        """Content for a freshly-created target."""
        return f"# Host Memory\n\n{PUBLISHED_START}\n{render_pinned_block(self._fragment_keys)}{PUBLISHED_END}\n"

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
            return f"{original}{sep}\n{PUBLISHED_START}\n{render_pinned_block(self._fragment_keys)}{PUBLISHED_END}\n"

        # Markers present: extract dynamic body (anything after the pinned
        # sections, if pinned is already there) and reassemble.
        before = original[:start_idx]
        after = original[end_idx + len(PUBLISHED_END) :]

        body_start = start_idx + len(PUBLISHED_START)
        body = original[body_start:end_idx]

        dynamic_tail = self._strip_pinned_from_body(body)

        new_region = f"{PUBLISHED_START}\n{render_pinned_block(self._fragment_keys)}{dynamic_tail}{PUBLISHED_END}"
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
