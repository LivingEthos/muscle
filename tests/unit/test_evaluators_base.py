"""
Unit tests for evaluators/base.py
"""

from subprocess import TimeoutExpired
from unittest.mock import Mock, patch

from tools.muscle.evaluators.base import BaseEvaluator, EvaluatorResult


class ConcreteEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "test-evaluator"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        return EvaluatorResult(success=True)


class TestEvaluatorResult:
    def test_defaults(self):
        result = EvaluatorResult(success=True)
        assert result.success is True
        assert result.errors == []
        assert result.output == ""

    def test_with_errors(self):
        result = EvaluatorResult(success=False, errors=["Error 1", "Error 2"], output="stderr")
        assert result.success is False
        assert len(result.errors) == 2
        assert result.output == "stderr"


class TestBaseEvaluator:
    def test_name_property(self):
        evaluator = ConcreteEvaluator()
        assert evaluator.name == "test-evaluator"

    def test_error_type_property(self):
        assert ConcreteEvaluator().error_type == "test"

    def test_run_command_success(self):
        evaluator = ConcreteEvaluator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="output", stderr="")
            returncode, stdout, stderr = evaluator._run_command(["echo", "test"], cwd=".")
            assert returncode == 0
            assert stdout == "output"

    def test_run_command_failure(self):
        evaluator = ConcreteEvaluator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="error")
            returncode, stdout, stderr = evaluator._run_command(["false"], cwd=".")
            assert returncode == 1
            assert stderr == "error"

    def test_run_command_timeout(self):
        evaluator = ConcreteEvaluator()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutExpired("cmd", 123)
            returncode, stdout, stderr = evaluator._run_command(["sleep", "10"], cwd=".")
            assert returncode == -1
            assert "timed out" in stderr.lower()

    def test_run_command_not_found(self):
        evaluator = ConcreteEvaluator()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("command not found")
            returncode, stdout, stderr = evaluator._run_command(["nonexistent"], cwd=".")
            assert returncode == -2
            assert "not found" in stderr.lower()

    def test_run_command_generic_exception(self):
        evaluator = ConcreteEvaluator()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("unexpected error")
            returncode, stdout, stderr = evaluator._run_command(["echo"], cwd=".")
            assert returncode == -3
            assert "unexpected error" in stderr.lower()
