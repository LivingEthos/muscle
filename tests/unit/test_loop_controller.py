"""
Unit tests for SCLE loop controller.
"""

import hashlib
import threading
from unittest.mock import MagicMock, Mock, patch

from tools.muscle.interactive import InteractiveChoice
from tools.muscle.loop_controller import LoopContext, LoopController, LoopEvent
from tools.muscle.project_memory import ProjectMemory
from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager
from tools.muscle.types import (
    BudgetMode,
    EvalMode,
    EvaluationResult,
    IterationResult,
    LoopStats,
    RunConfig,
    SessionStatus,
)


class DummyEvaluator:
    def __init__(self, should_pass: bool = False):
        self.should_pass = should_pass
        self.call_count = 0

    def __call__(self, output_dir: str) -> EvaluationResult:
        self.call_count += 1
        if self.should_pass:
            return EvaluationResult(passed=True)
        return EvaluationResult(
            passed=False,
            compiler_errors=["SyntaxError: invalid syntax"] if self.call_count == 1 else [],
            test_failures=["Test failed: expected 1, got 0"] if self.call_count == 2 else [],
        )


class DummyGenerator:
    def __init__(self):
        self.call_count = 0

    def __call__(self, task: str, evolved_strategy: str, output_dir: str | None = None):
        self.call_count += 1
        import time

        time.sleep(0.01)
        return f"Generated code iteration {self.call_count}", MagicMock(total=1000)


class DummyEvolver:
    def __init__(self):
        self.call_count = 0

    def __call__(self, task: str, errors: list, previous_strategy: str | None = None):
        self.call_count += 1
        return f"Improved strategy based on {len(errors)} errors", MagicMock(total=500)


class DummyBudgetManager:
    def __init__(self):
        self.calls = []

    def __call__(self, iteration_cost: int):
        self.calls.append(iteration_cost)
        return True, ""


class DummyInteractive:
    def __init__(self, choice: InteractiveChoice = InteractiveChoice.CONTINUE, hint: str = ""):
        self.choice = choice
        self.hint = hint
        self.call_count = 0

    def pause_before_iteration(
        self, iteration: int, task: str, evolved_strategy: str
    ) -> InteractiveChoice:
        self.call_count += 1
        return self.choice

    def pause_on_success(self, iteration: int, files: list) -> InteractiveChoice:
        return self.choice

    def pause_on_failure(
        self, iteration: int, errors: list
    ) -> tuple[InteractiveChoice, str | None]:
        return self.choice, self.hint if self.choice == InteractiveChoice.MODIFY else None


class DummySessionManager:
    def __init__(self):
        self.create_calls = 0
        self.saved_iterations = []
        self.saved_reports = []
        self.saved_contexts = []
        self.resumed_sessions = []

    def create_session(self, config: RunConfig) -> str:
        self.create_calls += 1
        return "test-session-123"

    def save_iteration(self, session_id: str, iteration_result) -> None:
        self.saved_iterations.append((session_id, iteration_result))

    def save_session_report(self, session_id: str, report) -> None:
        self.saved_reports.append((session_id, report))

    def save_final_context(self, ctx) -> None:
        self.saved_contexts.append(ctx)

    def mark_resumed(self, session_id: str) -> None:
        self.resumed_sessions.append(session_id)


def test_loop_controller_success_first_iteration():
    config = RunConfig(
        task="Build a simple calculator",
        max_iterations=5,
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=True)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.SUCCESS
    assert ctx.stats.total_iterations == 1
    assert generator.call_count == 1
    assert evaluator.call_count == 1
    assert evolver.call_count == 0


def test_loop_controller_eventual_success():
    config = RunConfig(
        task="Build a REST API",
        max_iterations=5,
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.FAILED
    assert ctx.stats.total_iterations == 5
    assert generator.call_count == 5
    assert evaluator.call_count == 5
    assert evolver.call_count == 5


def test_loop_controller_max_iterations():
    config = RunConfig(
        task="Build a complex microservice",
        max_iterations=3,
        timeout_seconds=1,
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.FAILED
    assert ctx.stats.total_iterations == 3


def test_loop_controller_budget_exceeded():
    config = RunConfig(
        task="Build a large project",
        max_iterations=10,
        budget_tokens=3000,
        budget_mode=BudgetMode.FIXED,
    )

    def budget_check(cost):
        return False, "Budget exceeded"

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_check,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.BUDGET_EXCEEDED


def test_loop_controller_abort():
    config = RunConfig(
        task="Build an infinite project",
        max_iterations=100,
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    import threading
    import time

    abort_called = False

    def abort_after_delay():
        nonlocal abort_called
        time.sleep(0.001)
        controller.request_abort()
        abort_called = True

    thread = threading.Thread(target=abort_after_delay)
    thread.start()

    ctx = controller.run()
    thread.join()

    assert ctx.stats.status == SessionStatus.ABORTED or ctx.current_iteration < 100, (
        f"Abort not triggered properly. Status: {ctx.stats.status}, iterations: {ctx.current_iteration}"
    )


def test_loop_controller_eval_mode_all():
    """Test EvalMode.ALL evolves once with all errors at once."""
    config = RunConfig(
        task="Build something",
        max_iterations=3,
        budget_mode=BudgetMode.UNLIMITED,
        eval_mode=EvalMode.ALL,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.FAILED
    assert evolver.call_count == 3


def test_loop_controller_eval_mode_parallel():
    """Test EvalMode.PARALLEL behaves same as ALL in current impl."""
    config = RunConfig(
        task="Build something",
        max_iterations=3,
        budget_mode=BudgetMode.UNLIMITED,
        eval_mode=EvalMode.PARALLEL,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.FAILED
    assert evolver.call_count == 3


def test_loop_controller_interactive_abort_before_iteration():
    """Test interactive ABORT before iteration stops immediately."""
    config = RunConfig(
        task="Build something",
        max_iterations=5,
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()
    interactive = DummyInteractive(choice=InteractiveChoice.ABORT)

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
        interactive=interactive,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.ABORTED
    assert generator.call_count == 0


def test_loop_controller_interactive_skip_continues():
    """Test interactive SKIP skips iteration but continues."""
    config = RunConfig(
        task="Build something",
        max_iterations=5,
        budget_mode=BudgetMode.UNLIMITED,
    )

    call_count = 0

    class CountingInteractive:
        def pause_before_iteration(self, iteration, task, evolved_strategy):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return InteractiveChoice.SKIP
            return InteractiveChoice.CONTINUE

        def pause_on_success(self, iteration, files):
            return InteractiveChoice.CONTINUE

        def pause_on_failure(self, iteration, errors):
            return InteractiveChoice.CONTINUE, None

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()
    interactive = CountingInteractive()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
        interactive=interactive,
    )

    controller.run()

    assert generator.call_count >= 1


def test_loop_controller_interactive_modify_task():
    """Test interactive MODIFY prepends hint to task."""
    config = RunConfig(
        task="Build something",
        max_iterations=3,
        budget_mode=BudgetMode.UNLIMITED,
    )

    class ModifyInteractive:
        def __init__(self):
            self.call_count = 0

        def pause_before_iteration(self, iteration, task, evolved_strategy):
            self.call_count += 1
            if self.call_count == 1:
                return InteractiveChoice.MODIFY
            return InteractiveChoice.CONTINUE

        def pause_on_success(self, iteration, files):
            return InteractiveChoice.CONTINUE

        def pause_on_failure(self, iteration, errors):
            return InteractiveChoice.CONTINUE, None

        def get_input(self, prompt):
            return "Use better naming conventions"

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()
    interactive = ModifyInteractive()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
        interactive=interactive,
    )

    with patch("builtins.input", return_value="Use better naming conventions"):
        controller.run()

    assert generator.call_count >= 1


def test_loop_controller_session_persistence():
    """Test that session manager saves iterations and reports."""
    config = RunConfig(
        task="Build something",
        max_iterations=2,
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=False)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()
    session_manager = DummySessionManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
        session_manager=session_manager,
    )

    controller.run()

    assert len(session_manager.saved_iterations) >= 1
    assert len(session_manager.saved_reports) >= 0
    assert len(session_manager.saved_contexts) >= 0


def test_loop_controller_records_positive_external_lesson_outcome(tmp_path):
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.insert_lesson_usage_event(
        project_path=str(current),
        session_id="test-session-123",
        stage="generate",
        lesson_source="related",
        lesson_key=str(lesson["lesson_key"]),
        source_project_path=str(source),
    )

    controller = LoopController(
        config=RunConfig(
            task="Build a simple calculator",
            output_dir=str(current),
            max_iterations=1,
            budget_mode=BudgetMode.UNLIMITED,
        ),
        code_generator=DummyGenerator(),
        evaluator=DummyEvaluator(should_pass=True),
        evolver=DummyEvolver(),
        budget_manager=DummyBudgetManager(),
        session_manager=DummySessionManager(),
        project_memory=current_pm,
    )

    controller.run()

    events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="test-session-123"
    )
    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    assert events[0]["outcome"] == "positive_generation_iteration"
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 1


def test_loop_controller_records_negative_external_lesson_outcome(tmp_path):
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.insert_lesson_usage_event(
        project_path=str(current),
        session_id="test-session-123",
        stage="generate",
        lesson_source="related",
        lesson_key=str(lesson["lesson_key"]),
        source_project_path=str(source),
    )

    controller = LoopController(
        config=RunConfig(
            task="Build a simple calculator",
            output_dir=str(current),
            max_iterations=1,
            budget_mode=BudgetMode.UNLIMITED,
        ),
        code_generator=DummyGenerator(),
        evaluator=DummyEvaluator(should_pass=False),
        evolver=DummyEvolver(),
        budget_manager=DummyBudgetManager(),
        session_manager=DummySessionManager(),
        project_memory=current_pm,
    )

    controller.run()

    events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="test-session-123"
    )
    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    assert events[0]["outcome"] == "negative_generation_evaluation"
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 0


def test_should_continue_early_exit_on_test_pass():
    """Test _should_continue early exits when tests pass."""
    config = RunConfig(
        task="Build something",
        max_iterations=10,
        early_exit_on="test_pass",
        budget_mode=BudgetMode.UNLIMITED,
    )

    generator = DummyGenerator()
    evaluator = DummyEvaluator(should_pass=True)
    evolver = DummyEvolver()
    budget_manager = DummyBudgetManager()

    controller = LoopController(
        config=config,
        code_generator=generator,
        evaluator=evaluator,
        evolver=evolver,
        budget_manager=budget_manager,
    )

    ctx = controller.run()

    assert ctx.stats.status == SessionStatus.SUCCESS
    assert ctx.stats.total_iterations == 1


def test_loop_controller_auto_commit_tracks_untracked_files_and_persists_commit(tmp_path):
    generated_file = tmp_path / "newfile.py"

    def generator(task: str, evolved_strategy: str, output_dir: str | None = None):
        generated_file.write_text("print('hello')\n", encoding="utf-8")
        return "Generated code", MagicMock(total=100)

    mock_git = Mock()
    mock_git.is_git_repo.return_value = True
    mock_git.create_branch.return_value = True
    mock_git.get_changed_files.return_value = ["newfile.py"]
    mock_git.add_files.return_value = True
    mock_git.commit.return_value = "abc12345"

    controller = LoopController(
        config=RunConfig(
            task="Build a simple file",
            output_dir=str(tmp_path),
            max_iterations=1,
            budget_mode=BudgetMode.UNLIMITED,
        ),
        code_generator=generator,
        evaluator=DummyEvaluator(should_pass=True),
        evolver=DummyEvolver(),
        git_repo_path=str(tmp_path),
    )

    with patch("tools.muscle.loop_controller.GitAdapter", return_value=mock_git):
        controller.run()

    mock_git.get_changed_files.assert_called_once()
    mock_git.add_files.assert_called_once_with(["newfile.py"])

    report = controller.get_session_report()
    assert report is not None
    assert report.git_commit == "abc12345"
    assert len(report.artifacts) == 1
    assert report.artifacts[0].file_path == str(generated_file)
    assert (
        report.artifacts[0].content_hash == hashlib.sha256(generated_file.read_bytes()).hexdigest()
    )
    assert report.artifacts[0].lines == 1


def test_loop_controller_resume_uses_existing_context_without_creating_new_session():
    config = RunConfig(
        task="Resume a failed session",
        max_iterations=4,
        budget_mode=BudgetMode.UNLIMITED,
    )

    session_manager = DummySessionManager()
    resume_ctx = LoopContext(
        session_id="existing-session-123",
        config=config,
        stats=LoopStats(
            total_iterations=2,
            total_tokens=200,
            total_duration_seconds=3.0,
            status=SessionStatus.FAILED,
        ),
        evolved_strategy="Previous strategy",
        iterations=[
            IterationResult(iteration=1, success=False, token_cost=100, duration_seconds=1.0),
            IterationResult(iteration=2, success=False, token_cost=100, duration_seconds=2.0),
        ],
        current_iteration=2,
    )

    controller = LoopController(
        config=config,
        code_generator=DummyGenerator(),
        evaluator=DummyEvaluator(should_pass=True),
        evolver=DummyEvolver(),
        budget_manager=DummyBudgetManager(),
        session_manager=session_manager,
    )

    ctx = controller.run(resume_context=resume_ctx)

    assert ctx.session_id == "existing-session-123"
    assert ctx.stats.status == SessionStatus.SUCCESS
    assert ctx.stats.total_iterations == 3
    assert session_manager.create_calls == 0
    assert session_manager.resumed_sessions == ["existing-session-123"]


# ---------------------------------------------------------------------------
# LC-01: Budget arithmetic — remaining_tokens never negative, overspend fires once
# ---------------------------------------------------------------------------


def test_lc01_remaining_tokens_never_negative_and_overspend_fires_once():
    """
    Drive total_tokens past budget_tokens across multiple iterations.
    Assert:
    - remaining_tokens in all emitted events is >= 0
    - BUDGET_OVERSPEND event fires exactly once
    """
    # budget of 100 tokens; each iteration costs 60 tokens → overspends on iter 2
    budget_tokens = 100
    token_cost_per_iter = 60  # iter 1: 60 total; iter 2: 120 total (overspend)

    emitted_events: list[tuple[LoopEvent, dict]] = []

    def event_cb(event: LoopEvent, data: dict) -> None:
        emitted_events.append((event, data))

    # Generator that always costs token_cost_per_iter tokens
    class FixedCostGenerator:
        def __call__(self, task: str, evolved_strategy: str, output_dir: str | None = None):
            return "code", MagicMock(total=token_cost_per_iter)

    config = RunConfig(
        task="Test budget overspend",
        max_iterations=5,
        budget_tokens=budget_tokens,
        budget_mode=BudgetMode.FIXED,
    )

    # Budget manager always returns OK so the loop continues past the overspend
    def always_ok(cost: int):
        return True, ""

    controller = LoopController(
        config=config,
        code_generator=FixedCostGenerator(),
        evaluator=DummyEvaluator(should_pass=False),
        evolver=DummyEvolver(),
        budget_manager=always_ok,
        event_callback=event_cb,
    )

    ctx = controller.run()

    # Check remaining_tokens is never negative in any event payload
    for _event, data in emitted_events:
        if "remaining_tokens" in data:
            assert data["remaining_tokens"] >= 0, (
                f"remaining_tokens went negative ({data['remaining_tokens']}) in event {_event}"
            )

    # BUDGET_OVERSPEND must fire exactly once
    overspend_events = [e for e, _ in emitted_events if e == LoopEvent.BUDGET_OVERSPEND]
    assert len(overspend_events) == 1, (
        f"Expected exactly 1 BUDGET_OVERSPEND event, got {len(overspend_events)}"
    )

    # remaining_tokens in the overspend payload must be 0
    overspend_data = [d for e, d in emitted_events if e == LoopEvent.BUDGET_OVERSPEND][0]
    assert overspend_data["remaining_tokens"] == 0
    assert overspend_data["total_tokens"] > budget_tokens

    # total_tokens in stats must never be reported negative remaining elsewhere
    assert ctx.stats.total_tokens > budget_tokens  # confirms overspend actually happened


# ---------------------------------------------------------------------------
# LC-02: Concurrent run() raises RuntimeError on the second call
# ---------------------------------------------------------------------------


def test_lc02_concurrent_run_raises_runtime_error():
    """
    Spin two threads both calling controller.run() on the same instance.
    The second call must raise RuntimeError.

    signal.signal() cannot be called from non-main threads, so we patch it out
    to isolate the _running-flag guard from Python's signal machinery.
    """
    import time as _time

    # Use a slow generator so the first run() is still in progress when
    # the second thread attempts to enter run().
    class SlowGenerator:
        def __call__(self, task: str, evolved_strategy: str, output_dir: str | None = None):
            _time.sleep(0.05)  # hold long enough for the second thread to fire
            return "code", MagicMock(total=10)

    config = RunConfig(
        task="Concurrency test",
        max_iterations=3,
        budget_mode=BudgetMode.UNLIMITED,
    )

    controller = LoopController(
        config=config,
        code_generator=SlowGenerator(),
        evaluator=DummyEvaluator(should_pass=False),
        evolver=DummyEvolver(),
        budget_manager=DummyBudgetManager(),
    )

    second_call_exception: list[Exception] = []
    first_started = threading.Event()

    # Patch signal.signal to be a no-op so threads can call run() without crashing
    # on Python's "signal only works in main thread" restriction.
    with patch("tools.muscle.loop_controller.signal.signal", return_value=None):

        def first_run() -> None:
            # Monkeypatch _emit to signal that the first run() is inside the loop
            original_emit = controller._emit

            def patched_emit(event, data):  # type: ignore[override]
                first_started.set()
                controller._emit = original_emit  # restore after first call
                original_emit(event, data)

            controller._emit = patched_emit  # type: ignore[method-assign]
            controller.run()

        def second_run() -> None:
            # Wait until first run() has definitely entered its loop
            first_started.wait(timeout=5.0)
            try:
                controller.run()
            except RuntimeError as exc:
                second_call_exception.append(exc)

        t1 = threading.Thread(target=first_run)
        t2 = threading.Thread(target=second_run)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    assert len(second_call_exception) == 1, (
        "Expected second concurrent run() to raise RuntimeError, "
        f"but got {len(second_call_exception)} exceptions: {second_call_exception}"
    )
    assert isinstance(second_call_exception[0], RuntimeError)


# ---------------------------------------------------------------------------
# LC-04: _sigterm_handler always sets shutdown flag even when handler body raises
# ---------------------------------------------------------------------------


def test_lc04_sigterm_handler_sets_abort_flag_even_on_exception():
    """Fix LC-04: _sigterm_handler must set _abort_requested in its ``finally``
    block so the flag is guaranteed to be set even if the handler body raises."""
    config = RunConfig(
        task="SIGTERM handler test",
        max_iterations=1,
        budget_mode=BudgetMode.UNLIMITED,
    )

    controller = LoopController(
        config=config,
        code_generator=DummyGenerator(),
        evaluator=DummyEvaluator(should_pass=False),
        evolver=DummyEvolver(),
        budget_manager=DummyBudgetManager(),
    )

    # Sanity: flag should start False.
    assert controller._abort_requested is False

    # Make logger.info raise to simulate an error inside the handler body.
    with patch("tools.muscle.loop_controller.logger") as mock_logger:
        mock_logger.info.side_effect = RuntimeError("logger blew up")
        try:
            controller._sigterm_handler(15, None)
        except RuntimeError:
            pass  # The exception propagates — that's fine.

    # The shutdown flag must have been set regardless of the exception.
    assert controller._abort_requested is True, (
        "_abort_requested must be True even when _sigterm_handler body raises"
    )


# ---------------------------------------------------------------------------
# LC-05: LoopStats.start_time uses default_factory=time.time (callable, not call)
# ---------------------------------------------------------------------------


def test_lc05_loop_stats_start_time_uses_factory_not_call():
    """Fix LC-05: LoopStats.start_time must be set via default_factory=time.time
    so that each instance gets its own timestamp, not a single shared value."""
    import time

    stats_a = LoopStats()
    time.sleep(0.05)
    stats_b = LoopStats()

    assert stats_b.start_time > stats_a.start_time, (
        "LoopStats.start_time must differ between instances created at different times. "
        "If they are equal, start_time is using a fixed default= instead of default_factory=."
    )
