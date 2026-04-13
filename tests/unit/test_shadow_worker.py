"""
Unit tests for code_review/shadow_worker.py (W3-A).
"""

from unittest.mock import Mock

import pytest

from tools.muscle.code_review.shadow_worker import (
    WORKER_DEFAULT_TIMEOUT_SECONDS,
    JobTask,
    ShadowWorker,
    WorkerConfig,
    WorkerManager,
)


class TestWorkerConfig:
    def test_defaults(self):
        config = WorkerConfig()
        assert config.poll_interval == 2.0
        assert config.idle_timeout == 300.0
        assert config.max_retries == 3
        assert config.retry_base_delay == 5.0
        assert config.retry_max_delay == 60.0


class TestJobTask:
    def test_defaults(self):
        task = JobTask(
            job_id="test-1",
            target_path="/src",
            mode=Mock(),
            intensity=Mock(),
        )
        assert task.job_id == "test-1"
        assert task.execution_mode == "local"
        assert task.retry_count == 0
        assert task.last_error is None
        assert task.timeout_seconds == WORKER_DEFAULT_TIMEOUT_SECONDS

    def test_with_timeout_and_budget(self):
        task = JobTask(
            job_id="test-2",
            target_path="/src",
            mode=Mock(),
            intensity=Mock(),
            timeout_seconds=600,
            token_budget=50000,
        )
        assert task.timeout_seconds == 600
        assert task.token_budget == 50000

    def test_with_changed_files(self):
        task = JobTask(
            job_id="test-3",
            target_path="/src",
            mode=Mock(),
            intensity=Mock(),
            changed_files=["src/a.py", "src/b.py"],
        )
        assert task.changed_files == ["src/a.py", "src/b.py"]


class TestShadowWorker:
    @pytest.fixture
    def mock_broker(self):
        return Mock()

    @pytest.fixture
    def worker(self, mock_broker):
        return ShadowWorker(broker=mock_broker)

    def test_init(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        assert worker.broker is mock_broker
        assert worker.config is not None
        assert worker.is_running() is False

    def test_start_stop_cycle(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        worker.config.poll_interval = 0.1
        worker.config.idle_timeout = 0.5
        started = worker.start()
        assert started is True
        assert worker.is_running() is True
        stopped = worker.stop(timeout=2.0)
        assert stopped is True
        assert worker.is_running() is False

    def test_start_twice(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        worker.config.poll_interval = 0.1
        worker.start()
        first_start = worker.start()
        assert first_start is True
        worker.stop()

    def test_stop_not_running(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        result = worker.stop()
        assert result is True

    def test_submit_job(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        mock_broker.get_pending_jobs.return_value = []
        # submit_job no longer creates the job; caller must do that first
        worker.submit_job("job-1", "/src", Mock(), Mock())
        mock_broker.start_job.assert_called_once_with("job-1")

    def test_submit_job_with_timeout_and_budget(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        mock_broker.get_pending_jobs.return_value = []
        # submit_job no longer creates the job; caller must do that first
        worker.submit_job(
            "job-1",
            "/src",
            Mock(),
            Mock(),
            timeout_seconds=600,
            token_budget=50000,
        )
        mock_broker.start_job.assert_called_once_with("job-1")

    def test_submit_job_idempotent(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        mock_broker.get_pending_jobs.return_value = []
        worker.submit_job("job-2", "/src", Mock(), Mock())
        worker.submit_job("job-2", "/src", Mock(), Mock())
        assert mock_broker.start_job.call_count == 1

    def test_parse_review_mode(self):
        from tools.muscle.code_review.types import ReviewMode

        assert ShadowWorker._parse_review_mode("review") == ReviewMode.REVIEW
        assert ShadowWorker._parse_review_mode("auto_fix") == ReviewMode.AUTO_FIX
        assert ShadowWorker._parse_review_mode("plan") == ReviewMode.PLAN
        assert ShadowWorker._parse_review_mode("unknown") == ReviewMode.REVIEW

    def test_parse_intensity(self):
        from tools.muscle.code_review.types import Intensity

        assert ShadowWorker._parse_intensity("minimal") == Intensity.MINIMAL
        assert ShadowWorker._parse_intensity("moderate") == Intensity.MODERATE
        assert ShadowWorker._parse_intensity("intensive") == Intensity.INTENSIVE
        assert ShadowWorker._parse_intensity("unknown") == Intensity.MODERATE

    def test_should_idle_out_always_false(self, mock_broker):
        worker = ShadowWorker(broker=mock_broker)
        assert worker._should_idle_out() is False

    def test_worker_config_custom(self):
        config = WorkerConfig(poll_interval=0.5, max_retries=5)
        assert config.poll_interval == 0.5
        assert config.max_retries == 5


class TestWorkerManager:
    @pytest.fixture
    def tmp_project(self, tmp_path):
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        return tmp_path

    def test_per_project_broker(self, tmp_project):
        """WorkerManager should create per-project broker, not a singleton."""
        mgr = WorkerManager(project_path=str(tmp_project))
        broker = mgr.get_broker()
        assert broker is not None
        assert broker.project_path == str(tmp_project)

    def test_multiple_projects_have_isolated_state(self, tmp_path):
        from tools.muscle.code_review.types import Intensity, ReviewMode

        proj_a = tmp_path / "proj_a"
        proj_b = tmp_path / "proj_b"
        proj_a.mkdir()
        proj_b.mkdir()

        mgr_a = WorkerManager(project_path=str(proj_a))
        mgr_b = WorkerManager(project_path=str(proj_b))

        broker_a = mgr_a.get_broker()
        broker_b = mgr_b.get_broker()

        jid_a = broker_a.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)
        jid_b = broker_b.create_job("/target", ReviewMode.REVIEW, Intensity.MINIMAL)

        # Each broker only sees its own jobs
        assert broker_a.get_job(jid_a) is not None
        assert broker_a.get_job(jid_b) is None
        assert broker_b.get_job(jid_b) is not None
        assert broker_b.get_job(jid_a) is None

    def test_get_worker_creates_worker(self, tmp_project):
        mgr = WorkerManager(project_path=str(tmp_project))
        worker = mgr.get_worker()
        assert worker is not None

    def test_start_stop_worker(self, tmp_project):
        mgr = WorkerManager(project_path=str(tmp_project))
        mgr.get_worker().config.poll_interval = 0.1
        mgr.start_worker()
        assert mgr.is_worker_running() is True
        mgr.stop_worker()
        assert mgr.is_worker_running() is False

    def test_stop_worker_when_none(self, tmp_project):
        mgr = WorkerManager(project_path=str(tmp_project))
        result = mgr.stop_worker()
        assert result is True

    def test_submit_shadow_job(self, tmp_project):
        from tools.muscle.code_review.types import Intensity, ReviewMode

        mgr = WorkerManager(project_path=str(tmp_project))
        worker = mgr.get_worker()
        worker.config.poll_interval = 0.1

        # submit_shadow_job creates the job then enqueues it; returns the actual job_id
        job_id = mgr.submit_shadow_job(
            "/src",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
        )
        assert job_id is not None
        assert len(job_id) == 8
        broker = mgr.get_broker()
        # Verify job was stored in broker
        job = broker.get_job(job_id)
        assert job is not None
        assert job["target_path"] == "/src"

    def test_submit_shadow_job_with_timeout_and_budget(self, tmp_project):
        from tools.muscle.code_review.types import Intensity, ReviewMode

        mgr = WorkerManager(project_path=str(tmp_project))
        worker = mgr.get_worker()
        worker.config.poll_interval = 0.1

        job_id = mgr.submit_shadow_job(
            "/src",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
            timeout_seconds=600,
            token_budget=50000,
            changed_files=["src/main.py"],
        )
        broker = mgr.get_broker()
        job = broker.get_job(job_id)
        assert job is not None
        assert job["timeout_seconds"] == 600
        assert job["token_budget"] == 50000

    def test_submit_shadow_job_persists_execution_mode(self, tmp_project):
        from tools.muscle.code_review.types import Intensity, ReviewMode

        mgr = WorkerManager(project_path=str(tmp_project))
        worker = mgr.get_worker()
        worker.config.poll_interval = 0.1

        job_id = mgr.submit_shadow_job(
            "/src",
            ReviewMode.AUTO_FIX,
            Intensity.MODERATE,
            execution_mode="worktree",
        )
        job = mgr.get_broker().get_job(job_id)
        assert job is not None
        assert job["execution_mode"] == "worktree"

    def test_project_path_property(self, tmp_project):
        mgr = WorkerManager(project_path=str(tmp_project))
        assert mgr.project_path == str(tmp_project)
