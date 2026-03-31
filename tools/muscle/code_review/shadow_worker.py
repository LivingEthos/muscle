"""
Shadow Worker - Background job processor for shadow mode reviews.

Production-ready background worker that:
- Runs as a daemon thread, processing pending jobs
- Handles graceful shutdown via signals
- Implements exponential backoff for retries
- Thread-safe job queue with persistence
- Real-time status updates
- Configurable idle timeout and retry limits

Architecture:
- ShadowBroker: Job storage and persistence (already exists)
- ShadowWorker: Background daemon that processes jobs
- WorkerManager: Lifecycle management singleton
"""

from __future__ import annotations

import atexit
import logging
import queue
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .shadow_broker import ShadowBroker
    from .types import Intensity, ReviewMode

logger = logging.getLogger(__name__)

WORKER_POLL_INTERVAL = 2.0
WORKER_IDLE_TIMEOUT = 300.0
WORKER_MAX_RETRIES = 3
WORKER_RETRY_BASE_DELAY = 5.0
WORKER_RETRY_MAX_DELAY = 60.0


@dataclass
class WorkerConfig:
    poll_interval: float = WORKER_POLL_INTERVAL
    idle_timeout: float = WORKER_IDLE_TIMEOUT
    max_retries: int = WORKER_MAX_RETRIES
    retry_base_delay: float = WORKER_RETRY_BASE_DELAY
    retry_max_delay: float = WORKER_RETRY_MAX_DELAY
    max_concurrent_jobs: int = 1


@dataclass
class JobTask:
    job_id: str
    target_path: str
    mode: ReviewMode
    intensity: Intensity
    retry_count: int = 0
    last_error: str | None = None
    queued_at: float = field(default_factory=time.time)


class ShadowWorker:
    def __init__(
        self,
        broker: ShadowBroker,
        config: WorkerConfig | None = None,
        job_processor: Callable[[JobTask], dict] | None = None,
    ):
        self.broker = broker
        self.config = config or WorkerConfig()
        self.job_processor = job_processor
        self._job_queue: queue.Queue[JobTask] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._is_running = False
        self._lock = threading.Lock()
        self._current_job: JobTask | None = None
        self._last_job_time: float = time.time()
        self._in_progress_jobs: set[str] = set()
        self._idle_check_interval = 5.0
        self._registered_atexit = False

    def start(self) -> bool:
        with self._lock:
            if self._is_running:
                logger.debug("Worker already running")
                return True

            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="ShadowWorker",
                daemon=True,
            )
            self._worker_thread.start()
            self._is_running = True

            if not self._registered_atexit:
                atexit.register(self.stop)
                self._registered_atexit = True

            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

            logger.info("ShadowWorker started")
            return True

    def stop(self, timeout: float = 10.0) -> bool:
        with self._lock:
            if not self._is_running:
                return True

            logger.info("ShadowWorker stopping...")
            self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
            if self._worker_thread.is_alive():
                logger.warning("Worker thread did not stop gracefully")

        with self._lock:
            self._is_running = False
            self._worker_thread = None
            logger.info("ShadowWorker stopped")
            return True

    def _handle_signal(self, signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown")
        self.stop(timeout=5.0)

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def submit_job(
        self,
        job_id: str,
        target_path: str,
        mode: ReviewMode,
        intensity: Intensity,
    ) -> None:
        with self._lock:
            if job_id in self._in_progress_jobs:
                logger.debug(f"Job {job_id} already in progress, skipping")
                return
            self._in_progress_jobs.add(job_id)
        task = JobTask(
            job_id=job_id,
            target_path=target_path,
            mode=mode,
            intensity=intensity,
        )
        self._job_queue.put(task)
        self._last_job_time = time.time()
        self.broker.start_job(job_id)
        logger.debug(f"Job {job_id} submitted to worker queue")

    def _worker_loop(self) -> None:
        logger.info("Worker loop started")
        last_poll = 0.0
        last_idle_check = time.time()

        while not self._stop_event.is_set():
            try:
                current_time = time.time()

                if current_time - last_poll >= self.config.poll_interval:
                    last_poll = current_time
                    self._poll_for_pending_jobs()

                if current_time - last_idle_check >= self._idle_check_interval:
                    last_idle_check = current_time
                    if self._should_idle_out():
                        logger.info("Worker idle timeout reached, continuing to poll for new jobs")

                try:
                    task = self._job_queue.get(timeout=0.5)
                    self._process_job(task)
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error in worker loop: {e}")

            except Exception as e:
                logger.error(f"Fatal error in worker loop: {e}")
                time.sleep(1.0)

        logger.info("Worker loop ended")

    def _poll_for_pending_jobs(self) -> None:
        try:
            with self._lock:
                pending = list(self.broker.get_pending_jobs())
            for job in pending:
                job_id = job.get("job_id")
                if not job_id:
                    continue
                if job_id in self._in_progress_jobs:
                    continue
                existing = self.broker.get_job(job_id)
                if existing and existing.get("status") == "pending":
                    with self._lock:
                        if job_id in self._in_progress_jobs:
                            continue
                        self._in_progress_jobs.add(job_id)
                    task = JobTask(
                        job_id=job_id,
                        target_path=job.get("target_path", ""),
                        mode=self._parse_review_mode(job.get("mode", "review")),
                        intensity=self._parse_intensity(job.get("intensity", "moderate")),
                    )
                    self._job_queue.put(task)
                    self.broker.start_job(job_id)
                    logger.debug(f"Polled pending job {job_id}")
        except Exception as e:
            logger.error(f"Error polling for pending jobs: {e}")

    def _should_idle_out(self) -> bool:
        if self._current_job is not None:
            return False
        if self._job_queue.qsize() > 0:
            return False
        return False

    def _process_job(self, task: JobTask) -> None:
        self._current_job = task
        logger.info(f"Processing job {task.job_id}")

        try:
            if self.job_processor is None:
                result = self._default_job_processor(task)
            else:
                result = self.job_processor(task)

            self.broker.complete_job(task.job_id, result)
            logger.info(f"Job {task.job_id} completed successfully")

        except Exception as e:
            logger.error(f"Job {task.job_id} failed: {e}")
            if task.retry_count < self.config.max_retries:
                task.retry_count += 1
                delay = min(
                    self.config.retry_base_delay * (2 ** (task.retry_count - 1)),
                    self.config.retry_max_delay,
                )
                logger.info(f"Retrying job {task.job_id} in {delay}s (attempt {task.retry_count})")
                time.sleep(delay)
                self._job_queue.put(task)
            else:
                self.broker.fail_job(task.job_id, str(e))
                logger.warning(f"Job {task.job_id} failed after {task.retry_count} retries")

        finally:
            self._current_job = None
            self._last_job_time = time.time()
            with self._lock:
                self._in_progress_jobs.discard(task.job_id)

    def _default_job_processor(self, task: JobTask) -> dict:
        from .types import ReviewConfig

        try:
            from ..m27_client import M27Client
            from .review_controller import ReviewController

            m27 = M27Client()
            config = ReviewConfig(
                target_path=task.target_path,
                mode=task.mode,
                intensity=task.intensity,
            )
            controller = ReviewController(config=config, m27_client=m27, use_kb=False)
            result = controller.run()

            return {
                "session_id": result.session_id,
                "issues_count": len(result.issues),
                "stats": {
                    "critical": sum(1 for i in result.issues if i.severity.value == 5),
                    "high": sum(1 for i in result.issues if i.severity.value == 4),
                    "medium": sum(1 for i in result.issues if i.severity.value == 3),
                    "low": sum(1 for i in result.issues if i.severity.value == 2),
                    "info": sum(1 for i in result.issues if i.severity.value == 1),
                },
            }
        except Exception as e:
            logger.error(f"Default job processor failed: {e}")
            raise

    @staticmethod
    def _parse_review_mode(mode_str: str) -> ReviewMode:
        from .types import ReviewMode

        mode_map = {
            "review": ReviewMode.REVIEW,
            "auto_fix": ReviewMode.AUTO_FIX,
            "plan": ReviewMode.PLAN,
            "hybrid": ReviewMode.HYBRID,
            "pressure": ReviewMode.PRESSURE,
        }
        return mode_map.get(mode_str, ReviewMode.REVIEW)

    @staticmethod
    def _parse_intensity(intensity_str: str) -> Intensity:
        from .types import Intensity

        intensity_map = {
            "minimal": Intensity.MINIMAL,
            "moderate": Intensity.MODERATE,
            "intensive": Intensity.INTENSIVE,
            "exhaustive": Intensity.EXHAUSTIVE,
        }
        return intensity_map.get(intensity_str, Intensity.MODERATE)


class WorkerManager:
    _instance: WorkerManager | None = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls, broker: ShadowBroker | None = None) -> WorkerManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, broker: ShadowBroker | None = None):
        if hasattr(self, "_worker") and self.__class__._initialized:
            return

        from .shadow_broker import ShadowBroker as ShadowBrokerBase

        self._broker = broker or ShadowBrokerBase()
        self._worker: ShadowWorker | None = None
        self._initialized = True

    def get_worker(self) -> ShadowWorker:
        if self._worker is None:
            self._worker = ShadowWorker(self._broker)
        return self._worker

    def start_worker(self) -> bool:
        return self.get_worker().start()

    def stop_worker(self, timeout: float = 10.0) -> bool:
        if self._worker is None:
            return True
        return self._worker.stop(timeout=timeout)

    def is_worker_running(self) -> bool:
        if self._worker is None:
            return False
        return self._worker.is_running()

    def submit_shadow_job(
        self,
        job_id: str,
        target_path: str,
        mode: ReviewMode,
        intensity: Intensity,
    ) -> None:
        self.start_worker()
        self.get_worker().submit_job(job_id, target_path, mode, intensity)

    def reset_singleton(self) -> None:
        if self._worker:
            self._worker.stop()
        WorkerManager._instance = None
        self._initialized = False
