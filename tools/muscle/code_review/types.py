"""
Code Review types for MUSCLE.

Architecture Decision Record (ADR):
- 5-level severity taxonomy aligned with CWE for AI-to-AI accuracy
- Separate types for review issues, handoff plans, and fix results
- Immutable ReviewConfig, mutable ReviewResult for state tracking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1


class IssueCategory(Enum):
    SECURITY = "security"
    CORRECTNESS = "correctness"
    PERFORMANCE = "performance"
    STYLE = "style"
    DOCUMENTATION = "documentation"
    BEST_PRACTICE = "best_practice"


@dataclass(frozen=True)
class ReviewIssue:
    file_path: str
    line_number: int
    severity: Severity
    category: IssueCategory
    cwe_id: str | None
    title: str
    description: str
    code_snippet: str
    suggested_fix: str | None = None
    auto_fixable: bool = False


@dataclass
class ReviewResult:
    session_id: str
    target_path: str
    issues: list[ReviewIssue] = field(default_factory=list)
    files_reviewed: int = 0
    lines_reviewed: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    auto_fixed_count: int = 0
    fixed_issues: list[ReviewIssue] = field(default_factory=list)
    unfixed_issues: list[ReviewIssue] = field(default_factory=list)


@dataclass
class HandoffIssue:
    issue: ReviewIssue
    root_cause: str
    verification_steps: list[str]
    effort_estimate: str
    related_files: list[str]


@dataclass
class HandoffPlan:
    session_id: str
    target_path: str
    issues: list[HandoffIssue]
    generated_at: str
    markdown: str = ""


class ReviewMode(Enum):
    REVIEW = "review"
    AUTO_FIX = "auto_fix"
    PLAN = "plan"
    HYBRID = "hybrid"
    PRESSURE = "pressure"


class Intensity(Enum):
    MINIMAL = "minimal"
    MODERATE = "moderate"
    INTENSIVE = "intensive"
    EXHAUSTIVE = "exhaustive"


@dataclass(frozen=True)
class ReviewConfig:
    target_path: str
    language: str | None = None
    mode: ReviewMode = ReviewMode.REVIEW
    intensity: Intensity = Intensity.MODERATE
    severity_threshold: Severity = Severity.LOW
    max_iterations: int = 10
    max_fixes_per_round: int = 5
    timeout_seconds: int = 3600
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    shadow_mode: bool = False
    failsafe: bool = False
    pressure_focus: PressureFocus | None = None


@dataclass
class StaticAnalysisResult:
    tool_name: str
    language: str
    issues: list[StaticIssue]
    duration_seconds: float
    error_output: str = ""


@dataclass
class StaticIssue:
    file_path: str
    line_number: int
    severity: str
    rule_id: str
    message: str
    category: str


class ReviewEvent(Enum):
    REVIEW_START = "review_start"
    STATIC_ANALYSIS_COMPLETE = "static_analysis_complete"
    SEMANTIC_REVIEW_COMPLETE = "semantic_review_complete"
    FIX_APPLIED = "fix_applied"
    FIX_VERIFIED = "fix_verified"
    FIX_ROLLBACK = "fix_rollback"
    HANDOFF_GENERATED = "handoff_generated"
    REVIEW_COMPLETE = "review_complete"
    REVIEW_ABORT = "review_abort"


@dataclass
class ReviewStats:
    total_issues: int = 0
    valid_issues: int = 0
    fixed_issues: int = 0
    auto_fixed: int = 0
    failed_fixes: int = 0
    handoffs_generated: int = 0
    tokens_used: int = 0
    duration_seconds: float = 0


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ShadowJob:
    job_id: str
    target_path: str
    mode: ReviewMode
    intensity: Intensity
    status: JobStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result: ReviewResult | None = None
    error_message: str | None = None


@dataclass
class PressureFocus:
    design_tradeoffs: bool = False
    failure_modes: bool = False
    race_conditions: bool = False
    auth_security: bool = False
    data_loss: bool = False
    rollback: bool = False
    reliability: bool = False
    custom_focus: str | None = None
