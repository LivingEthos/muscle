"""
Base classes for evaluators.

Architecture Decision Record (ADR):
- Abstract base for all evaluators
- Each evaluator returns specific error types
- Unified interface for easy addition of new evaluators
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Fix: LC-06. 30s is well past what a healthy compile/lint/test step needs on
# generated artifacts and keeps loop iterations responsive. Longer-running
# evaluators should subclass and override.
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30
MAX_COMMAND_OUTPUT_CHARS = 20_000


@dataclass
class EvaluatorResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    output: str = ""


class BaseEvaluator(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def error_type(self) -> str:
        return "generic"

    @abstractmethod
    def evaluate(self, output_dir: str) -> EvaluatorResult:
        pass

    @staticmethod
    def _truncate_output(text: str) -> str:
        if len(text) <= MAX_COMMAND_OUTPUT_CHARS:
            return text
        return text[:MAX_COMMAND_OUTPUT_CHARS] + "\n... [truncated]"

    def _run_command(self, cmd: list[str], cwd: str) -> tuple[int, str, str]:
        import subprocess

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            )
            return (
                result.returncode,
                self._truncate_output(result.stdout),
                self._truncate_output(result.stderr),
            )
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {DEFAULT_COMMAND_TIMEOUT_SECONDS}s"
        except FileNotFoundError:
            return -2, "", f"Command not found: {cmd[0]}"
        except Exception as e:
            return -3, "", self._truncate_output(str(e))
