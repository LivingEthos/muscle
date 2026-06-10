"""
Code Review module for MUSCLE.

Provides autonomous code review with self-learning capabilities:
- Static analysis using local tools (Ruff, ESLint, Clippy, etc.)
- M2.7-powered semantic analysis and issue classification
- Workflow-driven committee review and scope classification
- Automatic fix generation and verification
- Detailed handoff plans for complex issues
- Learning from past reviews via ReviewKB

Import policy: every public name is exposed via a uniform lazy ``__getattr__``
rather than eager top-level imports. Per the project critical rule, eager import
of many submodules makes the whole facade hostage to a single broken import; with
lazy loading the package is always importable and a failure surfaces only when the
specific name is actually used. ``__all__`` is the single source of truth (it maps
every name to its defining module), and ``__dir__`` mirrors it for tooling/REPL
completion. A ``TYPE_CHECKING`` block re-exports the real symbols so static type
checkers (mypy) and IDEs still resolve them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# name -> submodule (relative to this package) that defines it. This is the
# single source of truth for what the facade exposes; __all__ is derived from it.
_LAZY_EXPORTS: dict[str, str] = {
    # types
    "Severity": "types",
    "IssueCategory": "types",
    "ReviewIssue": "types",
    "ReviewResult": "types",
    "ReviewConfig": "types",
    "ReviewMode": "types",
    "ReviewEvent": "types",
    "ReviewStats": "types",
    "ReviewScope": "types",
    "HandoffIssue": "types",
    "HandoffPlan": "types",
    "StaticIssue": "types",
    "StaticAnalysisResult": "types",
    "Intensity": "types",
    "PressureFocus": "types",
    # controllers / engines
    "ReviewController": "review_controller",
    "CodeReviewer": "code_reviewer",
    "FixGenerator": "fix_generator",
    "HandoffGenerator": "handoff_generator",
    "StaticAnalyzer": "static_analyzer",
    "CommitteeReviewer": "committee_reviewer",
    "ReviewScopeClassifier": "review_scope",
    "ReviewWorkflowLoader": "review_workflows",
    "ReviewWorkflowEngine": "review_workflows",
    "ReviewArtifactStore": "review_artifacts",
    "ReviewKB": "review_kb",
    "GlobalReviewKB": "review_kb",
    "ShadowBroker": "shadow_broker",
    "GitWorktreeManager": "worktree_manager",
    "ReviewBenchmarkRunner": "review_benchmark",
}

__all__ = sorted(_LAZY_EXPORTS)


if TYPE_CHECKING:  # pragma: no cover - import-time hints for type checkers only
    # Redundant ``as`` aliases mark these as explicit re-exports: the names are
    # surfaced at runtime via ``__getattr__`` (keyed off ``_LAZY_EXPORTS``), which
    # the linter cannot statically connect to ``__all__``.
    from .code_reviewer import CodeReviewer as CodeReviewer
    from .committee_reviewer import CommitteeReviewer as CommitteeReviewer
    from .fix_generator import FixGenerator as FixGenerator
    from .handoff_generator import HandoffGenerator as HandoffGenerator
    from .review_artifacts import ReviewArtifactStore as ReviewArtifactStore
    from .review_benchmark import ReviewBenchmarkRunner as ReviewBenchmarkRunner
    from .review_controller import ReviewController as ReviewController
    from .review_kb import GlobalReviewKB as GlobalReviewKB
    from .review_kb import ReviewKB as ReviewKB
    from .review_scope import ReviewScopeClassifier as ReviewScopeClassifier
    from .review_workflows import ReviewWorkflowEngine as ReviewWorkflowEngine
    from .review_workflows import ReviewWorkflowLoader as ReviewWorkflowLoader
    from .shadow_broker import ShadowBroker as ShadowBroker
    from .static_analyzer import StaticAnalyzer as StaticAnalyzer
    from .types import HandoffIssue as HandoffIssue
    from .types import HandoffPlan as HandoffPlan
    from .types import Intensity as Intensity
    from .types import IssueCategory as IssueCategory
    from .types import PressureFocus as PressureFocus
    from .types import ReviewConfig as ReviewConfig
    from .types import ReviewEvent as ReviewEvent
    from .types import ReviewIssue as ReviewIssue
    from .types import ReviewMode as ReviewMode
    from .types import ReviewResult as ReviewResult
    from .types import ReviewScope as ReviewScope
    from .types import ReviewStats as ReviewStats
    from .types import Severity as Severity
    from .types import StaticAnalysisResult as StaticAnalysisResult
    from .types import StaticIssue as StaticIssue
    from .worktree_manager import GitWorktreeManager as GitWorktreeManager


def __getattr__(name: str) -> object:
    """Lazily import and cache a public name on first access.

    Resolving on demand keeps the package importable even if one submodule has a
    broken import; the failure is then localized to the name that needs it. The
    resolved attribute is cached in module globals so subsequent accesses are
    plain lookups.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    from importlib import import_module

    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
