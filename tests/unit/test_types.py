"""
Unit tests for SCLE types.
"""

from tools.muscle.types import (
    BudgetMode,
    EvalMode,
    EvaluationResult,
    IterationResult,
    LoopStats,
    RunConfig,
    SessionStatus,
)


def test_evaluation_result_all_errors():
    result = EvaluationResult(
        passed=False,
        compiler_errors=["SyntaxError"],
        test_failures=["Test failed"],
        linter_warnings=["Style warning"],
        assertion_failures=["Assertion error"],
    )

    assert result.passed is False
    assert len(result.all_errors) == 4
    assert result.has_warnings_only is False


def test_evaluation_result_warnings_only():
    result = EvaluationResult(
        passed=False,
        compiler_errors=[],
        test_failures=[],
        linter_warnings=["Style warning", "Formatting issue"],
        assertion_failures=[],
    )

    assert result.passed is False
    assert len(result.all_errors) == 2
    assert result.has_warnings_only is True


def test_evaluation_result_passed():
    result = EvaluationResult(
        passed=True,
        compiler_errors=[],
        test_failures=[],
        linter_warnings=["Minor style issue"],
        assertion_failures=[],
    )

    assert result.passed is True
    assert result.has_warnings_only is False


def test_run_config_defaults():
    config = RunConfig(task="Build a REST API")

    assert config.task == "Build a REST API"
    assert config.language is None
    assert config.output_dir == "."
    assert config.max_iterations == 20
    assert config.timeout_seconds == 3600
    assert config.budget_mode == BudgetMode.UNLIMITED
    assert config.eval_mode == EvalMode.ALL
    assert config.allow_warnings is False


def test_run_config_custom():
    config = RunConfig(
        task="Build a Go CLI",
        language="go",
        output_dir="./output",
        max_iterations=50,
        timeout_seconds=7200,
        budget_tokens=100000,
        budget_mode=BudgetMode.FIXED,
        eval_mode=EvalMode.SEQUENTIAL,
        allow_warnings=True,
    )

    assert config.language == "go"
    assert config.output_dir == "./output"
    assert config.max_iterations == 50
    assert config.timeout_seconds == 7200
    assert config.budget_mode == BudgetMode.FIXED
    assert config.eval_mode == EvalMode.SEQUENTIAL
    assert config.allow_warnings is True


def test_iteration_result():
    result = IterationResult(
        iteration=1,
        success=False,
        errors=["Error 1", "Error 2"],
        token_cost=2000,
        duration_seconds=5.5,
    )

    assert result.iteration == 1
    assert result.success is False
    assert len(result.errors) == 2
    assert result.token_cost == 2000


def test_loop_stats():
    stats = LoopStats()
    assert stats.total_iterations == 0
    assert stats.total_tokens == 0
    assert stats.total_duration_seconds == 0.0
    assert stats.status == SessionStatus.RUNNING
