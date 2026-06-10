"""
Project memory database types (dataclasses) for MUS-010.

These dataclasses provide type-safe representations of all tables
in the unified project memory database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class LearnedRuleStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROMOTED = "promoted"
    ARCHIVED = "archived"


class SkillStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROMOTED = "promoted"


class AgentStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class BackupType(Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    SCHEMA = "schema"


class DecisionType(Enum):
    PROMOTE_RULE = "promote_rule"
    CREATE_SKILL = "create_skill"
    CREATE_AGENT = "create_agent"
    ARCHIVE_PATTERN = "archive_pattern"
    ADJUST_STRATEGY = "adjust_strategy"


class EventType(Enum):
    TASK_START = "task_start"
    TASK_END = "task_end"
    REVIEW_START = "review_start"
    REVIEW_END = "review_end"
    FIX_APPLIED = "fix_applied"
    FIX_FAILED = "fix_failed"
    LEARN_TRIGGERED = "learn_triggered"
    STRATEGY_EVOLVED = "strategy_evolved"


# ---------------------------------------------------------------------------
# Task-related types
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: int | None
    project_path: str
    created_at: str
    title: str
    description: str
    status: TaskStatus
    outcome: str | None
    token_cost: int
    duration_ms: int


@dataclass
class ConversationEvent:
    id: int | None
    project_path: str
    task_id: int | None
    event_type: EventType
    timestamp: str
    summary: str
    metadata_json: str | None


# ---------------------------------------------------------------------------
# Review-related types
# ---------------------------------------------------------------------------


@dataclass
class ReviewRun:
    id: int | None
    project_path: str
    review_mode: str
    target_path: str
    findings_count: int
    token_cost: int
    duration_ms: int
    created_at: str


@dataclass
class ReviewFinding:
    id: int | None
    review_run_id: int
    rule_id: str
    severity: str
    file_path: str
    line_number: int
    message: str
    auto_fixable: bool
    fix_applied: bool
    outcome: str | None


@dataclass
class FixAttempt:
    id: int | None
    finding_id: int
    created_at: str
    fix_content: str | None
    verification_passed: bool
    notes: str | None


# ---------------------------------------------------------------------------
# Change tracking types
# ---------------------------------------------------------------------------


@dataclass
class ChangeEvent:
    id: int | None
    project_path: str
    created_at: str
    changed_files_json: str
    diff_summary: str | None
    review_run_id: int | None


# ---------------------------------------------------------------------------
# Learning types
# ---------------------------------------------------------------------------


@dataclass
class LearnedRule:
    id: int | None
    project_path: str
    created_at: str
    rule_text: str
    trigger_pattern: str
    recurrence_count: int
    success_rate: float
    last_triggered: str | None
    status: LearnedRuleStatus
    promoted_to_claude_md: bool
    promoted_at: str | None


@dataclass
class MemoryDecision:
    id: int | None
    project_path: str
    created_at: str
    decision_type: DecisionType
    source_table: str
    source_id: int
    evidence_json: str
    score_json: str
    reasoning: str


# ---------------------------------------------------------------------------
# Skill and agent types
# ---------------------------------------------------------------------------


@dataclass
class Skill:
    id: int | None
    project_path: str
    created_at: str
    name: str
    description: str
    trigger_pattern: str
    file_path: str | None
    status: SkillStatus
    last_used: str | None
    use_count: int


@dataclass
class Agent:
    id: int | None
    project_path: str
    created_at: str
    name: str
    description: str
    trigger_pattern: str
    file_path: str | None
    status: AgentStatus
    last_used: str | None
    use_count: int


# ---------------------------------------------------------------------------
# Backup and project notes types
# ---------------------------------------------------------------------------


@dataclass
class Backup:
    id: int | None
    project_path: str
    created_at: str
    backup_type: BackupType
    file_path: str
    checksum: str | None
    size_bytes: int
    retention_days: int


@dataclass
class ProjectNote:
    id: int | None
    project_path: str
    created_at: str
    category: str
    title: str
    content: str
    updated_at: str


@dataclass
class AutomationState:
    id: int | None
    project_path: str
    created_at: str
    state_key: str
    state_value: str | None
    updated_at: str


# ---------------------------------------------------------------------------
# Cross-project learning and model-pack types
# ---------------------------------------------------------------------------


@dataclass
class ProjectFingerprint:
    """Lightweight metadata describing a project for overlap detection."""

    project_path: str
    display_name: str
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    archetypes: list[str] = field(default_factory=list)
    fingerprint_hash: str = ""


@dataclass
class RelatedProjectLink:
    id: int | None
    project_path: str
    source_project_path: str
    link_mode: str
    status: str
    relatedness_score: float
    fingerprint_json: str
    created_at: str
    updated_at: str
    last_synced_at: str | None


@dataclass
class TransferredLesson:
    id: int | None
    project_path: str
    source_project_path: str
    source_rule_id: int | None
    lesson_key: str
    lesson_text: str
    trigger_pattern: str
    link_mode: str
    validation_status: str
    validation_count: int
    success_count: int
    scope_json: str
    metadata_json: str
    imported_at: str
    updated_at: str
    promoted_rule_id: int | None


@dataclass
class ModelIdentity:
    requested_label: str | None
    provider_endpoint: str | None
    provider_fingerprint: str | None
    canonical_model_key: str | None
    identity_source: str
    confidence: float
    manual_override: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ModelIdentityHistoryEntry:
    id: int | None
    project_path: str
    created_at: str
    requested_label: str | None
    provider_endpoint: str | None
    provider_fingerprint: str | None
    canonical_model_key: str | None
    identity_source: str
    confidence: float
    manual_override: bool
    metadata_json: str


@dataclass
class LessonUsageEvent:
    id: int | None
    project_path: str
    created_at: str
    session_id: str | None
    call_id: str | None
    stage: str
    lesson_source: str
    lesson_key: str
    canonical_model_key: str | None
    source_project_path: str | None
    outcome: str | None
    metadata_json: str


@dataclass
class ModelPackMetadata:
    canonical_model_key: str
    version: str
    install_status: str
    source_repo: str | None = None
    source_repo_commit: str | None = None
    pack_path: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ModelPackLesson:
    canonical_model_key: str
    lesson_key: str
    lesson_text: str
    scope_tags: list[str] = field(default_factory=list)
    safety_scope: str = "review-only"
    portability: str = "portable"
    evidence: dict[str, object] = field(default_factory=dict)
    rationale: str | None = None
    source_repo_commit: str | None = None


@dataclass
class PackSubmissionRecord:
    export_id: str
    canonical_model_key: str
    repo: str
    branch: str
    status: str
    pr_url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Optimization and telemetry types
# ---------------------------------------------------------------------------


@dataclass
class LLMCall:
    id: int | None
    project_path: str
    created_at: str
    call_id: str
    session_id: str
    stage: str
    workflow_name: str | None
    review_mode: str | None
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    success: bool
    parse_success: bool | None
    validation_success: bool | None
    context_chars: int
    context_strategy: str
    metadata_json: str


@dataclass
class WorkflowRollup:
    id: int | None
    project_path: str
    workflow_name: str
    stage: str
    language: str
    complexity: str
    target_type: str
    run_count: int
    success_count: int
    total_tokens: int
    total_duration_ms: int
    valid_findings: int
    verified_fixes: int
    one_shot_verified_fixes: int
    high_critical_findings: int
    validation_successes: int
    last_session_id: str | None
    updated_at: str


@dataclass
class OptimizationDecision:
    id: int | None
    project_path: str
    created_at: str
    decision_type: str
    decision_scope: str
    comparable_key: str
    recommendation_json: str
    applied: bool
    confidence: float
    outcome_json: str


@dataclass
class ExternalBenchmarkSession:
    id: int | None
    project_path: str
    provider: str
    external_session_id: str
    source_path: str
    project_hint: str | None
    normalized_project_path: str
    started_at: str | None
    ended_at: str | None
    metadata_json: str
    created_at: str


@dataclass
class ExternalBenchmarkTurn:
    id: int | None
    benchmark_session_id: int
    timestamp: str
    category: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_tokens: int
    reasoning_tokens: int
    retry_count: int
    success_signal: bool
    token_cost: int
    tool_names_json: str
    metadata_json: str
    dedup_key: str


@dataclass
class TokenSavingsLedgerEntry:
    id: int | None
    project_path: str
    created_at: str
    session_id: str
    stage: str
    workflow_name: str | None
    comparable_key: str
    baseline_tokens: int | None
    actual_tokens: int
    delta_tokens: int
    confidence: float
    realized: bool
    estimation_type: str
    metadata_json: str


# ---------------------------------------------------------------------------
# Schema version tracking
# ---------------------------------------------------------------------------


@dataclass
class SchemaVersion:
    id: int | None
    version: str
    applied_at: str


# ---------------------------------------------------------------------------
# Helper types for bulk operations
# ---------------------------------------------------------------------------


@dataclass
class ReviewFindingWithFixAttempt:
    """A review finding along with its associated fix attempts."""

    finding: ReviewFinding
    fix_attempts: list[FixAttempt] = field(default_factory=list)


@dataclass
class LearnedRuleWithMetadata:
    """A learned rule with computed metadata."""

    rule: LearnedRule
    avg_recurrence: float = 0.0
    avg_success_rate: float = 0.0
    total_triggers: int = 0
