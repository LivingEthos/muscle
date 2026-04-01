"""
Unit tests for code_review/shadow_worker.py
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from tools.muscle.code_review.shadow_worker import (
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
            mode=MagicMock(),
            intensity=MagicMock(),
        )
        assert task.job_id == "test-1"
        assert task.retry_count == 0
        assert task.last_error is None


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
        worker.submit_job("job-1", "/src", Mock(), Mock())
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
    def test_singleton_pattern(self):
        WorkerManager._instance = None
        WorkerManager._initialized = False
        with patch("tools.muscle.code_review.shadow_broker.ShadowBroker"):
            mgr1 = WorkerManager()
            mgr2 = WorkerManager()
        assert mgr1 is mgr2
        WorkerManager._instance = None
        WorkerManager._initialized = False

    def test_get_worker_creates_worker(self):
        WorkerManager._instance = None
        WorkerManager._initialized = False
        with patch("tools.muscle.code_review.shadow_broker.ShadowBroker") as mock_broker_cls:
            mock_broker = MagicMock()
            mock_broker_cls.return_value = mock_broker
            mgr = WorkerManager()
            worker = mgr.get_worker()
        assert worker is not None
        WorkerManager._instance = None
        WorkerManager._initialized = False

    def test_start_stop_worker(self):
        WorkerManager._instance = None
        WorkerManager._initialized = False
        with patch("tools.muscle.code_review.shadow_broker.ShadowBroker") as mock_broker_cls:
            mock_broker = MagicMock()
            mock_broker_cls.return_value = mock_broker
            mgr = WorkerManager()
            mgr.get_worker().config.poll_interval = 0.1
            mgr.start_worker()
            assert mgr.is_worker_running() is True
            mgr.stop_worker()
            assert mgr.is_worker_running() is False
        WorkerManager._instance = None
        WorkerManager._initialized = False

    def test_stop_worker_when_none(self):
        WorkerManager._instance = None
        WorkerManager._initialized = False
        with patch("tools.muscle.code_review.shadow_broker.ShadowBroker"):
            mgr = WorkerManager()
            result = mgr.stop_worker()
        assert result is True
        WorkerManager._instance = None
        WorkerManager._initialized = False

    def test_submit_shadow_job(self):
        WorkerManager._instance = None
        WorkerManager._initialized = False
        with patch("tools.muscle.code_review.shadow_broker.ShadowBroker") as mock_broker_cls:
            mock_broker = MagicMock()
            mock_broker.get_pending_jobs.return_value = []
            mock_broker_cls.return_value = mock_broker
            mgr = WorkerManager()
            mgr.get_worker().config.poll_interval = 0.1
            from tools.muscle.code_review.types import Intensity, ReviewMode

            mgr.submit_shadow_job("job-x", "/src", ReviewMode.REVIEW, Intensity.MODERATE)
            mock_broker.start_job.assert_called_with("job-x")
            mgr.stop_worker()
        WorkerManager._instance = None
        WorkerManager._initialized = False

    def test_reset_singleton(self):
        WorkerManager._instance = None
        WorkerManager._initialized = False
        with patch("tools.muscle.code_review.shadow_broker.ShadowBroker") as mock_broker_cls:
            mock_broker = MagicMock()
            mock_broker_cls.return_value = mock_broker
            mgr = WorkerManager()
            mgr.get_worker().config.poll_interval = 0.1
            mgr.start_worker()
            mgr.reset_singleton()
            assert mgr.is_worker_running() is False
            assert WorkerManager._instance is None
        WorkerManager._instance = None
        WorkerManager._initialized = False
