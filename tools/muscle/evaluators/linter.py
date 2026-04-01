"""
Linters for various languages.

Architecture Decision Record (ADR):
- Each language has its own linter
- Returns list of warnings (non-fatal)
- Configurable to fail on warnings via allow_warnings flag
"""

import logging
import shutil
from pathlib import Path

from .base import BaseEvaluator, EvaluatorResult

logger = logging.getLogger(__name__)


class BlackLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "black_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("black"):
            logger.warning("black not found, skipping formatting check")
            return EvaluatorResult(success=True)

        path = Path(output_dir)
        check_path = str(path) if path.is_file() else "."
        code, stdout, stderr = self._run_command(
            ["black", "--check", "--diff", check_path], output_dir
        )

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if "would reformat" in line][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class RuffLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "ruff_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("ruff"):
            logger.warning("ruff not found, skipping lint check")
            return EvaluatorResult(success=True)

        path = Path(output_dir)
        check_path = str(path) if path.is_file() else "."
        code, stdout, stderr = self._run_command(["ruff", "check", check_path], output_dir)

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if line.strip()][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class EslintLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "eslint_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("eslint"):
            logger.warning("eslint not found, skipping lint check")
            return EvaluatorResult(success=True)

        path = Path(output_dir)
        check_path = str(path) if path.is_file() else "."
        code, stdout, stderr = self._run_command(
            ["eslint", "--format", "compact", check_path], output_dir
        )

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if line.strip()][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class GolangciLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "golangci_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("golangci-lint"):
            logger.warning("golangci-lint not found, skipping lint check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(["golangci-lint", "run", "./..."], output_dir)

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if line.strip()][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class ClippyLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "clippy_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("cargo"):
            logger.warning("cargo not found, skipping clippy check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["cargo", "clippy", "--", "-D", "warnings"], output_dir
        )

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if "warning:" in line][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class CppcheckLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "cppcheck_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("cppcheck"):
            logger.warning("cppcheck not found, skipping lint check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["cppcheck", "--enable=all", "--quiet", output_dir], output_dir
        )

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if line.strip()][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class CheckstyleLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "checkstyle_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("checkstyle"):
            logger.warning("checkstyle not found, skipping lint check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["checkstyle", "-c", "google", output_dir], output_dir
        )

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if line.strip()][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)


class DotnetLinter(BaseEvaluator):
    @property
    def name(self) -> str:
        return "dotnet_linter"

    @property
    def error_type(self) -> str:
        return "linter"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("dotnet"):
            logger.warning("dotnet not found, skipping lint check")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["dotnet", "format", "--verify-no-changes", output_dir], output_dir
        )

        warnings = []
        if code != 0:
            output = stdout + stderr
            warnings = [line for line in output.split("\n") if line.strip()][:20]

        return EvaluatorResult(success=code == 0, errors=warnings, output=stdout)
