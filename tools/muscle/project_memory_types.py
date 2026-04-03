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
