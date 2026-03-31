"""
Base classes for evaluators.

Architecture Decision Record (ADR):
- Abstract base for all evaluators
- Each evaluator returns specific error types
- Unified interface for easy addition of new evaluators
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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

    def _run_command(self, cmd: list[str], cwd: str) -> tuple[int, str, str]:
        import subprocess

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except FileNotFoundError:
            return -2, "", f"Command not found: {cmd[0]}"
        except Exception as e:
            return -3, "", str(e)
