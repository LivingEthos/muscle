"""
Unit tests for SCLE types.
"""

import pytest

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


def test_run_config_rejects_empty_task():
    with pytest.raises(ValueError, match="Task cannot be empty"):
        RunConfig(task="   ")


def test_run_config_rejects_negative_budget():
    with pytest.raises(ValueError, match="budget_tokens"):
        RunConfig(task="Build a REST API", budget_tokens=-1)


# TY-01: __post_init__ validation tests


def test_run_config_rejects_zero_max_iterations():
    with pytest.raises(ValueError, match="max_iterations"):
        RunConfig(task="Build a REST API", max_iterations=0)


def test_run_config_rejects_over_100_max_iterations():
    with pytest.raises(ValueError, match="max_iterations"):
        RunConfig(task="Build a REST API", max_iterations=101)


def test_run_config_rejects_zero_timeout_seconds():
    with pytest.raises(ValueError, match="timeout_seconds"):
        RunConfig(task="Build a REST API", timeout_seconds=0)


def test_run_config_rejects_negative_timeout_seconds():
    with pytest.raises(ValueError, match="timeout_seconds"):
        RunConfig(task="Build a REST API", timeout_seconds=-1)


def test_run_config_rejects_zero_max_task_length():
    with pytest.raises(ValueError, match="max_task_length must be > 0"):
        RunConfig(task="Build a REST API", max_task_length=0)


def test_run_config_rejects_task_exceeding_max_task_length():
    long_task = "x" * 200
    with pytest.raises(ValueError, match="exceeds max_task_length"):
        RunConfig(task=long_task, max_task_length=100)


def test_run_config_accepts_task_at_max_task_length():
    task = "x" * 100
    config = RunConfig(task=task, max_task_length=100)
    assert config.max_task_length == 100


def test_run_config_max_task_length_none_ignores_length():
    long_task = "x" * 50000
    # No error when max_task_length is None (default)
    config = RunConfig(task=long_task)
    assert config.max_task_length is None


def test_run_config_rejects_zero_max_timeout_seconds():
    with pytest.raises(ValueError, match="max_timeout_seconds must be > 0"):
        RunConfig(task="Build a REST API", max_timeout_seconds=0)


def test_run_config_rejects_negative_max_timeout_seconds():
    with pytest.raises(ValueError, match="max_timeout_seconds must be > 0"):
        RunConfig(task="Build a REST API", max_timeout_seconds=-5)


def test_run_config_accepts_valid_max_timeout_seconds():
    config = RunConfig(task="Build a REST API", max_timeout_seconds=3600)
    assert config.max_timeout_seconds == 3600


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
