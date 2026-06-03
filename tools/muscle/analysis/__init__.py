"""
Static Analysis Engine for MUSCLE.

Provides AST-based security analysis, cross-reference analysis,
and integration with the v1 code review subsystem.

Architecture Decision Record (ADR):
- Pure-Python AST analysis avoids external tool dependencies for core checks
- Cross-reference analysis builds import graphs for architectural insights
- All findings emit v1-compatible shapes for seamless integration
"""

from __future__ import annotations

from .ast_analyzer import ASTAnalyzer, ASTFinding
from .cross_reference import CrossReferenceAnalyzer, CrossReferenceFinding, ImportGraph
from .types import Finding, Severity

__all__ = [
    "ASTAnalyzer",
    "ASTFinding",
    "CrossReferenceAnalyzer",
    "CrossReferenceFinding",
    "ImportGraph",
    "Severity",
    "Finding",
]
