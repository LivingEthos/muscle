"""
Unit tests for evaluators/compiler.py
"""

from pathlib import Path
from unittest.mock import Mock, patch

from tools.muscle.evaluators.compiler import (
    GoCompiler,
    GppCompiler,
    JavacCompiler,
    NodeCompiler,
    PythonCompiler,
    RustCompiler,
    TscCompiler,
)


class TestPythonCompiler:
    def test_name(self):
        assert PythonCompiler().name == "python_compiler"

    def test_error_type(self):
        assert PythonCompiler().error_type == "compiler"

    def test_tool_not_found_returns_success(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = PythonCompiler().evaluate("/fake/path")
        assert result.success is True

    def test_compilation_success(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/python"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = PythonCompiler().evaluate("/fake/path")
        assert result.success is True
        assert result.errors == []

    def test_compilation_errors_collected(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/python"
        (tmp_path / "bad.py").write_text("x = ")

        import py_compile

        with patch(
            "py_compile.compile",
            side_effect=py_compile.PyCompileError(
                SyntaxError, SyntaxError("invalid syntax"), "bad.py"
            ),
        ):
            result = PythonCompiler().evaluate(str(tmp_path))
        assert result.success is False
        assert len(result.errors) > 0

    def test_multiple_files(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/python"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")

        (tmp_path / "a.py").write_text("x = 1")
        (tmp_path / "b.py").write_text("y = 2")

        with patch.object(Path, "rglob", return_value=[tmp_path / "a.py", tmp_path / "b.py"]):
            result = PythonCompiler().evaluate(str(tmp_path))
        assert result.success is True


class TestNodeCompiler:
    def test_name(self):
        assert NodeCompiler().name == "node_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = NodeCompiler().evaluate("/fake/path")
        assert result.success is True

    def test_compilation_success(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/node"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = NodeCompiler().evaluate("/fake/path")
        assert result.success is True


class TestTscCompiler:
    def test_name(self):
        assert TscCompiler().name == "tsc_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = TscCompiler().evaluate("/fake/path")
        assert result.success is True

    def test_tsconfig_invocation(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/tsc"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = TscCompiler().evaluate("/fake/path")
        assert result.success is True
        args = mock_subprocess.call_args[0][0]
        assert "--noEmit" in args
        assert args == ["tsc", "--noEmit"]


class TestGoCompiler:
    def test_name(self):
        assert GoCompiler().name == "go_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = GoCompiler().evaluate("/fake/path")
        assert result.success is True

    def test_go_build_invocation(self, mock_subprocess, mock_shutil_which):
        mock_shutil_which.return_value = "/usr/bin/go"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        result = GoCompiler().evaluate("/fake/path")
        assert result.success is True
        args = mock_subprocess.call_args[0][0]
        assert "build" in args
        assert "-o" in args


class TestRustCompiler:
    def test_name(self):
        assert RustCompiler().name == "rust_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = RustCompiler().evaluate("/fake/path")
        assert result.success is True


class TestGppCompiler:
    def test_name(self):
        assert GppCompiler().name == "gpp_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = GppCompiler().evaluate("/fake/path")
        assert result.success is True


class TestJavacCompiler:
    def test_name(self):
        assert JavacCompiler().name == "javac_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = JavacCompiler().evaluate("/fake/path")
        assert result.success is True
