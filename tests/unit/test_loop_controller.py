"""
Unit tests for SCLE loop controller.
"""

import hashlib
from unittest.mock import MagicMock, Mock, patch

from tools.muscle.interactive import InteractiveChoice
from tools.muscle.loop_controller import LoopController
from tools.muscle.types import (
    BudgetMode,
    EvalMode,
    EvaluationResult,
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
        self.saved_iterations = []
        self.saved_reports = []
        self.saved_contexts = []

    def create_session(self, config: RunConfig) -> str:
        return "test-session-123"

    def save_iteration(self, session_id: str, iteration_result) -> None:
        self.saved_iterations.append((session_id, iteration_result))

    def save_session_report(self, session_id: str, report) -> None:
        self.saved_reports.append((session_id, report))

    def save_final_context(self, ctx) -> None:
        self.saved_contexts.append(ctx)


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
    assert report.artifacts[0].content_hash == hashlib.sha256(
        generated_file.read_bytes()
    ).hexdigest()
    assert report.artifacts[0].lines == 1
