"""
Base classes for evaluators.

Architecture Decision Record (ADR):
- Abstract base for all evaluators
- Each evaluator returns specific error types
- Unified interface for easy addition of new evaluators
- Command execution records compact, recoverable evidence for diagnostics
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..command_evidence import (
    CommandEvidence,
    ParserTier,
    compact_output,
    run_command_with_evidence,
)

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
    evidence: CommandEvidence | None = None


class BaseEvaluator(ABC):
    def __init__(self) -> None:
        self.last_command_evidence: CommandEvidence | None = None

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
        code, stdout, stderr, evidence = run_command_with_evidence(
            cmd,
            cwd,
            timeout_seconds=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            parser_tier=ParserTier.FULL,
            compact_max_chars=MAX_COMMAND_OUTPUT_CHARS,
        )
        self.last_command_evidence = evidence
        return code, self._truncate_output(stdout), self._truncate_output(stderr)

    def _result(
        self,
        *,
        success: bool,
        errors: list[str] | None = None,
        output: str = "",
        evidence: CommandEvidence | None = None,
    ) -> EvaluatorResult:
        """Build an evaluator result with the latest command evidence attached."""
        return EvaluatorResult(
            success=success,
            errors=errors or [],
            output=compact_output(output, MAX_COMMAND_OUTPUT_CHARS)[0],
            evidence=evidence or self.last_command_evidence,
        )
