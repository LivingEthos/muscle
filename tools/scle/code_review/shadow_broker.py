"""
Shadow Jobs - Background review job tracking.

Manages asynchronous review jobs that run in shadow mode,
with probe/status and diagnosis/result retrieval.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import Intensity, ReviewMode

SHADOW_JOBS_FILE = Path.home() / ".scle" / "shadow_jobs.json"


class ShadowBroker:
    _instance = None
    _lock = Lock()

    _initialized: bool = False

    def __new__(cls) -> ShadowBroker:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if ShadowBroker._initialized:
            return
        ShadowBroker._initialized = True
        self._jobs: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if SHADOW_JOBS_FILE.exists():
            try:
                self._jobs = json.loads(SHADOW_JOBS_FILE.read_text())
            except Exception:
                self._jobs = {}

    def _save(self) -> None:
        SHADOW_JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SHADOW_JOBS_FILE.write_text(json.dumps(self._jobs, indent=2))

    def create_job(
        self,
        target_path: str,
        mode: ReviewMode,
        intensity: Intensity,
    ) -> str:
        job_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        self._jobs[job_id] = {
            "job_id": job_id,
            "target_path": target_path,
            "mode": mode.value,
            "intensity": intensity.value,
            "status": "pending",
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error_message": None,
        }
        self._save()
        return job_id

    def start_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        self._jobs[job_id]["status"] = "running"
        self._jobs[job_id]["started_at"] = datetime.now().isoformat()
        self._save()
        return True

    def complete_job(self, job_id: str, result: dict | None = None) -> bool:
        if job_id not in self._jobs:
            return False
        self._jobs[job_id]["status"] = "completed"
        self._jobs[job_id]["completed_at"] = datetime.now().isoformat()
        if result:
            self._jobs[job_id]["result"] = result
        self._save()
        return True

    def fail_job(self, job_id: str, error: str) -> bool:
        if job_id not in self._jobs:
            return False
        self._jobs[job_id]["status"] = "failed"
        self._jobs[job_id]["error_message"] = error
        self._jobs[job_id]["completed_at"] = datetime.now().isoformat()
        self._save()
        return True

    def cancel_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        self._jobs[job_id]["status"] = "cancelled"
        self._jobs[job_id]["completed_at"] = datetime.now().isoformat()
        self._save()
        return True

    def get_job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def get_all_jobs(self) -> list[dict]:
        return list(self._jobs.values())

    def get_active_jobs(self) -> list[dict]:
        return [j for j in self._jobs.values() if j["status"] in ("pending", "running")]

    def get_pending_jobs(self) -> list[dict]:
        return [j for j in self._jobs.values() if j["status"] == "pending"]

    def get_recent_jobs(self, limit: int = 10) -> list[dict]:
        sorted_jobs = sorted(
            self._jobs.values(), key=lambda x: x.get("created_at", ""), reverse=True
        )
        return sorted_jobs[:limit]

    def remove_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False

    def clear_completed(self) -> int:
        to_remove = [
            jid
            for jid, j in self._jobs.items()
            if j["status"] in ("completed", "failed", "cancelled")
        ]
        for jid in to_remove:
            del self._jobs[jid]
        self._save()
        return len(to_remove)
