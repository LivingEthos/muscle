"""
Rule engine for MUSCLE static analysis.

Provides a pluggable rule system with built-in checks and custom
validation hooks, integrated with the v1 review controller.

Architecture Decision Record (ADR):
- RuleType enum allows mixing regex, AST, semantic, and custom checks
- Subprocess-based regex timeout prevents ReDoS from untrusted patterns
- Trusted module check for custom rules avoids arbitrary code execution
"""

from __future__ import annotations

from .engine import Rule, RuleEngine, RuleFinding, RuleType
from .regex_timeout import regex_finditer

__all__ = [
    "Rule",
    "RuleEngine",
    "RuleFinding",
    "RuleType",
    "regex_finditer",
]
