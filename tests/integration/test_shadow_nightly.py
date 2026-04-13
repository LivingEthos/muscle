"""
Integration tests for shadow mode and long evaluation runner.

Tests ShadowBroker -> ShadowWorker job lifecycle and
LongEvalRunner report generation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.muscle.code_review.types import Intensity, ReviewMode


class TestShadowBrokerLifecycle:
    """Tests shadow job creation, status tracking, and completion."""

    def test_create_and_complete_job(self, tmp_path: Path):
        """Job should transition: pending -> running -> completed."""
        from tools.muscle.code_review.shadow_broker import ShadowBroker

        # Reset singleton for test isolation
        ShadowBroker._instance = None
        ShadowBroker._initialized = False

        with patch(
            "tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE",
            tmp_path / "shadow_jobs.json",
        ):
            broker = ShadowBroker.__new__(ShadowBroker)
            ShadowBroker._instance = broker
            ShadowBroker._initialized = False
            broker.__init__()

            job_id = broker.create_job(
                target_path="/tmp/project",
                mode=ReviewMode.REVIEW,
                intensity=Intensity.MODERATE,
            )

            assert job_id
            job = broker.get_job(job_id)
            assert job["status"] == "pending"

            broker.start_job(job_id)
            job = broker.get_job(job_id)
            assert job["status"] == "running"
            assert job["started_at"] is not None

            broker.complete_job(job_id, result={"issues_found": 5})
            job = broker.get_job(job_id)
            assert job["status"] == "completed"
            assert job["result"]["issues_found"] == 5

            # Cleanup singleton
            ShadowBroker._instance = None
            ShadowBroker._initialized = False

    def test_fail_job(self, tmp_path: Path):
        """Failed jobs should record error message."""
        from tools.muscle.code_review.shadow_broker import ShadowBroker

        ShadowBroker._instance = None
        ShadowBroker._initialized = False

        with patch(
            "tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE",
            tmp_path / "shadow_jobs.json",
        ):
            broker = ShadowBroker.__new__(ShadowBroker)
            ShadowBroker._instance = broker
            ShadowBroker._initialized = False
            broker.__init__()

            job_id = broker.create_job(
                target_path="/tmp/project",
                mode=ReviewMode.REVIEW,
                intensity=Intensity.MINIMAL,
            )

            broker.start_job(job_id)
            broker.fail_job(job_id, "API rate limit exceeded")

            job = broker.get_job(job_id)
            assert job["status"] == "failed"
            assert job["error_message"] == "API rate limit exceeded"

            ShadowBroker._instance = None
            ShadowBroker._initialized = False

    def test_clear_completed_jobs(self, tmp_path: Path):
        """clear_completed should remove finished jobs."""
        from tools.muscle.code_review.shadow_broker import ShadowBroker

        ShadowBroker._instance = None
        ShadowBroker._initialized = False

        with patch(
            "tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE",
            tmp_path / "shadow_jobs.json",
        ):
            broker = ShadowBroker.__new__(ShadowBroker)
            ShadowBroker._instance = broker
            ShadowBroker._initialized = False
            broker.__init__()

            # Create mix of completed and pending jobs
            job1 = broker.create_job("/tmp/a", ReviewMode.REVIEW, Intensity.MODERATE)
            job2 = broker.create_job("/tmp/b", ReviewMode.REVIEW, Intensity.MODERATE)
            job3 = broker.create_job("/tmp/c", ReviewMode.REVIEW, Intensity.MODERATE)

            broker.complete_job(job1)
            broker.fail_job(job2, "error")
            # job3 stays pending

            cleared = broker.clear_completed()
            assert cleared == 2  # completed + failed

            # Pending job should remain
            assert broker.get_job(job3) is not None
            assert broker.get_job(job1) is None

            ShadowBroker._instance = None
            ShadowBroker._initialized = False

    def test_get_pending_jobs(self, tmp_path: Path):
        """get_pending_jobs should return only pending jobs."""
        from tools.muscle.code_review.shadow_broker import ShadowBroker

        ShadowBroker._instance = None
        ShadowBroker._initialized = False

        with patch(
            "tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE",
            tmp_path / "shadow_jobs.json",
        ):
            broker = ShadowBroker.__new__(ShadowBroker)
            ShadowBroker._instance = broker
            ShadowBroker._initialized = False
            broker.__init__()

            job1 = broker.create_job("/tmp/a", ReviewMode.REVIEW, Intensity.MODERATE)
            job2 = broker.create_job("/tmp/b", ReviewMode.REVIEW, Intensity.MODERATE)
            broker.start_job(job1)

            pending = broker.get_pending_jobs()
            assert len(pending) == 1
            assert pending[0]["job_id"] == job2

            ShadowBroker._instance = None
            ShadowBroker._initialized = False


class TestShadowWorkerIntegration:
    """Tests background worker job processing."""

    def test_worker_starts_and_stops(self, tmp_path: Path):
        """Worker should start as daemon and stop cleanly."""
        from tools.muscle.code_review.shadow_broker import ShadowBroker
        from tools.muscle.code_review.shadow_worker import ShadowWorker, WorkerConfig

        ShadowBroker._instance = None
        ShadowBroker._initialized = False

        with patch(
            "tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE",
            tmp_path / "shadow_jobs.json",
        ):
            broker = ShadowBroker.__new__(ShadowBroker)
            ShadowBroker._instance = broker
            ShadowBroker._initialized = False
            broker.__init__()

            config = WorkerConfig(
                poll_interval=0.1,
                idle_timeout=1.0,
                max_retries=1,
            )

            worker = ShadowWorker(broker, config=config)

            started = worker.start()
            assert started is True
            assert worker.is_running() is True

            stopped = worker.stop(timeout=2.0)
            assert stopped is True
            assert worker.is_running() is False

            ShadowBroker._instance = None
            ShadowBroker._initialized = False

    def test_worker_processes_job(self, tmp_path: Path):
        """Worker should process submitted jobs via processor callback."""
        from tools.muscle.code_review.shadow_broker import ShadowBroker
        from tools.muscle.code_review.shadow_worker import (
            JobTask,
            ShadowWorker,
            WorkerConfig,
        )

        ShadowBroker._instance = None
        ShadowBroker._initialized = False

        with patch(
            "tools.muscle.code_review.shadow_broker.SHADOW_JOBS_FILE",
            tmp_path / "shadow_jobs.json",
        ):
            broker = ShadowBroker.__new__(ShadowBroker)
            ShadowBroker._instance = broker
            ShadowBroker._initialized = False
            broker.__init__()

            processed_jobs: list[str] = []

            def mock_processor(job_task: JobTask) -> dict:
                processed_jobs.append(job_task.job_id)
                return {"status": "reviewed", "issues": 0}

            config = WorkerConfig(poll_interval=0.1, idle_timeout=2.0)
            worker = ShadowWorker(broker, config=config, job_processor=mock_processor)

            # Create a job
            job_id = broker.create_job("/tmp/test", ReviewMode.REVIEW, Intensity.MODERATE)

            worker.start()
            worker.submit_job(job_id, "/tmp/test", ReviewMode.REVIEW, Intensity.MODERATE)

            # Wait for processing
            time.sleep(1.0)

            worker.stop(timeout=3.0)

            assert len(processed_jobs) >= 1

            ShadowBroker._instance = None
            ShadowBroker._initialized = False


class TestLongEvalRunnerIntegration:
    """Tests long evaluation review and report generation."""

    def test_long_eval_runner_generates_report(self, tmp_path: Path):
        """LongEvalRunner should generate a report file."""
        from tools.muscle.code_review.long_eval_runner import LongEvalConfig, LongEvalRunner

        # Create a simple source file to review
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text('def main():\n    print("hello")\n')

        config = LongEvalConfig(
            target_paths=[str(src)],
            intensity="minimal",
        )

        runner = LongEvalRunner(str(tmp_path), config=config)

        # Mock the subprocess call that runs muscle review
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "session_id": "long_eval-001",
                        "issues": [],
                        "critical_count": 0,
                        "high_count": 0,
                    }
                ),
                stderr="",
            )
            result = runner.run_long_eval()

        assert result is not None
        assert "started_at" in result
        assert "completed_at" in result

    def test_long_eval_saves_report_file(self, tmp_path: Path):
        """Reports should be persisted to .muscle/reports/."""
        from tools.muscle.code_review.long_eval_runner import LongEvalConfig, LongEvalRunner

        config = LongEvalConfig(
            target_paths=[str(tmp_path)],
        )

        runner = LongEvalRunner(str(tmp_path), config=config)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps({"issues": [], "critical_count": 0}),
                stderr="",
            )
            runner.run_long_eval()

        reports_dir = tmp_path / ".muscle" / "reports"
        assert reports_dir.exists()

    def test_long_eval_reports_listing(self, tmp_path: Path):
        """Recent reports should be listable."""
        from tools.muscle.code_review.long_eval_runner import LongEvalRunner

        runner = LongEvalRunner(str(tmp_path))

        # Create some fake report files
        reports_dir = tmp_path / ".muscle" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        for i in range(3):
            report = {"total_issues": i * 2, "started_at": f"2024-01-0{i + 1}T03:00:00"}
            (reports_dir / f"long_eval_2024010{i + 1}.json").write_text(json.dumps(report))

        reports = runner.list_reports(limit=5)
        assert isinstance(reports, list)
