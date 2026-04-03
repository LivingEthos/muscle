"""
MUSCLE (MiniMax Unified Self-Correcting Learning Engine).

A self-learning code review tool that uses the MiniMax M2.7 model via
an Anthropic-compatible API.
"""

from .project_memory import ProjectMemory
from .project_memory_schema import SCHEMA_VERSION
from .project_memory_types import (
    Agent,
    AgentStatus,
    AutomationState,
    Backup,
    BackupType,
    ChangeEvent,
    ConversationEvent,
    DecisionType,
    EventType,
    FixAttempt,
    LearnedRule,
    LearnedRuleStatus,
    LearnedRuleWithMetadata,
    MemoryDecision,
    ProjectNote,
    ReviewFinding,
    ReviewFindingWithFixAttempt,
    ReviewRun,
    SchemaVersion,
    Skill,
    SkillStatus,
    Task,
    TaskStatus,
)

__all__ = [
    # Core class
    "ProjectMemory",
    # Schema version
    "SCHEMA_VERSION",
    # Types - Enums
    "AgentStatus",
    "BackupType",
    "DecisionType",
    "EventType",
    "LearnedRuleStatus",
    "SkillStatus",
    "TaskStatus",
    # Types - Task
    "Task",
    "ConversationEvent",
    # Types - Review
    "ReviewRun",
    "ReviewFinding",
    "ReviewFindingWithFixAttempt",
    "FixAttempt",
    # Types - Change
    "ChangeEvent",
    # Types - Learning
    "LearnedRule",
    "LearnedRuleWithMetadata",
    "MemoryDecision",
    # Types - Skills/Agents
    "Skill",
    "Agent",
    # Types - Backup/Notes/State
    "Backup",
    "ProjectNote",
    "AutomationState",
    # Types - Schema
    "SchemaVersion",
]
