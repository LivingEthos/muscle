"""
Custom assertions for MUSCLE.

Architecture Decision Record (ADR):
- Allows user-defined validation beyond standard compile/test/lint
- Benchmark runners for performance validation
- Output validators for specific format requirements
"""

import logging
from pathlib import Path

from .base import BaseEvaluator, EvaluatorResult

logger = logging.getLogger(__name__)


class DummyEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "dummy_evaluator"

    @property
    def error_type(self) -> str:
        return "assertion"

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        logger.info("Dummy evaluator: always passes")
        return EvaluatorResult(success=True, output="No specific assertions defined")


class BenchmarkEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "benchmark_evaluator"

    @property
    def error_type(self) -> str:
        return "assertion"

    def __init__(self, benchmark_cmd: str | None = None, max_time_seconds: float = 10.0):
        self.benchmark_cmd = benchmark_cmd
        self.max_time_seconds = max_time_seconds

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        if not self.benchmark_cmd:
            return EvaluatorResult(success=True, output="No benchmark command defined")

        code, stdout, stderr = self._run_command(self.benchmark_cmd.split(), output_dir)

        errors = []
        if code != 0:
            errors.append(f"Benchmark failed: {stderr or stdout}")
        else:
            output = stdout + stderr
            if "time" in output.lower():
                import re

                time_match = re.search(r"(\d+\.?\d*)\s*(ms|s)", output)
                if time_match:
                    time_value = float(time_match.group(1))
                    time_unit = time_match.group(2)
                    if time_unit == "s":
                        time_value *= 1000
                    if time_value > self.max_time_seconds * 1000:
                        errors.append(
                            f"Benchmark too slow: {time_value}ms > {self.max_time_seconds * 1000}ms"
                        )

        return EvaluatorResult(
            success=len(errors) == 0,
            errors=errors,
            output=stdout,
            evidence=self.last_command_evidence,
        )


class OutputFormatEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "output_format_evaluator"

    @property
    def error_type(self) -> str:
        return "assertion"

    def __init__(
        self,
        required_files: list[str] | None = None,
        required_patterns: dict[str, str] | None = None,
    ):
        self.required_files = required_files or []
        self.required_patterns = required_patterns or {}

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        errors = []
        path = Path(output_dir)

        for req_file in self.required_files:
            file_path = path / req_file
            if not file_path.exists():
                errors.append(f"Required file missing: {req_file}")

        for file_pattern, pattern in self.required_patterns.items():
            matching_files = list(path.rglob(file_pattern))
            if not matching_files:
                errors.append(f"No files matching {file_pattern} found")
                continue

            content = matching_files[0].read_text()
            if pattern not in content:
                errors.append(f"Pattern {pattern} not found in {matching_files[0]}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)


class SecurityEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "security_evaluator"

    @property
    def error_type(self) -> str:
        return "assertion"

    def __init__(self, checks: list[str] | None = None):
        self.checks = checks or ["secrets", "sql_injection", "hardcoded_credentials"]

    def evaluate(self, output_dir: str) -> EvaluatorResult:
        errors = []
        path = Path(output_dir)

        secrets_patterns = ["password", "api_key", "secret", "token", "credentials"]

        for check in self.checks:
            if check == "secrets":
                for py_file in path.rglob("*.py"):
                    content = py_file.read_text().lower()
                    for pattern in secrets_patterns:
                        if f'"{pattern}"' in content or f"'{pattern}'" in content:
                            if "password" in pattern and "validate_password" not in content:
                                errors.append(f"Potential hardcoded secret in {py_file}: {pattern}")

        return EvaluatorResult(success=len(errors) == 0, errors=errors)
