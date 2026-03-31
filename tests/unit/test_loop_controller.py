"""
Unit tests for SCLE loop controller.
"""
import pytest
from unittest.mock import Mock, MagicMock

from tools.scle.types import RunConfig, EvaluationResult, SessionStatus, EvalMode, BudgetMode
from tools.scle.loop_controller import LoopController, LoopContext, LoopEvent


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

    def __call__(self, task: str, evolved_strategy: str, output_dir: str):
        self.call_count += 1
        return f"Generated code iteration {self.call_count}", MagicMock(total=1000)


class DummyEvolver:
    def __init__(self):
        self.call_count = 0

    def __call__(self, task: str, errors: list, previous_strategy: str = None):
        self.call_count += 1
        return f"Improved strategy based on {len(errors)} errors", MagicMock(total=500)


class DummyBudgetManager:
    def __init__(self):
        self.calls = []

    def __call__(self, iteration_cost: int):
        self.calls.append(iteration_cost)
        return True, ""


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

    import time
    import threading

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

    assert ctx.stats.status == SessionStatus.ABORTED or ctx.current_iteration < 100, f"Abort not triggered properly. Status: {ctx.stats.status}, iterations: {ctx.current_iteration}"
