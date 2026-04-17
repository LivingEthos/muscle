"""
Data types and configuration for MUSCLE.

Architecture Decision Record (ADR):
- Using dataclasses for type-safe, immutable configurations
- Separating RunConfig from internal state for clean serialization
- Budget modes: unlimited, fixed, auto (reads from Token Plan)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .evaluators.base import EvaluatorResult


class EvalMode(Enum):
    ALL = "all"  # All errors at once to Evolver
    SEQUENTIAL = "seq"  # One error at a time
    PARALLEL = "par"  # Separate agents per evaluator type


class BudgetMode(Enum):
    UNLIMITED = "unlimited"
    FIXED = "fixed"
    AUTO = "auto"


class SessionStatus(Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass(frozen=True)
class RunConfig:
    task: str
    language: str | None = None
    output_dir: str = "."
    max_iterations: int = 20
    timeout_seconds: int = 3600
    budget_tokens: int = 0
    budget_mode: BudgetMode = BudgetMode.UNLIMITED
    eval_mode: EvalMode = EvalMode.ALL
    allow_warnings: bool = False
    interactive: bool = False
    kb_path: str | None = None
    max_cost_per_iteration: int | None = None
    early_exit_on: str | None = None
    max_task_length: int | None = None
    max_timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.task or not self.task.strip():
            raise ValueError("Task cannot be empty")
        if self.max_task_length is not None:
            if self.max_task_length <= 0:
                raise ValueError("max_task_length must be > 0")
            if len(self.task) > self.max_task_length:
                raise ValueError(
                    f"Task length {len(self.task)} exceeds max_task_length {self.max_task_length}"
                )
        if not 1 <= self.max_iterations <= 100:
            raise ValueError("max_iterations must be between 1 and 100")
        if self.max_timeout_seconds is not None and self.max_timeout_seconds <= 0:
            raise ValueError("max_timeout_seconds must be > 0")
        if not 1 <= self.timeout_seconds <= 86400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        if self.budget_tokens < 0:
            raise ValueError("budget_tokens must be non-negative")
        if self.max_cost_per_iteration is not None and self.max_cost_per_iteration < 0:
            raise ValueError("max_cost_per_iteration must be non-negative")


@dataclass
class IterationResult:
    iteration: int
    success: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    token_cost: int = 0
    duration_seconds: float = 0
    evolved_strategy: str | None = None
    artifacts_dir: str | None = None
    files_generated: list[str] = field(default_factory=list)


@dataclass
class LoopStats:
    total_iterations: int = 0
    total_tokens: int = 0
    total_duration_seconds: float = 0
    session_id: str | None = None
    status: SessionStatus = SessionStatus.RUNNING
    start_time: float = field(default_factory=time.time)


@dataclass
class EvaluationResult:
    passed: bool
    compiler_errors: list[str] = field(default_factory=list)
    test_failures: list[str] = field(default_factory=list)
    linter_warnings: list[str] = field(default_factory=list)
    assertion_failures: list[str] = field(default_factory=list)

    @property
    def all_errors(self) -> list[str]:
        return (
            self.compiler_errors
            + self.test_failures
            + self.linter_warnings
            + self.assertion_failures
        )

    @property
    def has_warnings_only(self) -> bool:
        return (
            self.passed is False
            and len(self.compiler_errors) == 0
            and len(self.test_failures) == 0
            and len(self.assertion_failures) == 0
            and len(self.linter_warnings) > 0
        )


@dataclass
class ParallelEvalResult:
    compiler_result: EvaluatorResult | None
    test_result: EvaluatorResult | None
    linter_result: EvaluatorResult | None
    duration_seconds: float


@dataclass
class BudgetInfo:
    mode: BudgetMode
    limit: int
    spent: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    @property
    def percentage(self) -> float:
        if self.limit == 0:
            return 0.0
        return max(0.0, min(100.0, (self.spent / self.limit) * 100))


@dataclass
class CodeArtifact:
    file_path: str
    content_hash: str
    language: str
    lines: int


@dataclass
class IterationReport:
    iteration: int
    success: bool
    errors: list[str]
    warnings: list[str]
    token_cost: int
    duration_seconds: float
    files_generated: list[str]
    evolved_strategy: str | None


@dataclass
class SessionReport:
    session_id: str
    task: str
    status: SessionStatus
    total_iterations: int
    total_tokens: int
    total_duration_seconds: float
    iterations: list[IterationReport]
    final_strategy: str | None
    artifacts: list[CodeArtifact]
    budget_info: BudgetInfo | None
    git_commit: str | None
