"""
Unit tests for evaluators/tester.py
"""

from pathlib import Path
from unittest.mock import Mock, patch

from tools.muscle.evaluators.tester import (
    CargoTestRunner,
    GoTestRunner,
    GtestRunner,
    JestRunner,
    JUnitRunner,
    PytestRunner,
)


class TestPytestRunner:
    def test_name(self):
        assert PytestRunner().name == "pytest_runner"

    def test_error_type(self):
        assert PytestRunner().error_type == "test"

    def test_tool_not_found_returns_success(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = PytestRunner().evaluate("/fake/path")
        assert result.success is True

    def test_all_pass(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/pytest"
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="3 passed in 0.5s",
            stderr="",
        )
        result = PytestRunner().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_failures_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/pytest"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="FAILED test_foo.py::test_bar\nAssertionError: expected 1 got 2",
        )
        result = PytestRunner().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestJestRunner:
    def test_name(self):
        assert JestRunner().name == "jest_runner"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = JestRunner().evaluate("/fake/path")
        assert result.success is True

    def test_all_pass(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/jest"
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="Tests: 5 passed",
            stderr="",
        )
        result = JestRunner().evaluate("/fake/path")
        assert result.success is True


class TestGoTestRunner:
    def test_name(self):
        assert GoTestRunner().name == "go_test_runner"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = GoTestRunner().evaluate("/fake/path")
        assert result.success is True

    def test_all_pass(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/go"
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="ok  \tgithub.com/user/project\t0.123s",
            stderr="",
        )
        result = GoTestRunner().evaluate("/fake/path")
        assert result.success is True


class TestCargoTestRunner:
    def test_name(self):
        assert CargoTestRunner().name == "cargo_test_runner"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = CargoTestRunner().evaluate("/fake/path")
        assert result.success is True

    def test_all_pass(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/cargo"
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="test result: ok. 5 passed in 1.23s",
            stderr="",
        )
        result = CargoTestRunner().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_failures_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/cargo"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="test result: FAILED. 2 passed in 0.5s",
            stderr="",
        )
        result = CargoTestRunner().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestGtestRunner:
    def test_name(self):
        assert GtestRunner().name == "gtest_runner"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = GtestRunner().evaluate("/fake/path")
        assert result.success is True

    def test_build_dir_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/cmake"
        with patch.object(Path, "exists", return_value=False):
            result = GtestRunner().evaluate("/fake/path")
        assert result.success is True


class TestJUnitRunner:
    def test_name(self):
        assert JUnitRunner().name == "junit_runner"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = JUnitRunner().evaluate("/fake/path")
        assert result.success is True

    def test_all_pass(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/java"
        mock_subprocess.return_value = Mock(returncode=0, stdout="JUnit running...", stderr="")
        result = JUnitRunner().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_failures_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/java"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="There were some test failures. Error: testFoo",
        )
        result = JUnitRunner().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0
