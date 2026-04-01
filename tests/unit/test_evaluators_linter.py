"""
Unit tests for evaluators/linter.py
"""

from unittest.mock import Mock

from tools.muscle.evaluators.linter import (
    BlackLinter,
    CheckstyleLinter,
    ClippyLinter,
    CppcheckLinter,
    DotnetLinter,
    EslintLinter,
    GolangciLinter,
    RuffLinter,
)


class TestRuffLinter:
    def test_name(self):
        assert RuffLinter().name == "ruff_linter"

    def test_error_type(self):
        assert RuffLinter().error_type == "linter"

    def test_tool_not_found_returns_success(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = RuffLinter().evaluate("/fake/path")
        assert result.success is True

    def test_clean_run(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/ruff"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = RuffLinter().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_violations_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/ruff"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="test.py:1: F401 'os' imported but unused\ntest.py:3: E302 expected 2 blank lines",
        )
        result = RuffLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestBlackLinter:
    def test_name(self):
        assert BlackLinter().name == "black_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = BlackLinter().evaluate("/fake/path")
        assert result.success is True

    def test_would_reformat_filtered(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/black"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="would reformat test.py\nOh no!",
        )
        result = BlackLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestEslintLinter:
    def test_name(self):
        assert EslintLinter().name == "eslint_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = EslintLinter().evaluate("/fake/path")
        assert result.success is True

    def test_violations_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/eslint"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="/path/file.js: line 1: error\n/path/file.js: line 2: warning",
        )
        result = EslintLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestGolangciLinter:
    def test_name(self):
        assert GolangciLinter().name == "golangci_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = GolangciLinter().evaluate("/fake/path")
        assert result.success is True

    def test_violations_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/golangci-lint"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="file.go:10: error message\nfile.go:20: another error",
        )
        result = GolangciLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestClippyLinter:
    def test_name(self):
        assert ClippyLinter().name == "clippy_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = ClippyLinter().evaluate("/fake/path")
        assert result.success is True


class TestCppcheckLinter:
    def test_name(self):
        assert CppcheckLinter().name == "cppcheck_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = CppcheckLinter().evaluate("/fake/path")
        assert result.success is True

    def test_violations_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/cppcheck"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="/path/file.cpp:10: error: something\n/path/file.cpp:20: style: another",
        )
        result = CppcheckLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestCheckstyleLinter:
    def test_name(self):
        assert CheckstyleLinter().name == "checkstyle_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = CheckstyleLinter().evaluate("/fake/path")
        assert result.success is True

    def test_clean_run(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/checkstyle"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = CheckstyleLinter().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_violations_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/checkstyle"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="error: Some checkstyle error\nerror: Another checkstyle error",
        )
        result = CheckstyleLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0


class TestDotnetLinter:
    def test_name(self):
        assert DotnetLinter().name == "dotnet_linter"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = DotnetLinter().evaluate("/fake/path")
        assert result.success is True

    def test_clean_run(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/dotnet"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = DotnetLinter().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_violations_collected(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/dotnet"
        mock_subprocess.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="dotnet format error: file.cs(10,1): error\nfile.cs(20,5): error",
        )
        result = DotnetLinter().evaluate("/fake/path")
        assert result.success is False
        assert len(result.errors) > 0
