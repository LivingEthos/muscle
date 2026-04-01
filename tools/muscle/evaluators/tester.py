"""
Test runners for various languages.

Architecture Decision Record (ADR):
- Each language has its own test runner
- Returns list of test failures
- Gracefully handles missing test framework
"""

import logging
import shutil
from pathlib import Path

from .base import BaseEvaluator, EvaluatorResult

logger = logging.getLogger(__name__)


class PytestRunner(BaseEvaluator):
    @property
    def name(self) -> str:
        return "pytest_runner"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("pytest"):
            logger.warning("pytest not found, skipping test run")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(["pytest", "--tb=short", "-v", "."], output_dir)

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = self._parse_pytest_output(output)

        return EvaluatorResult(success=code == 0, errors=errors, output=stdout)

    def _parse_pytest_output(self, output: str) -> list[str]:
        errors = []
        for line in output.split("\n"):
            if "FAILED" in line or "ERROR" in line:
                errors.append(line.strip())
        return errors[:20]


class JestRunner(BaseEvaluator):
    @property
    def name(self) -> str:
        return "jest_runner"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("jest"):
            logger.warning("jest not found, skipping test run")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(["jest", "."], output_dir)

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = self._parse_jest_output(output)

        return EvaluatorResult(success=code == 0, errors=errors, output=stdout)

    def _parse_jest_output(self, output: str) -> list[str]:
        errors = []
        for line in output.split("\n"):
            if "FAIL" in line or "● " in line:
                errors.append(line.strip())
        return errors[:20]


class GoTestRunner(BaseEvaluator):
    @property
    def name(self) -> str:
        return "go_test_runner"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("go"):
            logger.warning("go not found, skipping test run")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(["go", "test", "-v", "./..."], output_dir)

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = self._parse_go_test_output(output)

        return EvaluatorResult(success=code == 0, errors=errors, output=stdout)

    def _parse_go_test_output(self, output: str) -> list[str]:
        errors = []
        for line in output.split("\n"):
            if "FAIL" in line or "--- FAIL" in line:
                errors.append(line.strip())
        return errors[:20]


class CargoTestRunner(BaseEvaluator):
    @property
    def name(self) -> str:
        return "cargo_test_runner"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("cargo"):
            logger.warning("cargo not found, skipping test run")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["cargo", "test", "--message-format=short"], output_dir
        )

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = self._parse_cargo_output(output)

        return EvaluatorResult(success=code == 0, errors=errors, output=stdout)

    def _parse_cargo_output(self, output: str) -> list[str]:
        errors = []
        for line in output.split("\n"):
            if "test result: FAILED" in line or "FAILED" in line:
                errors.append(line.strip())
        return errors[:20]


class GtestRunner(BaseEvaluator):
    @property
    def name(self) -> str:
        return "gtest_runner"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("cmake") or not shutil.which("make"):
            logger.warning("cmake or make not found, skipping gtest run")
            return EvaluatorResult(success=True)

        build_dir = Path(output_dir) / "build"
        if not build_dir.exists():
            logger.info("No build directory found, skipping tests")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(["ctest", "--output-on-failure"], str(build_dir))

        errors = []
        if code != 0:
            output = stdout + stderr
            errors = [line for line in output.split("\n") if "Failed" in line or "ERROR" in line][
                :20
            ]

        return EvaluatorResult(success=code == 0, errors=errors, output=stdout)


class JUnitRunner(BaseEvaluator):
    @property
    def name(self) -> str:
        return "junit_runner"

    @property
    def error_type(self) -> str:
        return "test"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not shutil.which("java"):
            logger.warning("java not found, skipping test run")
            return EvaluatorResult(success=True)

        code, stdout, stderr = self._run_command(
            ["java", "-jar", "junit.jar", "org.junit.runner.JUnitCore", output_dir], output_dir
        )

        errors = []
        if code != 0:
            errors = stderr.split("\n")
            errors = [e for e in errors if "FAILURES" in e or "Error" in e][:20]

        return EvaluatorResult(success=code == 0, errors=errors, output=stdout)
