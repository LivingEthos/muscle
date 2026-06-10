"""
Code Review module for MUSCLE.

Provides autonomous code review with self-learning capabilities:
- Static analysis using local tools (Ruff, ESLint, Clippy, etc.)
- M2.7-powered semantic analysis and issue classification
- Workflow-driven committee review and scope classification
- Automatic fix generation and verification
- Detailed handoff plans for complex issues
- Learning from past reviews via ReviewKB
"""

from .code_reviewer import CodeReviewer
from .committee_reviewer import CommitteeReviewer
from .fix_generator import FixGenerator
from .handoff_generator import HandoffGenerator
from .review_artifacts import ReviewArtifactStore
from .review_controller import ReviewController
from .review_kb import GlobalReviewKB, ReviewKB
from .review_scope import ReviewScopeClassifier
from .review_workflows import ReviewWorkflowEngine, ReviewWorkflowLoader
from .shadow_broker import ShadowBroker
from .static_analyzer import StaticAnalyzer
from .types import (
    HandoffIssue,
    HandoffPlan,
    Intensity,
    IssueCategory,
    PressureFocus,
    ReviewConfig,
    ReviewEvent,
    ReviewIssue,
    ReviewMode,
    ReviewResult,
    ReviewScope,
    ReviewStats,
    Severity,
    StaticAnalysisResult,
    StaticIssue,
)
from .worktree_manager import GitWorktreeManager

__all__ = [
    "Severity",
    "IssueCategory",
    "ReviewIssue",
    "ReviewResult",
    "ReviewConfig",
    "ReviewMode",
    "ReviewEvent",
    "ReviewStats",
    "ReviewScope",
    "HandoffIssue",
    "HandoffPlan",
    "StaticIssue",
    "StaticAnalysisResult",
    "Intensity",
    "PressureFocus",
    "ReviewController",
    "CodeReviewer",
    "FixGenerator",
    "HandoffGenerator",
    "StaticAnalyzer",
    "CommitteeReviewer",
    "ReviewScopeClassifier",
    "ReviewWorkflowLoader",
    "ReviewWorkflowEngine",
    "ReviewArtifactStore",
    "ReviewKB",
    "GlobalReviewKB",
    "ShadowBroker",
    "GitWorktreeManager",
]


def __getattr__(name: str) -> object:
    """Lazily expose heavier modules to avoid import cycles."""
    if name == "ReviewBenchmarkRunner":
        from .review_benchmark import ReviewBenchmarkRunner

        return ReviewBenchmarkRunner
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
