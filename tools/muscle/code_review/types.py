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
from typing import Any

from ..command_evidence import CommandEvidence, ParserTier


class Severity(Enum):
    """Issue severity levels aligned with CWE triage taxonomy.

    Convention:
    - Use ``.value`` (int) for persistence, JSON serialisation, and numeric comparisons.
    - Use ``.name`` (str, e.g. ``"HIGH"``) for human-readable log messages and display.
    """

    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1


class IssueCategory(Enum):
    """Issue category labels.

    Convention:
    - Use ``.value`` (lowercase str, e.g. ``"security"``) for persistence and JSON.
    - Use ``.name`` (upper str, e.g. ``"SECURITY"``) for log messages and display.
    """

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
    source_agent: str | None = None


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
    workflow_name: str | None = None
    execution_mode: str = "local"
    worktree_path: str | None = None
    base_branch: str | None = None
    sync_summary: dict[str, Any] | None = None
    applied_back_files: list[str] = field(default_factory=list)
    artifact_dir: str | None = None
    scope_summary: dict[str, Any] | None = None
    raw_issues: list[ReviewIssue] = field(default_factory=list)


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
    pressure_challenge: str | None = None
    workflow_name: str | None = None
    review_profile: str = "smart"
    scope_mode: str = "auto"
    execution_mode: str = "local"
    worktree_enabled: bool = False
    fetch_sources: bool = False
    fetch_source_packages: list[str] | None = None
    # Maximum number of static-analysis issues forwarded to the M2.7 semantic
    # review per file per batch.  Tune down to reduce token spend; tune up to
    # allow the reviewer to see more context per call.
    max_issues_per_batch: int = 20

    def __post_init__(self) -> None:
        if self.execution_mode == "worktree" and not self.worktree_enabled:
            object.__setattr__(self, "worktree_enabled", True)


@dataclass
class StaticAnalysisResult:
    tool_name: str
    language: str
    issues: list[StaticIssue]
    duration_seconds: float
    error_output: str = ""
    parser_tier: str = ParserTier.FULL.value
    parse_warnings: list[str] = field(default_factory=list)
    evidence: CommandEvidence | None = None


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


@dataclass(frozen=True)
class ReviewScope:
    complexity: str
    changed_files: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    touched_languages: list[str] = field(default_factory=list)
    review_agents: list[str] = field(default_factory=list)
    review_intensity: str = Intensity.MODERATE.value
    test_scope: str = "none"
    auto_fix_cap: int = 1
    public_api_changed: bool = False
    docs_only: bool = False
    tests_only: bool = False
    line_count: int = 0
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert ReviewScope to a JSON-serializable dict."""
        return {
            "complexity": self.complexity,
            "changed_files": self.changed_files,
            "source_files": self.source_files,
            "doc_files": self.doc_files,
            "test_files": self.test_files,
            "touched_languages": self.touched_languages,
            "review_agents": self.review_agents,
            "review_intensity": self.review_intensity,
            "test_scope": self.test_scope,
            "auto_fix_cap": self.auto_fix_cap,
            "public_api_changed": self.public_api_changed,
            "docs_only": self.docs_only,
            "tests_only": self.tests_only,
            "line_count": self.line_count,
            "reasoning": self.reasoning,
        }


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
