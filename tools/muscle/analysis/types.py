"""
Core types for the static analysis engine.

Architecture Decision Record (ADR):
- Severity enum shared across all analyzers for consistent triage
- Finding base class provides common serialization to v1 shapes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


@dataclass(frozen=True)
class Finding:
    """Base finding shared across all analysis modules.

    Attributes:
        rule_id: Stable identifier for the rule that triggered.
        message: Human-readable description of the issue.
        severity: Severity level.
        line: 1-based line number in the source file.
        column: 0-based column offset in the source file.
        category: Broad classification (e.g. ``security``).
        metadata: Additional structured context.
    """

    rule_id: str
    message: str
    severity: Severity
    line: int
    column: int
    category: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize finding to a plain dictionary."""
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity.name,
            "line": self.line,
            "column": self.column,
            "category": self.category,
            "metadata": self.metadata,
        }
