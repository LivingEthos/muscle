"""
Unit tests for shadow_broker.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.muscle.code_review.shadow_broker import ShadowBroker
from tools.muscle.code_review.types import Intensity, ReviewMode


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset ShadowBroker singleton between tests."""
    ShadowBroker._instance = None
    ShadowBroker._initialized = False
    yield
    ShadowBroker._instance = None
    ShadowBroker._initialized = False


@pytest.fixture
def tmp_jobs_file(tmp_path):
    """Use a temp file for SHADOW_JOBS_FILE."""
    return tmp_path / "shadow_jobs.json"


class TestSingletonEnforcement:
    def test_second_instantiation_returns_same_instance(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker1 = ShadowBroker()
            broker2 = ShadowBroker()
            assert broker1 is broker2


class TestCreateJob:
    def test_creates_job_with_correct_structure(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/path/to/target", ReviewMode.REVIEW, Intensity.MODERATE)

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

    def test_multiple_jobs_get_unique_ids(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            ids = set()
            for _ in range(5):
                jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
                ids.add(jid)
            assert len(ids) == 5

    def test_job_persisted_to_file(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.INTENSIVE)
            assert tmp_jobs_file.exists()
            data = json.loads(tmp_jobs_file.read_text())
            assert job_id in data


class TestStartJob:
    def test_start_pending_job(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            result = broker.start_job(job_id)
            assert result is True

            job = broker.get_job(job_id)
            assert job["status"] == "running"
            assert job["started_at"] is not None

    def test_start_nonexistent_job_returns_false(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            result = broker.start_job("nonexistent-id")
            assert result is False


class TestCompleteJob:
    def test_complete_job_sets_status_and_result(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            result_data = {"issues": [{"severity": "HIGH", "title": "test issue"}]}
            result = broker.complete_job(job_id, result_data)

            assert result is True
            job = broker.get_job(job_id)
            assert job["status"] == "completed"
            assert job["completed_at"] is not None
            assert job["result"] == result_data

    def test_complete_job_without_result(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            result = broker.complete_job(job_id)
            assert result is True

            job = broker.get_job(job_id)
            assert job["status"] == "completed"
            assert job["result"] is None

    def test_complete_nonexistent_job_returns_false(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            result = broker.complete_job("nonexistent-id", {})
            assert result is False


class TestFailJob:
    def test_fail_job_sets_status_and_error(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            result = broker.fail_job(job_id, "Something went wrong")
            assert result is True

            job = broker.get_job(job_id)
            assert job["status"] == "failed"
            assert job["error_message"] == "Something went wrong"
            assert job["completed_at"] is not None

    def test_fail_nonexistent_job_returns_false(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            result = broker.fail_job("nonexistent-id", "error")
            assert result is False


class TestCancelJob:
    def test_cancel_job(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            result = broker.cancel_job(job_id)
            assert result is True

            job = broker.get_job(job_id)
            assert job["status"] == "cancelled"
            assert job["completed_at"] is not None

    def test_cancel_nonexistent_job_returns_false(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            result = broker.cancel_job("nonexistent-id")
            assert result is False


class TestGetJob:
    def test_get_existing_job(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job_id = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
            job = broker.get_job(job_id)
            assert job is not None
            assert job["job_id"] == job_id

    def test_get_nonexistent_job(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job = broker.get_job("does-not-exist")
            assert job is None


class TestGetAllJobs:
    def test_returns_all_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
            broker.create_job("/target2", ReviewMode.REVIEW, Intensity.INTENSIVE)
            all_jobs = broker.get_all_jobs()
            assert len(all_jobs) == 2

    def test_empty_when_no_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            all_jobs = broker.get_all_jobs()
            assert all_jobs == []


class TestGetActiveJobs:
    def test_returns_only_active_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid1 = broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
            jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)

            broker.start_job(jid1)
            broker.complete_job(jid2)

            active = broker.get_active_jobs()
            assert len(active) == 1
            assert active[0]["job_id"] == jid1

    def test_empty_when_none_active(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
            broker.complete_job(jid)
            active = broker.get_active_jobs()
            assert active == []


class TestGetPendingJobs:
    def test_returns_only_pending_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid1 = broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
            jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)
            broker.start_job(jid1)

            pending = broker.get_pending_jobs()
            assert len(pending) == 1
            assert pending[0]["job_id"] == jid2


class TestGetRecentJobs:
    def test_returns_jobs_sorted_by_created_at(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid1 = broker.create_job("/target1", ReviewMode.REVIEW, Intensity.MINIMAL)
            jid2 = broker.create_job("/target2", ReviewMode.REVIEW, Intensity.MINIMAL)

            recent = broker.get_recent_jobs(limit=1)
            assert len(recent) == 1
            assert recent[0]["job_id"] == jid2

    def test_respects_limit(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            for i in range(5):
                broker.create_job(f"/target{i}", ReviewMode.REVIEW, Intensity.MINIMAL)

            recent = broker.get_recent_jobs(limit=3)
            assert len(recent) == 3

    def test_empty_when_no_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            recent = broker.get_recent_jobs()
            assert recent == []


class TestRemoveJob:
    def test_remove_existing_job(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            result = broker.remove_job(jid)
            assert result is True
            assert broker.get_job(jid) is None

    def test_remove_nonexistent_job(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            result = broker.remove_job("nonexistent-id")
            assert result is False


class TestClearCompleted:
    def test_clears_completed_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
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

    def test_clears_cancelled_jobs(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
            broker.cancel_job(jid)

            cleared = broker.clear_completed()
            assert cleared == 1
            assert broker.get_all_jobs() == []

    def test_returns_zero_when_nothing_to_clear(self, tmp_jobs_file):
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            jid = broker.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

            cleared = broker.clear_completed()
            assert cleared == 0


class TestLoad:
    def test_loads_from_existing_file(self, tmp_jobs_file):
        data = {
            "test-id": {
                "job_id": "test-id",
                "target_path": "/target",
                "mode": "review",
                "intensity": "medium",
                "status": "completed",
                "created_at": "2024-01-01T00:00:00",
                "started_at": "2024-01-01T00:00:01",
                "completed_at": "2024-01-01T00:00:05",
                "result": {"issues": []},
                "error_message": None,
            }
        }
        tmp_jobs_file.write_text(json.dumps(data))

        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            job = broker.get_job("test-id")
            assert job is not None
            assert job["status"] == "completed"

    def test_load_corrupted_json_returns_empty_dict(self, tmp_jobs_file):
        tmp_jobs_file.write_text("not valid json{{{")
        with patch("tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE", tmp_jobs_file):
            broker = ShadowBroker()
            assert broker.get_all_jobs() == []
