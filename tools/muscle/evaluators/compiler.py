"""
Compiler evaluators for various languages.

Architecture Decision Record (ADR):
- Each language has its own compiler evaluator
- Returns list of compilation errors
- Gracefully handles missing compiler (skips with warning)
"""

import logging
import shutil
from pathlib import Path

from .base import BaseEvaluator, EvaluatorResult

logger = logging.getLogger(__name__)


class PythonCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "python_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("python3"):
            logger.warning("python3 not found, skipping compilation check")
            return EvaluatorResult(success=True)

        import py_compile

        errors = []
        path = Path(output_dir)

        if path.is_file():
            files_to_check = [path]
        else:
            files_to_check = list(path.rglob("*.py"))

        for py_file in files_to_check:
            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{py_file}: {str(e)}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)


class NodeCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "node_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("node"):
            logger.warning("node not found, skipping syntax check")
            return EvaluatorResult(success=True)

        errors = []
        path = Path(output_dir)

        if path.is_file():
            files_to_check = [path]
        else:
            files_to_check = list(path.rglob("*.js"))

        for js_file in files_to_check:
            code, stdout, stderr = self._run_command(["node", "--check", str(js_file)], output_dir)
            if code != 0:
                errors.append(f"{js_file}: {stderr or stdout}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)


class TscCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "tsc_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("tsc"):
            logger.warning("tsc not found, skipping TypeScript check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(["tsc", "--noEmit"], output_dir)

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = [line for line in output.split("\n") if line.strip()]

        return EvaluatorResult(success=code == 0, errors=errors)


class GoCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "go_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("go"):
            logger.warning("go not found, skipping build check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["go", "build", "-o", "/dev/null", "./..."], output_dir
        )

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = [line for line in output.split("\n") if line.strip()]

        return EvaluatorResult(success=code == 0, errors=errors)


class RustCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "rust_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("rustc"):
            logger.warning("rustc not found, skipping compilation check")
            return EvaluatorResult(success=True)

        errors = []
        path = Path(output_dir)

        if path.is_file():
            files_to_check = [path]
        else:
            files_to_check = list(path.rglob("*.rs"))

        for rs_file in files_to_check:
            code, stdout, stderr = self._run_command(
                ["rustc", "--emit=metadata", str(rs_file)], output_dir
            )
            if code != 0:
                errors.append(f"{rs_file}: {stderr or stdout}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)


class GppCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "gpp_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("g++"):
            logger.warning("g++ not found, skipping compilation check")
            return EvaluatorResult(success=True)

        errors = []
        path = Path(output_dir)

        if path.is_file():
            if path.suffix in (".cpp", ".cc", ".cxx"):
                files_to_check = [path]
            elif path.suffix == ".c":
                files_to_check = [path]
            else:
                files_to_check = []
        else:
            cpp_files = (
                list(path.rglob("*.cpp")) + list(path.rglob("*.cc")) + list(path.rglob("*.cxx"))
            )
            c_files = list(path.rglob("*.c"))
            files_to_check = cpp_files + c_files

        for c_file in files_to_check:
            if c_file.suffix == ".c":
                compiler, flags = "gcc", ["-fsyntax-only"]
            else:
                compiler, flags = "g++", ["-fsyntax-only", "-std=c++17"]
            code, stdout, stderr = self._run_command([compiler] + flags + [str(c_file)], output_dir)
            if code != 0:
                errors.append(f"{c_file}: {stderr or stdout}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)


class JavacCompiler(BaseEvaluator):
    @property
    def name(self) -> str:
        return "javac_compiler"

    @property
    def error_type(self) -> str:
        return "compiler"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("javac"):
            logger.warning("javac not found, skipping compilation check")
            return EvaluatorResult(success=True)

        errors = []
        path = Path(output_dir)

        if path.is_file():
            files_to_check = [path] if path.suffix == ".java" else []
        else:
            files_to_check = list(path.rglob("*.java"))

        for java_file in files_to_check:
            code, stdout, stderr = self._run_command(["javac", str(java_file)], output_dir)
            if code != 0:
                errors.append(f"{java_file}: {stderr or stdout}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)
