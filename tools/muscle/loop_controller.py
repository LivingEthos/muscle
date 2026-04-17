"""
Loop Controller - The heart of MUSCLE.

Orchestrates the generate → evaluate → evolve → retry loop using M2.7 agents.

Architecture Decision Record (ADR):
- Single responsibility: controls loop state and iteration flow
- Delegates to specialized components (code_generator, evolver, evaluators)
- Supports multiple escape conditions (max_iterations, timeout, budget, early_exit)
- Emits events for monitoring without coupling to specific output formats
"""

import hashlib
import inspect
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .adapters.git_adapter import GitAdapter
from .delegation_metrics import DelegationEvent, DelegationMetrics
from .interactive import InteractiveChoice, InteractiveHandler
from .m27_client import TokenUsage
from .self_improver import SelfImprover
from .types import (
    BudgetInfo,
    BudgetMode,
    CodeArtifact,
    EvalMode,
    EvaluationResult,
    IterationReport,
    IterationResult,
    LoopStats,
    RunConfig,
    SessionReport,
    SessionStatus,
)
from .webhook_notifier import WebhookEvent, WebhookNotifier

logger = logging.getLogger(__name__)

MAX_ITERATIONS_MIN = 1
MAX_ITERATIONS_MAX = 100
MAX_TIMEOUT_SECONDS = 86400
MAX_TASK_LENGTH = 10000
MAX_TASK_PREVIEW_LENGTH = 50
MAX_COMMIT_MESSAGE_LENGTH = 500


class LoopEvent(Enum):
    ITERATION_START = "iteration_start"
    ITERATION_END = "iteration_end"
    GENERATION_START = "generation_start"
    GENERATION_END = "generation_end"
    GENERATION_STREAM = "generation_stream"
    EVALUATION_START = "evaluation_start"
    EVALUATION_END = "evaluation_end"
    EVOLUTION_START = "evolution_start"
    EVOLUTION_END = "evolution_end"
    BUDGET_WARNING = "budget_warning"
    BUDGET_OVERSPEND = "budget_overspend"
    SESSION_COMPLETE = "session_complete"
    SESSION_ABORT = "session_abort"


@dataclass
class LoopContext:
    session_id: str
    config: RunConfig
    stats: LoopStats
    evolved_strategy: str | None = None
    iterations: list[IterationResult] = field(default_factory=list)
    current_iteration: int = 0
    start_time: float = field(default_factory=time.time)
    last_evaluation: EvaluationResult | None = None
    user_hint: str | None = None


class LoopController:
    """
    Main loop orchestrator for MUSCLE.

    Usage:
        controller = LoopController(config, code_generator, evaluator, evolver)
        result = controller.run()
    """

    def __init__(
        self,
        config: RunConfig,
        code_generator: Callable[[str, str, str | None], tuple[str, TokenUsage]],
        evaluator: Callable[[str], EvaluationResult],
        evolver: Callable[[str, list[str], str | None], tuple[str, TokenUsage]],
        budget_manager: Callable[[int], tuple[bool, str]] | None = None,
        event_callback: Callable[[LoopEvent, dict], None] | None = None,
        webhook_notifier: WebhookNotifier | None = None,
        git_repo_path: str | None = None,
        git_auto_push: bool = False,
        interactive: InteractiveHandler | None = None,
        session_manager: Any = None,
        project_memory: Any = None,
    ):
        self.config = config
        self.code_generator = code_generator
        self.evaluator = evaluator
        self.evolver = evolver
        self.budget_manager = budget_manager
        self.event_callback = event_callback
        self.webhook_notifier = webhook_notifier
        self.git_repo_path = git_repo_path
        self.git_auto_push = git_auto_push
        self.interactive = interactive or InteractiveHandler(enabled=config.interactive)
        self._session_manager = session_manager
        self._project_memory = project_memory
        self._abort_requested = False
        self._session_report: SessionReport | None = None
        self._git_commit: str | None = None
        self._self_improver = SelfImprover()
        self._running: bool = False
        self._budget_overspend_emitted: bool = False

    def _emit(self, event: LoopEvent, data: dict) -> None:
        if self.event_callback:
            self.event_callback(event, data)
        logger.debug(f"Event: {event.value} - {data}")

    def _record_delegation_event(self, ctx: LoopContext) -> None:
        """Record a delegation event for observability (Phase B.6)."""
        try:
            project_path = (
                str(
                    getattr(
                        self._project_memory, "project_path", Path(ctx.config.output_dir).resolve()
                    )
                )
                if self._project_memory
                else ctx.config.output_dir
            )
            metrics = DelegationMetrics(project_path)
            metrics.record(
                DelegationEvent(
                    session_id=ctx.session_id,
                    entry_point="run",
                    m27_tokens_in=ctx.stats.total_tokens,
                    m27_tokens_out=0,
                )
            )
        except Exception as exc:
            logger.debug("Failed to record delegation event: %s", exc)

    def _record_external_lesson_outcome(
        self,
        ctx: LoopContext,
        *,
        success: bool,
        outcome: str,
    ) -> None:
        if self._project_memory is None:
            return
        try:
            self._project_memory.apply_transferred_lesson_outcomes(
                project_path=str(
                    getattr(
                        self._project_memory, "project_path", Path(ctx.config.output_dir).resolve()
                    )
                ),
                session_id=ctx.session_id,
                stages=["generate"],
                outcome=outcome,
                success=success,
            )
        except Exception as exc:
            logger.warning(
                "Failed to record external lesson outcome for generation session %s: %s",
                ctx.session_id,
                exc,
            )

    def _emit_webhook(self, event: WebhookEvent, session_id: str, data: dict) -> None:
        if self.webhook_notifier and self.webhook_notifier.enabled:
            self.webhook_notifier.send(event, session_id, data)

    def _validate_config(self, config: RunConfig) -> None:
        if not config.task or not config.task.strip():
            raise ValueError("Task cannot be empty")

        if len(config.task) > MAX_TASK_LENGTH:
            logger.warning(
                f"Task length {len(config.task)} exceeds {MAX_TASK_LENGTH}, will be truncated internally"
            )

        if not (MAX_ITERATIONS_MIN <= config.max_iterations <= MAX_ITERATIONS_MAX):
            raise ValueError(
                f"max_iterations must be between {MAX_ITERATIONS_MIN} and "
                f"{MAX_ITERATIONS_MAX}, got {config.max_iterations}"
            )

        if config.timeout_seconds < 1 or config.timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}, "
                f"got {config.timeout_seconds}"
            )

        if config.budget_tokens < 0:
            raise ValueError(f"budget_tokens must be non-negative, got {config.budget_tokens}")

    @staticmethod
    def _truncate(s: str, max_len: int) -> str:
        if len(s) <= max_len:
            return s
        return s[: max_len - 3] + "..."

    def request_abort(self) -> None:
        self._abort_requested = True
        logger.info("Abort requested")

    def _auto_commit(self, ctx: LoopContext) -> None:
        if not self.git_repo_path:
            return

        git = GitAdapter(self.git_repo_path)

        if not git.is_git_repo():
            logger.warning(f"Not a git repo: {self.git_repo_path}")
            return

        branch_name = f"muscle/session-{ctx.session_id}"
        if git.create_branch(branch_name):
            logger.info(f"Created branch: {branch_name}")
        else:
            logger.warning(f"Could not create branch: {branch_name}")
            return

        files = git.get_changed_files()
        if not files:
            logger.info("No changes to commit")
            return

        if git.add_files(files):
            task_preview = self._truncate(self.config.task, MAX_TASK_PREVIEW_LENGTH)
            message = (
                f"feat: MUSCLE session {ctx.session_id} - {task_preview}\n\n"
                f"Iterations: {ctx.stats.total_iterations}\n"
                f"Tokens: {ctx.stats.total_tokens}\n"
                f"Status: {ctx.stats.status.value}\n"
                f"MUSCLE-Iteration: {ctx.stats.total_iterations}"
            )
            if len(message) > MAX_COMMIT_MESSAGE_LENGTH:
                message = message[:MAX_COMMIT_MESSAGE_LENGTH]
            commit_hash = git.commit(message)
            if commit_hash:
                self._git_commit = commit_hash
                logger.info(f"Committed: {commit_hash}")
                if self.git_auto_push:
                    if git.push():
                        logger.info("Pushed to remote")
                    else:
                        logger.warning("Push failed")
            else:
                logger.warning("Commit failed")
        else:
            logger.warning("Could not stage files")

    def _should_continue(self, ctx: LoopContext) -> tuple[bool, str | None]:
        if self._abort_requested:
            return False, None

        if ctx.current_iteration >= self.config.max_iterations:
            return False, f"Max iterations ({self.config.max_iterations}) reached"

        elapsed = max(0.0, time.time() - ctx.start_time)
        if elapsed >= self.config.timeout_seconds:
            return False, f"Timeout ({self.config.timeout_seconds}s) exceeded"

        if self.config.early_exit_on == "test_pass":
            if ctx.last_evaluation and len(ctx.last_evaluation.test_failures) == 0:
                return False, "Early exit: tests passing"

        return True, None

    def _check_budget(self, token_cost: int) -> tuple[bool, str | None]:
        if self.budget_manager:
            ok, reason = self.budget_manager(token_cost)
            if not ok:
                return False, reason
        return True, None

    @staticmethod
    def _supports_kwarg(callable_obj: Callable[..., Any], name: str) -> bool:
        try:
            signature = inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return False
        parameter = signature.parameters.get(name)
        if parameter is None:
            return False
        return parameter.kind in {
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }

    def _wait_for_evolved_strategy(self, errors: list[str], ctx: LoopContext) -> str | None:
        self._emit(
            LoopEvent.EVOLUTION_START, {"iteration": ctx.current_iteration, "errors": errors}
        )

        evolve_kwargs: dict[str, Any] = {}
        if self._supports_kwarg(self.evolver, "session_id"):
            evolve_kwargs["session_id"] = ctx.session_id

        evolved, usage = self.evolver(
            ctx.config.task,
            errors,
            ctx.evolved_strategy,
            **evolve_kwargs,
        )

        ctx.stats.total_tokens += usage.total
        self._emit(LoopEvent.EVOLUTION_END, {"strategy": evolved[:100], "tokens": usage.total})

        return evolved

    def _run_iteration(
        self, ctx: LoopContext, streaming_callback: Callable[[str], None] | None = None
    ) -> IterationResult:
        iter_num = ctx.current_iteration
        iter_start = time.time()
        effective_task = ctx.config.task
        user_hint: str | None = None

        self._emit(LoopEvent.ITERATION_START, {"iteration": iter_num})

        choice = self.interactive.pause_before_iteration(
            iter_num, effective_task, ctx.evolved_strategy
        )
        if choice == InteractiveChoice.ABORT:
            self._abort_requested = True
            return IterationResult(
                iteration=iter_num,
                success=False,
                token_cost=0,
                duration_seconds=time.time() - iter_start,
            )
        elif choice == InteractiveChoice.SKIP:
            self._emit(LoopEvent.ITERATION_END, {"success": False, "skipped": True})
            return IterationResult(
                iteration=iter_num,
                success=False,
                token_cost=0,
                duration_seconds=time.time() - iter_start,
            )
        elif choice == InteractiveChoice.MODIFY:
            try:
                hint = input("Enter your hint: ").strip()
            except (EOFError, OSError) as e:
                logger.warning(f"Failed to read hint input: {e}")
                hint = ""
            if hint:
                user_hint = hint
                effective_task = f"{effective_task}\n\nUser hint: {hint}"

        if ctx.user_hint:
            effective_task = f"{effective_task}\n\nUser hint: {ctx.user_hint}"

        self._emit(LoopEvent.GENERATION_START, {"strategy": ctx.evolved_strategy})

        output_path = Path(ctx.config.output_dir)
        cache_names = {
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            ".mypy_cache",
            ".tox",
            ".coverage",
            "node_modules",
        }
        pre_existing = set()
        if output_path.exists() and output_path.is_dir():
            pre_existing = {
                p.name
                for p in output_path.iterdir()
                if not (p.is_dir() and p.name in cache_names)
                and not (p.is_file() and p.name.endswith(".pyc"))
            }

        if streaming_callback:
            gen_streaming = getattr(self.code_generator, "generate_streaming", None)
            if gen_streaming:
                code_output = ""
                gen_usage = TokenUsage()

                def on_stream_chunk(chunk: str) -> None:
                    if not chunk:
                        return
                    streaming_callback(chunk)
                    self._emit(LoopEvent.GENERATION_STREAM, {"chunk": chunk})

                generate_streaming_kwargs: dict[str, Any] = {}
                if self._supports_kwarg(gen_streaming, "progress_callback"):
                    generate_streaming_kwargs["progress_callback"] = on_stream_chunk

                for chunk, usage in gen_streaming(
                    effective_task,
                    ctx.evolved_strategy or "",
                    ctx.config.output_dir,
                    **generate_streaming_kwargs,
                ):
                    if usage is not None:
                        gen_usage = usage
                    if chunk:
                        code_output = chunk
                        if not generate_streaming_kwargs:
                            on_stream_chunk(chunk)
            else:
                generate_kwargs: dict[str, Any] = {}
                if self._supports_kwarg(self.code_generator, "session_id"):
                    generate_kwargs["session_id"] = ctx.session_id
                code_output, gen_usage = self.code_generator(
                    effective_task,
                    ctx.evolved_strategy or "",
                    ctx.config.output_dir,
                    **generate_kwargs,
                )
        else:
            generate_kwargs = {}
            if self._supports_kwarg(self.code_generator, "session_id"):
                generate_kwargs["session_id"] = ctx.session_id
            code_output, gen_usage = self.code_generator(
                effective_task,
                ctx.evolved_strategy or "",
                ctx.config.output_dir,
                **generate_kwargs,
            )

        ctx.stats.total_tokens += gen_usage.total
        self._emit(LoopEvent.GENERATION_END, {"tokens": gen_usage.total})

        self._emit(LoopEvent.EVALUATION_START, {})

        evaluation = self.evaluator(ctx.config.output_dir)
        if evaluation is None:
            logger.error("Evaluator returned None for %s", ctx.config.output_dir)
            evaluation = EvaluationResult(
                passed=False,
                compiler_errors=["Evaluator returned no result"],
            )

        ctx.last_evaluation = evaluation
        duration = time.time() - iter_start

        post_files: set[str] = set()
        if output_path.exists() and output_path.is_dir():
            post_files = {
                p.name
                for p in output_path.iterdir()
                if not (p.is_dir() and p.name in cache_names)
                and not (p.is_file() and p.name.endswith(".pyc"))
            }
        new_files = sorted(post_files - pre_existing)

        result = IterationResult(
            iteration=iter_num,
            success=False,
            token_cost=gen_usage.total,
            duration_seconds=duration,
            files_generated=new_files,
        )

        if evaluation.passed or (self.config.allow_warnings and evaluation.has_warnings_only):
            result.success = True
            self._record_external_lesson_outcome(
                ctx,
                success=True,
                outcome="positive_generation_iteration",
            )
            self._emit(LoopEvent.ITERATION_END, {"success": True})
            self._emit(LoopEvent.EVALUATION_END, {"passed": True})

            files: list[str] = []
            success_choice = self.interactive.pause_on_success(iter_num, files)
            if success_choice == InteractiveChoice.ABORT:
                self._emit(LoopEvent.SESSION_COMPLETE, {"status": SessionStatus.ABORTED.value})
                return result

            return result

        result.errors = evaluation.all_errors
        self._record_external_lesson_outcome(
            ctx,
            success=False,
            outcome="negative_generation_evaluation",
        )
        result.warnings = evaluation.linter_warnings
        self._emit(LoopEvent.EVALUATION_END, {"passed": False, "errors": len(result.errors)})

        failure_choice, user_hint = self.interactive.pause_on_failure(iter_num, result.errors)
        if failure_choice == InteractiveChoice.ABORT:
            self._abort_requested = True
            self._emit(LoopEvent.ITERATION_END, {"success": False, "aborted": True})
            return result
        elif failure_choice == InteractiveChoice.MODIFY and user_hint:
            ctx.user_hint = user_hint

        evolved: str | None = None
        if self.config.eval_mode == EvalMode.ALL:
            evolved = self._wait_for_evolved_strategy(result.errors, ctx)
            if evolved:
                ctx.evolved_strategy = evolved
                result.evolved_strategy = evolved
        elif self.config.eval_mode == EvalMode.SEQUENTIAL:
            for error in result.errors:
                evolved = self._wait_for_evolved_strategy([error], ctx)
                if evolved:
                    ctx.evolved_strategy = evolved
                    result.evolved_strategy = evolved
        elif self.config.eval_mode == EvalMode.PARALLEL:
            evolved = self._wait_for_evolved_strategy(result.errors, ctx)
            if evolved:
                ctx.evolved_strategy = evolved
                result.evolved_strategy = evolved

        self._emit(
            LoopEvent.ITERATION_END,
            {"success": False, "evolved": bool(evolved) if evolved else False},
        )
        return result

    def _sigterm_handler(self, signum: int, frame: object) -> None:
        logger.info("SIGTERM received, requesting abort")
        self._abort_requested = True

    def _write_session_pid(self, session_id: str) -> None:
        pid_file = Path.home() / ".muscle" / f"{session_id}.pid"
        try:
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
            logger.debug(f"Wrote PID {os.getpid()} to {pid_file}")
        except OSError as e:
            logger.warning(f"Could not write PID file: {e}")

    def _remove_session_pid(self, session_id: str | None = None) -> None:
        if session_id is None:
            return
        pid_file = Path.home() / ".muscle" / f"{session_id}.pid"
        try:
            pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    def run(
        self,
        streaming_callback: Callable[[str], None] | None = None,
        resume_context: LoopContext | None = None,
    ) -> LoopContext:
        # LC-02: guard against concurrent reuse of the same instance
        if self._running:
            raise RuntimeError(
                "LoopController.run() is already in progress on this instance. "
                "Create a separate LoopController for concurrent execution."
            )
        self._running = True
        self._budget_overspend_emitted = False

        config = resume_context.config if resume_context else self.config
        self._validate_config(config)
        self.config = config

        if resume_context is not None:
            ctx = resume_context
            ctx.stats.status = SessionStatus.RUNNING
            ctx.start_time = time.time()
            if self._session_manager and hasattr(self._session_manager, "mark_resumed"):
                self._session_manager.mark_resumed(ctx.session_id)
        elif self._session_manager:
            session_id = self._session_manager.create_session(self.config)
            ctx = LoopContext(
                session_id=session_id,
                config=self.config,
                stats=LoopStats(),
            )
        else:
            session_id = str(uuid.uuid4())[:8]
            ctx = LoopContext(
                session_id=session_id,
                config=self.config,
                stats=LoopStats(),
            )

        logger.info(
            f"Starting MUSCLE session {ctx.session_id}: "
            f"{self._truncate(self.config.task, MAX_TASK_PREVIEW_LENGTH)}..."
        )

        self._write_session_pid(ctx.session_id)
        original_sigterm = signal.signal(signal.SIGTERM, self._sigterm_handler)

        try:
            if self.webhook_notifier and self.webhook_notifier.enabled:
                self.webhook_notifier.send_session_start(
                    ctx.session_id,
                    self.config.task,
                    {
                        "max_iterations": self.config.max_iterations,
                        "timeout_seconds": self.config.timeout_seconds,
                        "budget_tokens": self.config.budget_tokens,
                    },
                )

            while True:
                should_cont, reason = self._should_continue(ctx)
                if not should_cont:
                    if self._abort_requested:
                        ctx.stats.status = SessionStatus.ABORTED
                        self._emit(
                            LoopEvent.SESSION_ABORT, {"reason": reason or "User requested abort"}
                        )
                    elif reason:
                        ctx.stats.status = SessionStatus.FAILED
                        self._emit(
                            LoopEvent.SESSION_COMPLETE,
                            {"reason": reason, "status": ctx.stats.status.value},
                        )
                        if self.webhook_notifier and self.webhook_notifier.enabled:
                            self.webhook_notifier.send_session_failure(ctx.session_id, reason)
                    else:
                        ctx.stats.status = SessionStatus.ABORTED
                        self._emit(LoopEvent.SESSION_ABORT, {"reason": "Unknown reason"})
                    break

                ctx.current_iteration += 1
                iteration_result = self._run_iteration(ctx, streaming_callback)
                ctx.iterations.append(iteration_result)
                ctx.stats.total_iterations = ctx.current_iteration
                ctx.stats.total_tokens += iteration_result.token_cost
                ctx.stats.total_duration_seconds += iteration_result.duration_seconds

                # LC-01: emit overspend event exactly once when budget is first exceeded
                if (
                    self.config.budget_tokens > 0
                    and ctx.stats.total_tokens > self.config.budget_tokens
                    and not self._budget_overspend_emitted
                ):
                    self._budget_overspend_emitted = True
                    self._emit(
                        LoopEvent.BUDGET_OVERSPEND,
                        {
                            "iteration": ctx.current_iteration,
                            "total_tokens": ctx.stats.total_tokens,
                            "budget_tokens": self.config.budget_tokens,
                            "overspend": ctx.stats.total_tokens - self.config.budget_tokens,
                            "remaining_tokens": 0,
                        },
                    )

                if self.webhook_notifier and self.webhook_notifier.enabled:
                    self.webhook_notifier.send_iteration_complete(
                        ctx.session_id,
                        iteration_result.iteration,
                        iteration_result.success,
                        iteration_result.token_cost,
                    )

                if self._session_manager:
                    self._session_manager.save_iteration(ctx.session_id, iteration_result)

                if iteration_result.success:
                    ctx.stats.status = SessionStatus.SUCCESS
                    self._emit(LoopEvent.SESSION_COMPLETE, {"status": SessionStatus.SUCCESS.value})
                    if self.webhook_notifier and self.webhook_notifier.enabled:
                        self.webhook_notifier.send_session_success(
                            ctx.session_id,
                            ctx.stats.total_iterations,
                            ctx.stats.total_tokens,
                        )
                    self._auto_commit(ctx)
                    break

                budget_ok, budget_reason = self._check_budget(iteration_result.token_cost)
                if not budget_ok:
                    ctx.stats.status = SessionStatus.BUDGET_EXCEEDED
                    self._emit(LoopEvent.SESSION_ABORT, {"reason": budget_reason})
                    if self.webhook_notifier and self.webhook_notifier.enabled:
                        self.webhook_notifier.send_budget_exceeded(ctx.session_id)
                    break

                if ctx.current_iteration > 1 and ctx.current_iteration % 5 == 0:
                    remaining_tokens = (
                        max(0, self.config.budget_tokens - ctx.stats.total_tokens)
                        if self.config.budget_tokens > 0
                        else 0
                    )
                    self._emit(
                        LoopEvent.BUDGET_WARNING,
                        {
                            "iteration": ctx.current_iteration,
                            "total_tokens": ctx.stats.total_tokens,
                            "remaining_tokens": remaining_tokens,
                        },
                    )
                    if self.webhook_notifier and self.webhook_notifier.enabled:
                        self.webhook_notifier.send_budget_warning(
                            ctx.session_id,
                            float(ctx.stats.total_tokens) / float(self.config.budget_tokens)
                            if self.config.budget_tokens > 0
                            else 0.0,
                            remaining_tokens,
                        )

            logger.info(
                f"Session {ctx.session_id} complete: "
                f"status={ctx.stats.status.value}, "
                f"iterations={ctx.stats.total_iterations}, "
                f"tokens={ctx.stats.total_tokens}"
            )

            self._record_delegation_event(ctx)

            self._build_session_report(ctx)

            if self._session_manager and self._session_report:
                self._session_manager.save_session_report(ctx.session_id, self._session_report)
                self._session_manager.save_final_context(ctx)

            all_errors: list[str] = []
            for it_result in ctx.iterations:
                all_errors.extend(it_result.errors)

            self._self_improver.log_session(
                session_id=ctx.session_id,
                task=ctx.config.task,
                status=ctx.stats.status.value,
                iterations=ctx.stats.total_iterations,
                tokens=ctx.stats.total_tokens,
                duration=ctx.stats.total_duration_seconds,
                errors=all_errors,
                strategy=ctx.evolved_strategy,
            )

            return ctx
        finally:
            self._running = False
            signal.signal(signal.SIGTERM, original_sigterm)
            self._remove_session_pid(ctx.session_id)

    def _build_session_report(self, ctx: LoopContext) -> None:
        budget_info: BudgetInfo | None = None
        if self.config.budget_mode != BudgetMode.UNLIMITED:
            budget_info = BudgetInfo(
                mode=self.config.budget_mode,
                limit=self.config.budget_tokens,
                spent=ctx.stats.total_tokens,
            )

        iteration_reports: list[IterationReport] = []
        all_generated_files: list[CodeArtifact] = []
        for it_result in ctx.iterations:
            iteration_reports.append(
                IterationReport(
                    iteration=it_result.iteration,
                    success=it_result.success,
                    errors=it_result.errors,
                    warnings=it_result.warnings,
                    token_cost=it_result.token_cost,
                    duration_seconds=it_result.duration_seconds,
                    files_generated=it_result.files_generated,
                    evolved_strategy=it_result.evolved_strategy,
                )
            )
            for fname in it_result.files_generated:
                fpath = Path(ctx.config.output_dir) / fname
                content_hash = ""
                lines = 0
                if fpath.exists() and fpath.is_file():
                    try:
                        file_bytes = fpath.read_bytes()
                        content_hash = hashlib.sha256(file_bytes).hexdigest()
                        lines = len(
                            fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                        )
                    except OSError as e:
                        logger.warning(f"Could not read generated file metadata for {fpath}: {e}")
                all_generated_files.append(
                    CodeArtifact(
                        file_path=str(fpath),
                        content_hash=content_hash,
                        language=ctx.config.language or "unknown",
                        lines=lines,
                    )
                )

        self._session_report = SessionReport(
            session_id=ctx.session_id,
            task=ctx.config.task,
            status=ctx.stats.status,
            total_iterations=ctx.stats.total_iterations,
            total_tokens=ctx.stats.total_tokens,
            total_duration_seconds=ctx.stats.total_duration_seconds,
            iterations=iteration_reports,
            final_strategy=ctx.evolved_strategy,
            artifacts=all_generated_files,
            budget_info=budget_info,
            git_commit=self._git_commit,
        )

    def get_session_report(self) -> SessionReport | None:
        """Return the session report after run() has completed."""
        return self._session_report
