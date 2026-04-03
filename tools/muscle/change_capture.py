"""
ChangeCapture - Record diffs and changed files as learning evidence (MUS-021).

Captures git diff summaries and changed file lists after reviews, storing them
in the project_memory.db change_events table and linking to review_run_id.
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.git_adapter import GitAdapter
from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)


@dataclass
class ChangeEvent:
    """A recorded change event with file list and diff summary."""

    changed_files: list[str]
    diff_summary: str  # Compact: "file.py +5 -3 | file2.py +10"
    timestamp: str
    review_run_id: int | None = None


class ChangeCapture:
    """
    Captures git diffs and changed files as learning evidence.

    Handles non-git projects gracefully (returns empty list, no errors).
    """

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self._git_adapter: GitAdapter | None = None  # Lazy import

    @property
    def git_adapter(self) -> GitAdapter:
        """Lazy-load git adapter to avoid import overhead for non-git projects."""
        if self._git_adapter is None:
            self._git_adapter = GitAdapter(str(self.project_path))
        return self._git_adapter

    def is_git_project(self) -> bool:
        """Check if project is a git repository."""
        try:
            return self.git_adapter.is_git_repo()
        except Exception:
            return False

    def collect_changed_files(self) -> list[str]:
        """
        Get list of changed files from git status.

        Returns empty list for non-git projects or projects with no changes.
        """
        if not self.is_git_project():
            return []
        try:
            return self.git_adapter.get_changed_files()
        except Exception as e:
            logger.debug(f"Could not get changed files: {e}")
            return []

    def collect_diff_summary(self) -> str:
        """
        Get compact diff summary (file names + change stats), not full diffs.

        Format: "file.py +5 -3 | file2.py +10"
        Returns empty string for non-git projects or no changes.
        """
        if not self.is_git_project():
            return ""

        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "--compact-summary"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return ""

            # Parse stat output into compact format
            lines = result.stdout.strip().splitlines()
            if not lines:
                return ""

            # Last line is the summary line like "3 files changed, 15 insertions(+), 5 deletions(-)"
            # We want the per-file lines
            summary_parts = []
            for line in lines:
                # Skip the summary line at the end
                if "files changed" in line or "insertion" in line or "deletion" in line:
                    continue
                # Format: " file.py | 5 +++ --- "
                if " | " in line:
                    file_part = line.split(" | ")[0].strip()
                    stats_part = line.split(" | ")[1].strip()
                    summary_parts.append(f"{file_part} {stats_part}")

            return " | ".join(summary_parts) if summary_parts else ""

        except Exception as e:
            logger.debug(f"Could not get diff summary: {e}")
            return ""

    def store_change_events(
        self,
        project_memory: ProjectMemory,
        review_run_id: int | None = None,
    ) -> list[int]:
        """
        Write change events to project_memory.db.

        Args:
            project_memory: ProjectMemory instance for DB access.
            review_run_id: Optional review_run_id to link changes to a review.

        Returns:
            List of inserted change_event IDs.
        """
        changed_files = self.collect_changed_files()
        diff_summary = self.collect_diff_summary()

        if not changed_files and not diff_summary:
            # No changes to record
            return []

        event_ids = []
        try:
            event_id = project_memory.insert_change_event(
                project_path=str(self.project_path),
                changed_files_json=json.dumps(changed_files),
                diff_summary=diff_summary if diff_summary else None,
                review_run_id=review_run_id,
            )
            if event_id:
                event_ids.append(event_id)
        except Exception as e:
            logger.warning(f"Failed to store change event: {e}")

        return event_ids

    def capture_and_store(
        self,
        project_memory: ProjectMemory,
        review_run_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Convenience method: capture and store in one call.

        Returns dict with keys: event_ids, changed_files_count, diff_summary.
        """
        changed_files = self.collect_changed_files()
        diff_summary = self.collect_diff_summary()

        event_ids = self.store_change_events(project_memory, review_run_id)

        return {
            "event_ids": event_ids,
            "changed_files_count": len(changed_files),
            "diff_summary": diff_summary,
            "changed_files": changed_files,
        }
