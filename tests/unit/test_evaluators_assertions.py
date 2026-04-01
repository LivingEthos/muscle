"""
Unit tests for evaluators/assertions.py
"""

from pathlib import Path
from unittest.mock import Mock, patch

from tools.muscle.evaluators.assertions import (
    BenchmarkEvaluator,
    DummyEvaluator,
    OutputFormatEvaluator,
    SecurityEvaluator,
)


class TestDummyEvaluator:
    def test_always_passes(self):
        evaluator = DummyEvaluator()
        result = evaluator.evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []


class TestBenchmarkEvaluator:
    def test_no_benchmark_command(self):
        evaluator = BenchmarkEvaluator()
        result = evaluator.evaluate("/fake/path")
        assert result.success is True

    def test_benchmark_pass(self, mock_subprocess):
        evaluator = BenchmarkEvaluator(benchmark_cmd="python benchmark.py", max_time_seconds=10.0)
        mock_subprocess.return_value = Mock(returncode=0, stdout="Time: 0.5s", stderr="")
        with patch("re.search", return_value=Mock(group=lambda i: "0.5" if i == 1 else "s")):
            result = evaluator.evaluate("/fake/path")
        assert result.success is True

    def test_benchmark_timeout(self, mock_subprocess):
        evaluator = BenchmarkEvaluator(benchmark_cmd="sleep 100", max_time_seconds=1.0)
        mock_subprocess.return_value = Mock(returncode=0, stdout="Time: 5.0s", stderr="")
        with patch("re.search", return_value=Mock(group=lambda i: "5.0" if i == 1 else "s")):
            result = evaluator.evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0

    def test_benchmark_failure(self, mock_subprocess):
        evaluator = BenchmarkEvaluator(benchmark_cmd="python benchmark.py")
        mock_subprocess.return_value = Mock(returncode=1, stdout="", stderr="Benchmark failed")
        result = evaluator.evaluate("/fake/path")
        assert result.success is False


class TestOutputFormatEvaluator:
    def test_required_files_missing(self):
        evaluator = OutputFormatEvaluator(required_files=["README.md", "setup.py"])
        with patch.object(Path, "exists", return_value=False):
            result = evaluator.evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0

    def test_required_pattern_not_found(self):
        evaluator = OutputFormatEvaluator(
            required_files=["README.md"],
            required_patterns={"README.md": "Installation"},
        )
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", return_value="No useful content"):
                result = evaluator.evaluate("/fake/path")
        assert result.success is False

    def test_all_required_present(self):
        evaluator = OutputFormatEvaluator(required_files=["README.md"])
        with patch.object(Path, "exists", return_value=True):
            result = evaluator.evaluate("/fake/path")
        assert result.success is True


class TestSecurityEvaluator:
    def test_no_password_in_code(self):
        evaluator = SecurityEvaluator(checks=["password"])
        with patch.object(Path, "rglob", return_value=[]):
            result = evaluator.evaluate("/fake/path")
        assert result.success is True

    def test_password_found_without_validation(self):
        evaluator = SecurityEvaluator(checks=["secrets"])
        with patch.object(Path, "rglob", return_value=[Path("auth.py")]):
            with patch.object(Path, "read_text", return_value='"password" = "secret123"'):
                result = evaluator.evaluate("/fake/path")
        assert result.success is False

    def test_password_found_with_validation_function(self):
        evaluator = SecurityEvaluator(checks=["password"])
        with patch.object(Path, "rglob", return_value=[Path("auth.py")]):
            with patch.object(
                Path,
                "read_text",
                return_value="def validate_password(pwd):\n    pass\npassword = 'secret'",
            ):
                result = evaluator.evaluate("/fake/path")
        assert result.success is True
