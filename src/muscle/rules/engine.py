"""
Rule engine for static analysis.

Supports regex, AST, semantic, and custom rule types with built-in
checks and trusted module validation for custom rules.

Architecture Decision Record (ADR):
- Built-in rules cover common lint-like checks without external tools
- ReDoS detection prevents dangerous regex patterns from being registered
- Custom rules must pass a trusted module check before execution
"""

from __future__ import annotations

import ast
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..analysis.types import Finding, Severity
from .regex_timeout import regex_finditer

logger = logging.getLogger(__name__)


class RuleType(Enum):
    """Classification of rule implementation strategy."""

    REGEX = "regex"
    AST = "ast"
    SEMANTIC = "semantic"
    CUSTOM = "custom"


@dataclass(frozen=True)
class RuleFinding(Finding):
    """Finding produced by the rule engine."""

    file_path: str = ""

    def to_review_issue_dict(self) -> dict[str, Any]:
        """Emit a v1-compatible ReviewIssue shape."""
        return {
            "file_path": self.file_path,
            "line_number": self.line,
            "severity": self.severity,
            "category": self.category,
            "cwe_id": None,
            "title": self.rule_id,
            "description": self.message,
            "code_snippet": "",
            "suggested_fix": None,
            "auto_fixable": False,
            "source_agent": "rule_engine",
        }


@dataclass
class Rule:
    """A single analysis rule.

    Attributes:
        id: Stable rule identifier.
        name: Human-readable name.
        rule_type: Implementation strategy.
        severity: Default severity when triggered.
        pattern: Regex pattern (for REGEX rules).
        message: Message template for findings.
        custom_check: Callable for CUSTOM rules.
        enabled: Whether the rule is active.
        category: Logical grouping for the rule.
        description: Detailed explanation of what the rule checks.
        metadata: Arbitrary key-value data for extensibility.
    """

    id: str
    name: str
    rule_type: RuleType
    severity: Severity
    message: str
    pattern: str | None = None
    custom_check: Callable[[str, str], list[RuleFinding]] | None = None
    enabled: bool = True
    category: str = "custom"
    description: str = ""
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})


class RuleEngine:
    """Engine that registers and executes analysis rules."""

    _BUILTIN_RULES: list[Rule] = [
        Rule(
            id="RULE-001",
            name="no-print",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="Print statement found",
            pattern=r"^\s*print\s*\(",
        ),
        Rule(
            id="RULE-002",
            name="no-TODO",
            rule_type=RuleType.REGEX,
            severity=Severity.INFO,
            message="TODO comment found",
            pattern=r"#\s*TODO",
        ),
        Rule(
            id="RULE-003",
            name="max-line-length",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="Line exceeds 100 characters",
            pattern=r"^.{101,}$",
        ),
        Rule(
            id="RULE-004",
            name="no-assert",
            rule_type=RuleType.AST,
            severity=Severity.MEDIUM,
            message="Assert statement found in non-test code",
        ),
    ]

    def __init__(self) -> None:
        self._rules: list[Rule] = list(self._BUILTIN_RULES)
        self._disabled_rule_ids: set[str] = set()

    @property
    def rules(self) -> list[Rule]:
        """Return a copy of registered rules."""
        return list(self._rules)

    def add_rule(self, rule: Rule) -> None:
        """Add a rule to the engine after validation.

        Args:
            rule: Rule to add.

        Raises:
            ValueError: If the rule pattern has ReDoS risk or custom check is untrusted.
        """
        self.register(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID.

        Args:
            rule_id: ID of the rule to remove.

        Returns:
            True if a rule was removed, False otherwise.
        """
        original_len = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        self._disabled_rule_ids.discard(rule_id)
        return len(self._rules) < original_len

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule by ID.

        Args:
            rule_id: ID of the rule to enable.

        Returns:
            True if the rule was previously disabled and is now enabled.
        """
        if rule_id in self._disabled_rule_ids:
            self._disabled_rule_ids.discard(rule_id)
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule by ID.

        Args:
            rule_id: ID of the rule to disable.

        Returns:
            True if the rule exists and was not already disabled.
        """
        if any(r.id == rule_id for r in self._rules):
            if rule_id not in self._disabled_rule_ids:
                self._disabled_rule_ids.add(rule_id)
                return True
        return False

    def get_rule_summary(self) -> dict[str, Any]:
        """Return a summary of registered rules.

        Returns:
            Dictionary with total, enabled, disabled counts and
            breakdowns by type and category.
        """
        total_rules = len(self._rules)
        disabled = len(self._disabled_rule_ids)
        enabled = total_rules - disabled

        by_type: dict[str, int] = {}
        for rule in self._rules:
            key = rule.rule_type.value
            by_type[key] = by_type.get(key, 0) + 1

        by_category: dict[str, int] = {}
        for rule in self._rules:
            key = getattr(rule, "category", "uncategorized")
            by_category[key] = by_category.get(key, 0) + 1

        return {
            "total_rules": total_rules,
            "enabled": enabled,
            "disabled": disabled,
            "by_type": by_type,
            "by_category": by_category,
        }

    def register(self, rule: Rule) -> None:
        """Register a new rule after validation.

        Args:
            rule: Rule to register.

        Raises:
            ValueError: If the rule pattern has ReDoS risk or custom check is untrusted.
        """
        if rule.rule_type == RuleType.REGEX and rule.pattern:
            if self._has_redos_risk(rule.pattern):
                raise ValueError(f"Rule {rule.id} pattern has ReDoS risk")
        if rule.rule_type == RuleType.CUSTOM and rule.custom_check is not None:
            if not self._is_trusted_check(rule.custom_check):
                raise ValueError(f"Rule {rule.id} custom check is not trusted")
        self._rules.append(rule)

    def unregister(self, rule_id: str) -> None:
        """Remove a rule by ID and clear its disabled state."""
        self._rules = [r for r in self._rules if r.id != rule_id]
        self._disabled_rule_ids.discard(rule_id)

    def analyze_file(self, file_path: str) -> list[RuleFinding]:
        """Analyze a single file with all enabled rules.

        Args:
            file_path: Path to the source file.

        Returns:
            Combined list of findings.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning("File not found: %s", file_path)
            return []

        source = path.read_text(encoding="utf-8")
        findings: list[RuleFinding] = []

        for rule in self._rules:
            if not rule.enabled or rule.id in self._disabled_rule_ids:
                continue
            if rule.rule_type == RuleType.REGEX and rule.pattern:
                findings.extend(self._run_regex_rule(rule, file_path, source))
            elif rule.rule_type == RuleType.AST:
                findings.extend(self._run_ast_rule(rule, file_path, source))
            elif rule.rule_type == RuleType.CUSTOM and rule.custom_check:
                findings.extend(rule.custom_check(file_path, source))

        return findings

    def analyze_directory(self, directory: str, pattern: str = "*.py") -> list[RuleFinding]:
        """Recursively analyze all matching files.

        Args:
            directory: Root directory to scan.
            pattern: Glob pattern for file matching.

        Returns:
            Flat list of findings from all files.
        """
        findings: list[RuleFinding] = []
        for path in Path(directory).rglob(pattern):
            findings.extend(self.analyze_file(str(path)))
        return findings

    def _run_regex_rule(self, rule: Rule, file_path: str, source: str) -> list[RuleFinding]:
        """Execute a regex rule with timeout protection."""
        findings: list[RuleFinding] = []
        result = regex_finditer(rule.pattern or "", source)
        if result.timed_out:
            findings.append(
                RuleFinding(
                    rule_id=rule.id,
                    message=f"Regex timed out for rule {rule.id}",
                    severity=Severity.HIGH,
                    line=1,
                    column=0,
                    category="security",
                    file_path=file_path,
                )
            )
            return findings
        if result.error:
            logger.warning("Regex error for rule %s: %s", rule.id, result.error)
            return findings
        for match in result.matches:
            line = source[: match.start].count("\n") + 1
            last_newline = source.rfind("\n", 0, match.start)
            column = match.start - (last_newline + 1) if last_newline != -1 else match.start
            findings.append(
                RuleFinding(
                    rule_id=rule.id,
                    message=rule.message,
                    severity=rule.severity,
                    line=line,
                    column=column,
                    category="style",
                    file_path=file_path,
                )
            )
        return findings

    def _run_ast_rule(self, rule: Rule, file_path: str, source: str) -> list[RuleFinding]:
        """Execute an AST-based rule."""
        findings: list[RuleFinding] = []
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", file_path, exc)
            return findings

        for node in ast.walk(tree):
            if rule.id == "RULE-004" and isinstance(node, ast.Assert):
                findings.append(
                    RuleFinding(
                        rule_id=rule.id,
                        message=rule.message,
                        severity=rule.severity,
                        line=node.lineno,
                        column=node.col_offset,
                        category="correctness",
                        file_path=file_path,
                    )
                )
        return findings

    @staticmethod
    def _has_redos_risk(pattern: str) -> bool:
        """Heuristic check for ReDoS-prone regex patterns.

        Looks for nested quantifiers and ambiguous alternations.

        Args:
            pattern: Regex pattern string.

        Returns:
            True if the pattern appears risky.
        """
        # Simple heuristic: nested quantifiers like (a+)+ or (a*)*
        if re.search(r"\([^)]*[*+][^)]*\)[*+]", pattern):
            return True
        # Ambiguous alternation with repetition: (a|b)*
        if re.search(r"\([^)]*\|[^)]*\)[*+]", pattern):
            return True
        return False

    @staticmethod
    def _is_trusted_check(check: Callable[..., Any]) -> bool:
        """Validate that a custom check comes from a trusted module.

        Args:
            check: Callable to validate.

        Returns:
            True if the callable is defined in a trusted module.
        """
        module = getattr(check, "__module__", None)
        if module is None:
            return False
        trusted_prefixes = (
            "muscle.",
            "tests.unit.",
            "__main__",
        )
        return any(module.startswith(p) for p in trusted_prefixes)
