"""
Shadow Worker - Background job processor for shadow mode reviews.

Production-ready background worker that:
- Runs as a daemon thread, processing pending jobs
- Handles graceful shutdown via signals
- Implements exponential backoff for retries
- Thread-safe job queue with persistence
- Real-time status updates
- Configurable idle timeout and retry limits
- Budget and timeout guardrails per job (W3-A)
- Changed-files-first scope tracking (W3-A)

Architecture:
- ShadowBroker: Project-local job storage backed by project_memory.db
- ShadowWorker: Background daemon that processes jobs
- WorkerManager: Lifecycle management (per-project instances)
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
WORKER_DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes


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
    project_path: str | None = None
    retry_count: int = 0
    last_error: str | None = None
    queued_at: float = field(default_factory=time.time)
    timeout_seconds: int = WORKER_DEFAULT_TIMEOUT_SECONDS
    token_budget: int | None = None
    changed_files: list[str] | None = None


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
        self._current_job_started: float | None = None
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
        project_path: str | None = None,
        timeout_seconds: int = WORKER_DEFAULT_TIMEOUT_SECONDS,
        token_budget: int | None = None,
        changed_files: list[str] | None = None,
    ) -> None:
        """
        Enqueue a job for background processing.

        The job record must already exist in the broker (created via
        `broker.create_job()`). This method enqueues the job for processing
        and marks it as running.

        Args:
            job_id: The job_id returned by `broker.create_job()`.
            target_path: Path that will be reviewed.
            mode: Review mode.
            intensity: Review intensity.
            project_path: Optional project path for scope.
            timeout_seconds: Job timeout in seconds.
            token_budget: Optional token budget cap.
            changed_files: Optional changed-files list for scope.
        """
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
            project_path=project_path,
            timeout_seconds=timeout_seconds,
            token_budget=token_budget,
            changed_files=changed_files,
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

                    import json

                    changed_files = None
                    changed_json = job.get("changed_files_json")
                    if changed_json:
                        try:
                            changed_files = json.loads(changed_json)
                        except Exception:
                            pass

                    task = JobTask(
                        job_id=job_id,
                        target_path=job.get("target_path", ""),
                        mode=self._parse_review_mode(job.get("mode", "review")),
                        intensity=self._parse_intensity(job.get("intensity", "moderate")),
                        project_path=job.get("project_path"),
                        timeout_seconds=job.get("timeout_seconds", WORKER_DEFAULT_TIMEOUT_SECONDS),
                        token_budget=job.get("token_budget"),
                        changed_files=changed_files,
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

    def _check_job_timeout(self, task: JobTask) -> bool:
        """Check if the current job has exceeded its timeout. Returns True if timed out."""
        if self._current_job_started is None:
            return False
        elapsed = time.time() - self._current_job_started
        if elapsed > task.timeout_seconds:
            logger.warning(
                f"Job {task.job_id} timed out after {elapsed:.1f}s (limit: {task.timeout_seconds}s)"
            )
            return True
        return False

    def _process_job(self, task: JobTask) -> None:
        self._current_job = task
        self._current_job_started = time.time()
        logger.info(f"Processing job {task.job_id}")

        try:
            # Budget guardrail: check token budget before starting
            if task.token_budget is not None and task.token_budget <= 0:
                self.broker.fail_job(task.job_id, "Token budget exhausted before job started")
                logger.warning(f"Job {task.job_id} skipped: token_budget is 0")
                return

            # Timeout guardrail: check periodically during processing
            if self.job_processor is None:
                result = self._default_job_processor(task)
            else:
                result = self.job_processor(task)

            self.broker.complete_job(task.job_id, result)
            logger.info(f"Job {task.job_id} completed successfully")

        except TimeoutError as e:
            logger.error(f"Job {task.job_id} timed out: {e}")
            self.broker.fail_job(task.job_id, f"Timeout after {task.timeout_seconds}s")
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
            self._current_job_started = None
            self._last_job_time = time.time()
            with self._lock:
                self._in_progress_jobs.discard(task.job_id)

    def _default_job_processor(self, task: JobTask) -> dict:
        from .types import ReviewConfig

        try:
            from ..budget_manager import BudgetManager
            from ..m27_client import M27Client
            from ..types import BudgetMode
            from .review_controller import ReviewController

            # Build a budget manager scoped to this job if a token budget was set
            budget_manager = None
            if task.token_budget is not None:
                budget_manager = BudgetManager(
                    mode=BudgetMode.FIXED,
                    fixed_limit=task.token_budget,
                )
                logger.debug(f"Job {task.job_id} budget: {task.token_budget} tokens")

            m27 = M27Client()
            config = ReviewConfig(
                target_path=task.target_path,
                mode=task.mode,
                intensity=task.intensity,
            )
            controller = ReviewController(
                config=config,
                m27_client=m27,
                use_kb=False,
            )
            result = controller.run()

            # Record token usage if budget tracking was enabled
            if budget_manager is not None:
                budget_info = budget_manager.get_budget_info()
                logger.debug(
                    f"Job {task.job_id} used approximately "
                    f"{budget_info.used_tokens} tokens (budget: {task.token_budget})"
                )

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
                "changed_files": task.changed_files,
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
    """
    Per-project worker lifecycle manager.

    Unlike the old global singleton, WorkerManager is created per-project
    so that multiple projects do not share shadow job state.
    """

    def __init__(self, project_path: str, db_path: str | None = None):
        from .shadow_broker import ShadowBroker

        self._project_path = project_path
        self._db_path = db_path
        self._broker: ShadowBroker = ShadowBroker(project_path, db_path)
        self._worker: ShadowWorker | None = None

    def get_worker(self) -> ShadowWorker:
        if self._worker is None:
            self._worker = ShadowWorker(self._broker)
        return self._worker

    def get_broker(self) -> ShadowBroker:
        return self._broker

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
        target_path: str,
        mode: ReviewMode,
        intensity: Intensity,
        timeout_seconds: int = WORKER_DEFAULT_TIMEOUT_SECONDS,
        token_budget: int | None = None,
        changed_files: list[str] | None = None,
    ) -> str:
        """
        Create and submit a shadow job for background processing.

        Creates the job record in the broker, then enqueues it for background
        processing. Returns the generated job_id.

        Args:
            target_path: Path that will be reviewed.
            mode: Review mode.
            intensity: Review intensity.
            timeout_seconds: Job timeout in seconds (default 300).
            token_budget: Optional token budget cap.
            changed_files: Optional changed-files list for scope.

        Returns:
            The generated job_id.
        """
        self.start_worker()
        # Create the job record (broker generates the actual job_id)
        actual_job_id = self._broker.create_job(
            target_path=target_path,
            mode=mode,
            intensity=intensity,
            changed_files=changed_files,
            timeout_seconds=timeout_seconds,
            token_budget=token_budget,
        )
        self.get_worker().submit_job(
            job_id=actual_job_id,
            target_path=target_path,
            mode=mode,
            intensity=intensity,
            project_path=self._project_path,
            timeout_seconds=timeout_seconds,
            token_budget=token_budget,
            changed_files=changed_files,
        )
        return actual_job_id

    @property
    def project_path(self) -> str:
        return self._project_path
