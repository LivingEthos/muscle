"""
Code Review module for MUSCLE.

Provides autonomous code review with self-learning capabilities:
- Static analysis using local tools (Ruff, ESLint, Clippy, etc.)
- M2.7-powered semantic analysis and issue classification
- Automatic fix generation and verification
- Detailed handoff plans for complex issues
- Learning from past reviews via ReviewKB
"""

from .code_reviewer import CodeReviewer
from .fix_generator import FixGenerator
from .handoff_generator import HandoffGenerator
from .review_controller import ReviewController
from .review_kb import GlobalReviewKB, ReviewKB
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
    ReviewStats,
    Severity,
    StaticAnalysisResult,
    StaticIssue,
)

__all__ = [
    "Severity",
    "IssueCategory",
    "ReviewIssue",
    "ReviewResult",
    "ReviewConfig",
    "ReviewMode",
    "ReviewEvent",
    "ReviewStats",
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
    "ReviewKB",
    "GlobalReviewKB",
    "ShadowBroker",
]
