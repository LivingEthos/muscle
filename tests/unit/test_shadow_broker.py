"""
Unit tests for shadow_broker.py (project-local, W3-A).
"""

from __future__ import annotations

import json

import pytest

from tools.muscle.code_review.shadow_broker import ShadowBroker
from tools.muscle.code_review.types import Intensity, ReviewMode


@pytest.fixture
def tmp_project(tmp_path):
    """A fake project directory with .muscle/ created."""
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    return tmp_path


@pytest.fixture
def broker(tmp_project):
    """ShadowBroker bound to a temp project."""
    return ShadowBroker(project_path=str(tmp_project))


class TestCreateJob:
    def test_creates_job_with_correct_structure(self, broker):
        job_id = broker.create_job(
            "/path/to/target",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
        )

        assert job_id is not None
        assert len(job_id) == 8

        job = broker.get_job(job_id)
        assert job is not None
        assert job["job_id"] == job_id
        assert job["target_path"] == "/path/to/target"
        assert job["mode"] == "review"
        assert job["intensity"] == "moderate"
        assert job["status"] == "pending"
        assert job["created_at"] is not None
        assert job["started_at"] is None
        assert job["completed_at"] is None
        assert job["result"] is None
        assert job["error_message"] is None
        assert job["timeout_seconds"] == 300

    def test_multiple_jobs_get_unique_ids(self, broker):
        ids = set()
        for _ in range(5):
            jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
            ids.add(jid)
        assert len(ids) == 5

    def test_job_stored_in_project_memory_db(self, broker, tmp_project):
        broker.create_job("/target", ReviewMode.REVIEW, Intensity.INTENSIVE)
        db_path = tmp_project / ".muscle" / "project_memory.db"
        assert db_path.exists()

    def test_create_job_with_changed_files(self, broker):
        changed = ["src/foo.py", "src/bar.py"]
        job_id = broker.create_job(
            "/target",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
            changed_files=changed,
        )
        job = broker.get_job(job_id)
        assert job["changed_files_json"] is not None
        assert json.loads(job["changed_files_json"]) == changed

    def test_create_job_with_timeout_and_budget(self, broker):
        job_id = broker.create_job(
            "/target",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
            timeout_seconds=600,
            token_budget=50000,
        )
        job = broker.get_job(job_id)
        assert job["timeout_seconds"] == 600
        assert job["token_budget"] == 50000

    def test_create_job_with_execution_mode(self, broker):
        job_id = broker.create_job(
            "/target",
            ReviewMode.AUTO_FIX,
            Intensity.MODERATE,
            execution_mode="worktree",
        )
        job = broker.get_job(job_id)
        assert job is not None
        assert job["execution_mode"] == "worktree"


class TestProjectIsolation:
    """Multiple projects must not share job state."""

    def test_jobs_are_project_scoped(self, tmp_path):
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()

        broker_a = ShadowBroker(project_path=str(proj_a))
        broker_b = ShadowBroker(project_path=str(proj_b))

        jid_a = broker_a.create_job("/target_a", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid_b = broker_b.create_job("/target_b", ReviewMode.REVIEW, Intensity.MINIMAL)

        # Each project's broker only sees its own jobs
        assert broker_a.get_job(jid_a) is not None
        assert broker_a.get_job(jid_b) is None
        assert broker_b.get_job(jid_b) is not None
        assert broker_b.get_job(jid_a) is None

    def test_get_all_jobs_is_project_scoped(self, tmp_path):
        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()

        broker_a = ShadowBroker(project_path=str(proj_a))
        broker_b = ShadowBroker(project_path=str(proj_b))

        for _ in range(3):
            broker_a.create_job("/target_a", ReviewMode.REVIEW, Intensity.MINIMAL)
        for _ in range(2):
            broker_b.create_job("/target_b", ReviewMode.REVIEW, Intensity.MINIMAL)

        assert len(broker_a.get_all_jobs()) == 3
        assert len(broker_b.get_all_jobs()) == 2


class TestStartJob:
    def test_start_pending_job(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        result = broker.start_job(job_id)
        assert result is True

        job = broker.get_job(job_id)
        assert job["status"] == "running"
        assert job["started_at"] is not None

    def test_start_nonexistent_job_returns_false(self, broker):
        result = broker.start_job("nonexistent-id")
        assert result is False


class TestCompleteJob:
    def test_complete_job_sets_status_and_result(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        result_data = {"issues": [{"severity": "HIGH", "title": "test issue"}]}
        result = broker.complete_job(job_id, result_data)

        assert result is True
        job = broker.get_job(job_id)
        assert job["status"] == "completed"
        assert job["completed_at"] is not None
        assert job["result"] is not None

    def test_complete_job_without_result(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        result = broker.complete_job(job_id)
        assert result is True

        job = broker.get_job(job_id)
        assert job["status"] == "completed"
        assert job["result"] is None

    def test_complete_nonexistent_job_returns_false(self, broker):
        result = broker.complete_job("nonexistent-id", {})
        assert result is False


class TestFailJob:
    def test_fail_job_sets_status_and_error(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        result = broker.fail_job(job_id, "Something went wrong")
        assert result is True

        job = broker.get_job(job_id)
        assert job["status"] == "failed"
        assert job["error_message"] == "Something went wrong"
        assert job["completed_at"] is not None

    def test_fail_nonexistent_job_returns_false(self, broker):
        result = broker.fail_job("nonexistent-id", "error")
        assert result is False


class TestCancelJob:
    def test_cancel_job(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        result = broker.cancel_job(job_id)
        assert result is True

        job = broker.get_job(job_id)
        assert job["status"] == "cancelled"
        assert job["completed_at"] is not None

    def test_cancel_nonexistent_job_returns_false(self, broker):
        result = broker.cancel_job("nonexistent-id")
        assert result is False


class TestGetJob:
    def test_get_existing_job(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
        job = broker.get_job(job_id)
        assert job is not None
        assert job["job_id"] == job_id

    def test_get_nonexistent_job(self, broker):
        job = broker.get_job("does-not-exist")
        assert job is None


class TestGetAllJobs:
    def test_returns_all_jobs(self, broker):
        broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
        broker.create_job("/target2", ReviewMode.REVIEW, Intensity.INTENSIVE)
        all_jobs = broker.get_all_jobs()
        assert len(all_jobs) == 2

    def test_empty_when_no_jobs(self, broker):
        all_jobs = broker.get_all_jobs()
        assert all_jobs == []


class TestGetActiveJobs:
    def test_returns_only_active_jobs(self, broker):
        jid1 = broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)

        broker.start_job(jid1)
        broker.complete_job(jid2)

        active = broker.get_active_jobs()
        assert len(active) == 1
        assert active[0]["job_id"] == jid1

    def test_empty_when_none_active(self, broker):
        jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
        broker.complete_job(jid)
        active = broker.get_active_jobs()
        assert active == []


class TestGetPendingJobs:
    def test_returns_only_pending_jobs(self, broker):
        jid1 = broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)
        broker.start_job(jid1)

        pending = broker.get_pending_jobs()
        assert len(pending) == 1
        assert pending[0]["job_id"] == jid2


class TestGetRecentJobs:
    def test_returns_jobs_sorted_by_created_at(self, broker):
        broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)

        recent = broker.get_recent_jobs(limit=1)
        assert len(recent) == 1
        assert recent[0]["job_id"] == jid2

    def test_respects_limit(self, broker):
        for i in range(5):
            broker.create_job(f"/target{i}", ReviewMode.REVIEW, Intensity.MINIMAL)

        recent = broker.get_recent_jobs(limit=3)
        assert len(recent) == 3


class TestRemoveJob:
    def test_remove_existing_job(self, broker):
        jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        result = broker.remove_job(jid)
        assert result is True
        assert broker.get_job(jid) is None

    def test_remove_nonexistent_job(self, broker):
        result = broker.remove_job("nonexistent-id")
        assert result is False


class TestClearCompleted:
    def test_clears_completed_jobs(self, broker):
        jid1 = broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid3 = broker.create_job("/target3", ReviewMode.REVIEW, Intensity.MINIMAL)

        broker.complete_job(jid1)
        broker.fail_job(jid2, "test error")

        cleared = broker.clear_completed()
        assert cleared == 2
        remaining = broker.get_all_jobs()
        assert len(remaining) == 1
        assert remaining[0]["job_id"] == jid3

    def test_clears_cancelled_jobs(self, broker):
        jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
        broker.cancel_job(jid)

        cleared = broker.clear_completed()
        assert cleared == 1
        assert broker.get_all_jobs() == []

    def test_returns_zero_when_nothing_to_clear(self, broker):
        broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        cleared = broker.clear_completed()
        assert cleared == 0


class TestGetChangedFiles:
    def test_returns_changed_files_list(self, broker):
        changed = ["src/a.py", "src/b.py"]
        job_id = broker.create_job(
            "/target", ReviewMode.REVIEW, Intensity.MINIMAL, changed_files=changed
        )
        assert broker.get_changed_files(job_id) == changed

    def test_returns_none_when_not_set(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
        assert broker.get_changed_files(job_id) is None

    def test_returns_none_for_unknown_job(self, broker):
        assert broker.get_changed_files("unknown") is None


class TestGetJobTimeout:
    def test_returns_timeout_seconds(self, broker):
        job_id = broker.create_job(
            "/target", ReviewMode.REVIEW, Intensity.MINIMAL, timeout_seconds=600
        )
        assert broker.get_job_timeout(job_id) == 600

    def test_returns_none_for_unknown_job(self, broker):
        assert broker.get_job_timeout("unknown") is None


class TestGetJobTokenBudget:
    def test_returns_token_budget(self, broker):
        job_id = broker.create_job(
            "/target", ReviewMode.REVIEW, Intensity.MINIMAL, token_budget=50000
        )
        assert broker.get_job_token_budget(job_id) == 50000

    def test_returns_none_when_not_set(self, broker):
        job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
        assert broker.get_job_token_budget(job_id) is None
