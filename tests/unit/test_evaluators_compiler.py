"""
Unit tests for evaluators/compiler.py
"""

import logging
from pathlib import Path
from unittest.mock import Mock, patch

from tools.muscle.evaluators.compiler import (
    _STDERR_MAX_BYTES,
    GoCompiler,
    GppCompiler,
    JavacCompiler,
    NodeCompiler,
    PythonCompiler,
    RustCompiler,
    TscCompiler,
    _cap_stderr,
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

    def test_compilation_success(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/rustc"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        (tmp_path / "main.rs").write_text("fn main() {}")
        with patch.object(Path, "rglob", return_value=[tmp_path / "main.rs"]):
            result = RustCompiler().evaluate(str(tmp_path))
        assert result.success is True

    def test_compilation_errors_collected(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/rustc"
        mock_subprocess.return_value = Mock(
            returncode=1, stdout="", stderr="error: expected semicolon"
        )
        (tmp_path / "bad.rs").write_text("fn main() {}")
        with patch.object(Path, "rglob", return_value=[tmp_path / "bad.rs"]):
            result = RustCompiler().evaluate(str(tmp_path))
        assert result.success is False
        assert len(result.errors) > 0


class TestGppCompiler:
    def test_name(self):
        assert GppCompiler().name == "gpp_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = GppCompiler().evaluate("/fake/path")
        assert result.success is True

    def test_compilation_success(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/g++"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        (tmp_path / "main.cpp").write_text("int main() {}")
        with patch.object(Path, "rglob", return_value=[tmp_path / "main.cpp"]):
            result = GppCompiler().evaluate(str(tmp_path))
        assert result.success is True

    def test_compilation_errors_collected(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/g++"
        mock_subprocess.return_value = Mock(
            returncode=1, stdout="", stderr="error: expected semicolon"
        )
        (tmp_path / "bad.cpp").write_text("int main() {}")
        with patch.object(Path, "rglob", return_value=[tmp_path / "bad.cpp"]):
            result = GppCompiler().evaluate(str(tmp_path))
        assert result.success is False
        assert len(result.errors) > 0


# EV-T1: stderr capped at 5 KB


class TestCapStderr:
    def test_short_stderr_unchanged(self):
        short = "error: something went wrong"
        assert _cap_stderr(short) == short

    def test_long_stderr_truncated(self, caplog):
        big_stderr = "e" * (_STDERR_MAX_BYTES + 100)
        with caplog.at_level(logging.WARNING, logger="tools.muscle.evaluators.compiler"):
            result = _cap_stderr(big_stderr)
        assert len(result) < len(big_stderr)
        assert result.endswith("... [stderr truncated]")
        # Log must mention the original length
        assert any(str(len(big_stderr)) in r.message for r in caplog.records)

    def test_exactly_at_limit_not_truncated(self):
        exact = "x" * _STDERR_MAX_BYTES
        result = _cap_stderr(exact)
        assert result == exact
        assert "truncated" not in result


class TestNodeCompilerStderrCap:
    """EV-T1: NodeCompiler must cap stderr in error messages."""

    def test_large_stderr_is_truncated_in_error(self, mock_shutil_which, tmp_path, caplog):
        mock_shutil_which.return_value = "/usr/bin/node"
        big_stderr = "E" * (_STDERR_MAX_BYTES + 500)

        (tmp_path / "bad.js").write_text("{{{{")

        with patch(
            "tools.muscle.evaluators.compiler.NodeCompiler._run_command",
            return_value=(1, "", big_stderr),
        ):
            with caplog.at_level(logging.WARNING, logger="tools.muscle.evaluators.compiler"):
                result = NodeCompiler().evaluate(str(tmp_path))

        assert result.success is False
        assert len(result.errors) > 0
        error_text = result.errors[0]
        # The captured error must be smaller than the original stderr
        assert len(error_text) < len(big_stderr) + 100  # +100 for filename prefix
        # Log must warn about truncation including original length
        assert any(str(len(big_stderr)) in r.message for r in caplog.records)


class TestJavacCompiler:
    def test_name(self):
        assert JavacCompiler().name == "javac_compiler"

    def test_tool_not_found(self, mock_shutil_which):
        mock_shutil_which.return_value = None
        result = JavacCompiler().evaluate("/fake/path")
        assert result.success is True

    def test_compilation_success(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/javac"
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        (tmp_path / "Main.java").write_text("public class Main {}")
        with patch.object(Path, "rglob", return_value=[tmp_path / "Main.java"]):
            result = JavacCompiler().evaluate(str(tmp_path))
        assert result.success is True

    def test_compilation_errors_collected(self, mock_subprocess, mock_shutil_which, tmp_path):
        mock_shutil_which.return_value = "/usr/bin/javac"
        mock_subprocess.return_value = Mock(
            returncode=1, stdout="", stderr="error: cannot find symbol"
        )
        (tmp_path / "Bad.java").write_text("public class Bad {}")
        with patch.object(Path, "rglob", return_value=[tmp_path / "Bad.java"]):
            result = JavacCompiler().evaluate(str(tmp_path))
        assert result.success is False
        assert len(result.errors) > 0
