"""Shadow worker crash / recovery / heartbeat tests (TEST-01).

Exercises ShadowBroker.reap_stale_jobs: when a worker stops updating its
heartbeat and then the broker's stale-job sweep runs with a staleness
threshold beyond the job's last heartbeat, the job must not be silently
stuck in the ``running`` status. The broker rewrites stale running jobs
into ``failed`` with a dedicated "orphaned" error message.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from tools.muscle.code_review.shadow_broker import ShadowBroker
from tools.muscle.code_review.types import Intensity, ReviewMode


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """Isolated project directory with a writable .muscle/ root."""
    monkeypatch.setenv("HOME", str(tmp_path))
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    return tmp_path


@pytest.fixture
def broker(tmp_project):
    return ShadowBroker(project_path=str(tmp_project))


class TestShadowWorkerHeartbeatRecovery:
    """Crash / recovery / heartbeat semantics for ShadowBroker.reap_stale_jobs."""

    def test_heartbeat_written_on_start(self, broker):
        """start_job stamps heartbeat_at (not just started_at)."""
        job_id = broker.create_job(
            "/src",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
        )
        assert broker.start_job(job_id) is True

        job = broker.get_job(job_id)
        assert job is not None
        assert job["status"] == "running"
        assert job["heartbeat_at"] is not None
        assert job["started_at"] is not None

    def test_fresh_heartbeat_is_not_reaped(self, broker):
        """A job whose heartbeat is recent must NOT be marked failed."""
        job_id = broker.create_job(
            "/src",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
        )
        broker.start_job(job_id)

        # staleness threshold far larger than the just-written heartbeat
        reaped = broker.reap_stale_jobs(max_staleness_seconds=3600.0)

        assert reaped == 0
        job = broker.get_job(job_id)
        assert job["status"] == "running"

    def test_crashed_worker_job_is_marked_failed_as_orphan(self, broker):
        """Simulate a worker that wrote an initial heartbeat then crashed.

        By patching ``datetime.now`` within project_memory to advance past
        ``orphan_timeout_seconds``, the next ``reap_stale_jobs`` sweep should
        rewrite the job to ``failed`` with the "orphaned" error message.
        """
        job_id = broker.create_job(
            "/src",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
        )
        broker.start_job(job_id)

        # Sanity: job is running with a fresh heartbeat
        job = broker.get_job(job_id)
        assert job["status"] == "running"

        # Simulate the passage of time: the project_memory module computes
        # "now" via datetime.now() when comparing heartbeat_at. Patching it
        # to return a moment in the future is equivalent to the heartbeat
        # going stale.
        future = datetime.now() + timedelta(seconds=600)

        class FakeDateTime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future

            @classmethod
            def fromtimestamp(cls, ts, tz=None):  # type: ignore[override]
                return datetime.fromtimestamp(ts, tz)

        with patch(
            "tools.muscle.code_review.shadow_broker.datetime",
            FakeDateTime,
        ), patch(
            "tools.muscle.project_memory.datetime",
            FakeDateTime,
        ):
            # Staleness threshold of 60s < 600s we advanced => job is stale
            reaped = broker.reap_stale_jobs(max_staleness_seconds=60.0)

        assert reaped == 1, "Stale running job should be reaped"
        job = broker.get_job(job_id)
        assert job is not None
        # Verify the job is NOT silently stuck in running
        assert job["status"] != "running"
        assert job["status"] == "failed"
        # Dedicated "orphaned" error message (see project_memory.py:3591)
        assert "orphaned" in (job.get("error_message") or "").lower()

    def test_reap_only_affects_running_jobs(self, broker):
        """Pending/completed/cancelled jobs are never touched by the sweep."""
        pending_id = broker.create_job("/a", ReviewMode.REVIEW, Intensity.MODERATE)
        completed_id = broker.create_job("/b", ReviewMode.REVIEW, Intensity.MODERATE)
        running_id = broker.create_job("/c", ReviewMode.REVIEW, Intensity.MODERATE)

        broker.start_job(completed_id)
        broker.complete_job(completed_id, result={"ok": True})
        broker.start_job(running_id)

        future = datetime.now() + timedelta(seconds=600)

        class FakeDateTime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return future

            @classmethod
            def fromtimestamp(cls, ts, tz=None):  # type: ignore[override]
                return datetime.fromtimestamp(ts, tz)

        with patch(
            "tools.muscle.code_review.shadow_broker.datetime",
            FakeDateTime,
        ), patch(
            "tools.muscle.project_memory.datetime",
            FakeDateTime,
        ):
            reaped = broker.reap_stale_jobs(max_staleness_seconds=60.0)

        # Only the running job is reaped
        assert reaped == 1
        assert broker.get_job(pending_id)["status"] == "pending"
        assert broker.get_job(completed_id)["status"] == "completed"
        assert broker.get_job(running_id)["status"] == "failed"

    def test_heartbeat_refresh_prevents_orphan_marking(self, broker):
        """A worker that keeps heartbeating survives the sweep."""
        job_id = broker.create_job(
            "/src",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
        )
        broker.start_job(job_id)

        # The worker sends a fresh heartbeat "now" — so a sweep with a short
        # staleness window should not touch it.
        assert broker.heartbeat_job(job_id) is True

        reaped = broker.reap_stale_jobs(max_staleness_seconds=60.0)
        assert reaped == 0
        assert broker.get_job(job_id)["status"] == "running"
