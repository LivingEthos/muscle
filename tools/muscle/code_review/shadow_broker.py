"""
Shadow Jobs - Background review job tracking (project-local, W3-A).

Manages asynchronous review jobs that run in shadow mode,
with probe/status and diagnosis/result retrieval.

All state is stored in project_memory.db so each project has
isolated job tracking with no global shared state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..project_memory import ProjectMemory

if TYPE_CHECKING:
    from .types import Intensity, ReviewMode


class ShadowBroker:
    """
    Project-local shadow job broker.

    Uses ProjectMemory (SQLite) instead of a global JSON file so multiple
    projects do not share confusing job state.

    Instance-per-project: create one ShadowBroker per project_path.
    """

    def __init__(
        self,
        project_path: str,
        db_path: str | None = None,
    ) -> None:
        """
        Initialize ShadowBroker for a project.

        Args:
            project_path: Absolute path to the project root. Used to scope all job
                records and to locate the project_memory.db.
            db_path: Optional path to the project_memory.db. Defaults to
                <project_path>/.muscle/project_memory.db.
        """
        self._project_path = Path(project_path).resolve()
        self._memory = ProjectMemory(str(self._project_path), db_path)

    @property
    def project_path(self) -> str:
        return str(self._project_path)

    def create_job(
        self,
        target_path: str,
        mode: ReviewMode,
        intensity: Intensity,
        changed_files: list[str] | None = None,
        timeout_seconds: int = 300,
        token_budget: int | None = None,
    ) -> str:
        """
        Create a new shadow job.

        Args:
            target_path: Path that will be reviewed.
            mode: Review mode (review, auto_fix, plan, hybrid, pressure).
            intensity: Review intensity.
            changed_files: Optional list of files that changed (for changed-files-first
                background scope).
            timeout_seconds: Maximum time for the job before it is cancelled.
                Defaults to 300 seconds (5 minutes).
            token_budget: Optional token budget cap for this job.

        Returns:
            The job_id (8-character hex string).
        """
        import json

        job_id = str(uuid.uuid4())[:8]
        changed_files_json = json.dumps(changed_files) if changed_files else None

        self._memory.insert_shadow_job(
            project_path=self.project_path,
            job_id=job_id,
            target_path=target_path,
            mode=mode.value,
            intensity=intensity.value,
            changed_files_json=changed_files_json,
            timeout_seconds=timeout_seconds,
            token_budget=token_budget,
        )
        return job_id

    def start_job(self, job_id: str) -> bool:
        """Mark a job as running. Returns False if job not found."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return False
        self._memory.update_shadow_job_status(
            job_id,
            status="running",
            started_at=datetime.now().isoformat(),
        )
        return True

    def complete_job(self, job_id: str, result: dict | None = None) -> bool:
        """Mark a job as completed with optional result data. Returns False if not found."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return False
        import json

        result_json = json.dumps(result) if result else None
        self._memory.update_shadow_job_status(
            job_id,
            status="completed",
            completed_at=datetime.now().isoformat(),
            result=result_json,
        )
        return True

    def fail_job(self, job_id: str, error: str) -> bool:
        """Mark a job as failed with an error message. Returns False if not found."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return False
        self._memory.update_shadow_job_status(
            job_id,
            status="failed",
            completed_at=datetime.now().isoformat(),
            error_message=error,
        )
        return True

    def cancel_job(self, job_id: str) -> bool:
        """Mark a job as cancelled. Returns False if not found."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return False
        self._memory.update_shadow_job_status(
            job_id,
            status="cancelled",
            completed_at=datetime.now().isoformat(),
        )
        return True

    def get_job(self, job_id: str) -> dict | None:
        """Return the full job record, or None if not found."""
        return self._memory.get_shadow_job(job_id)

    def get_all_jobs(self, limit: int = 100) -> list[dict]:
        """Return all jobs for this project."""
        return self._memory.list_shadow_jobs(project_path=self.project_path, limit=limit)

    def get_active_jobs(self) -> list[dict]:
        """Return all pending/running jobs for this project."""
        return self._memory.get_active_shadow_jobs(self.project_path)

    def get_pending_jobs(self) -> list[dict]:
        """Return all pending jobs for this project."""
        return self._memory.get_pending_shadow_jobs(self.project_path)

    def get_recent_jobs(self, limit: int = 10) -> list[dict]:
        """Return the most recent jobs for this project."""
        return self._memory.list_shadow_jobs(project_path=self.project_path, limit=limit)

    def remove_job(self, job_id: str) -> bool:
        """Delete a job. Returns False if not found."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return False
        return self._memory.remove_shadow_job(job_id)

    def clear_completed(self) -> int:
        """Delete all completed/failed/cancelled jobs for this project. Returns count deleted."""
        return self._memory.clear_completed_shadow_jobs(self.project_path)

    def get_changed_files(self, job_id: str) -> list[str] | None:
        """Return the changed files list for a job, or None."""
        import json

        job = self._memory.get_shadow_job(job_id)
        if not job:
            return None
        changed = job.get("changed_files_json")
        if not changed:
            return None
        try:
            parsed = json.loads(changed)
            if isinstance(parsed, list):
                return list(parsed)
            return None
        except Exception:
            return None

    def get_job_timeout(self, job_id: str) -> int | None:
        """Return the timeout in seconds for a job, or None."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return None
        return job.get("timeout_seconds")

    def get_job_token_budget(self, job_id: str) -> int | None:
        """Return the token budget for a job, or None."""
        job = self._memory.get_shadow_job(job_id)
        if not job:
            return None
        return job.get("token_budget")
