"""
Unit tests for the rule engine.
"""

import tempfile
from pathlib import Path

import pytest

from tools.muscle.analysis.types import Severity
from tools.muscle.rules.engine import Rule, RuleEngine, RuleFinding, RuleType


class TestRuleEngineBuiltinRules:
    """Tests for built-in rule detection."""

    def test_no_print_rule(self):
        """RULE-001: print statements are detected."""
        engine = RuleEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("print('hello')\n")
            findings = engine.analyze_file(str(path))
        assert any(f.rule_id == "RULE-001" for f in findings)

    def test_no_todo_rule(self):
        """RULE-002: TODO comments are detected."""
        engine = RuleEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("# TODO: fix this\n")
            findings = engine.analyze_file(str(path))
        assert any(f.rule_id == "RULE-002" for f in findings)

    def test_max_line_length_rule(self):
        """RULE-003: long lines are detected."""
        engine = RuleEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("x" * 101 + "\n")
            findings = engine.analyze_file(str(path))
        assert any(f.rule_id == "RULE-003" for f in findings)

    def test_no_assert_rule(self):
        """RULE-004: assert statements are detected."""
        engine = RuleEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("assert x == 1\n")
            findings = engine.analyze_file(str(path))
        assert any(f.rule_id == "RULE-004" for f in findings)

    def test_disabled_rule_not_triggered(self):
        """Disabled rules do not produce findings."""
        engine = RuleEngine()
        engine._rules[0] = Rule(
            id="RULE-001",
            name="no-print",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="print statement found",
            pattern=r"^\s*print\s*\(",
            enabled=False,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("print('hello')\n")
            findings = engine.analyze_file(str(path))
        assert not any(f.rule_id == "RULE-001" for f in findings)

    def test_analyze_directory(self):
        """Directory scan aggregates findings from multiple files."""
        engine = RuleEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "a.py").write_text("print('a')\n")
            (path / "b.py").write_text("print('b')\n")
            findings = engine.analyze_directory(tmpdir)
        assert len([f for f in findings if f.rule_id == "RULE-001"]) == 2

    def test_file_not_found(self):
        """Missing files return empty findings."""
        engine = RuleEngine()
        findings = engine.analyze_file("/nonexistent/path.py")
        assert findings == []

    def test_redos_pattern_rejected(self):
        """ReDoS-prone patterns are rejected during registration."""
        engine = RuleEngine()
        bad_rule = Rule(
            id="RULE-BAD",
            name="bad-regex",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="bad",
            pattern=r"(a+)+",
        )
        with pytest.raises(ValueError, match="ReDoS"):
            engine.register(bad_rule)

    def test_custom_check_trusted(self):
        """Trusted custom checks are accepted."""
        engine = RuleEngine()

        def trusted_check(file_path: str, source: str) -> list[RuleFinding]:
            return []

        trusted_check.__module__ = "tools.muscle.rules.engine"
        custom_rule = Rule(
            id="RULE-CUST",
            name="custom",
            rule_type=RuleType.CUSTOM,
            severity=Severity.INFO,
            message="custom check",
            custom_check=trusted_check,
        )
        engine.register(custom_rule)
        assert any(r.id == "RULE-CUST" for r in engine.rules)

    def test_custom_check_untrusted_rejected(self):
        """Untrusted custom checks are rejected."""
        engine = RuleEngine()

        def untrusted_check(file_path: str, source: str) -> list[RuleFinding]:
            return []

        untrusted_check.__module__ = "malicious.module"
        custom_rule = Rule(
            id="RULE-BAD",
            name="bad",
            rule_type=RuleType.CUSTOM,
            severity=Severity.INFO,
            message="bad check",
            custom_check=untrusted_check,
        )
        with pytest.raises(ValueError, match="trusted"):
            engine.register(custom_rule)


class TestRuleLifecycle:
    """Tests for rule lifecycle methods (add, remove, enable, disable)."""

    def test_add_rule(self):
        """add_rule appends a rule to the engine."""
        engine = RuleEngine()
        rule = Rule(
            id="RULE-NEW",
            name="new-rule",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="new rule",
            pattern=r"^\s*eval\s*\(",
        )
        engine.add_rule(rule)
        assert any(r.id == "RULE-NEW" for r in engine.rules)

    def test_remove_rule_existing(self):
        """remove_rule returns True when a rule is removed."""
        engine = RuleEngine()
        assert engine.remove_rule("RULE-001") is True
        assert not any(r.id == "RULE-001" for r in engine.rules)

    def test_remove_rule_nonexistent(self):
        """remove_rule returns False when the rule does not exist."""
        engine = RuleEngine()
        assert engine.remove_rule("RULE-NOPE") is False

    def test_disable_rule_existing(self):
        """disable_rule returns True and prevents rule from firing."""
        engine = RuleEngine()
        assert engine.disable_rule("RULE-001") is True
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("print('hello')\n")
            findings = engine.analyze_file(str(path))
        assert not any(f.rule_id == "RULE-001" for f in findings)

    def test_disable_rule_already_disabled(self):
        """disable_rule returns False if rule is already disabled."""
        engine = RuleEngine()
        engine.disable_rule("RULE-001")
        assert engine.disable_rule("RULE-001") is False

    def test_disable_rule_nonexistent(self):
        """disable_rule returns False for a nonexistent rule."""
        engine = RuleEngine()
        assert engine.disable_rule("RULE-NOPE") is False

    def test_enable_rule_previously_disabled(self):
        """enable_rule returns True and restores rule execution."""
        engine = RuleEngine()
        engine.disable_rule("RULE-001")
        assert engine.enable_rule("RULE-001") is True
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.py"
            path.write_text("print('hello')\n")
            findings = engine.analyze_file(str(path))
        assert any(f.rule_id == "RULE-001" for f in findings)

    def test_enable_rule_not_disabled(self):
        """enable_rule returns False if the rule was not disabled."""
        engine = RuleEngine()
        assert engine.enable_rule("RULE-001") is False

    def test_remove_rule_clears_disabled_state(self):
        """Removing a rule also clears its disabled state."""
        engine = RuleEngine()
        engine.disable_rule("RULE-001")
        engine.remove_rule("RULE-001")
        summary = engine.get_rule_summary()
        assert summary["disabled"] == 0


class TestRuleSummary:
    """Tests for get_rule_summary."""

    def test_summary_counts(self):
        """Summary reflects total, enabled, and disabled counts."""
        engine = RuleEngine()
        summary = engine.get_rule_summary()
        assert summary["total_rules"] == 4
        assert summary["enabled"] == 4
        assert summary["disabled"] == 0

    def test_summary_after_disable(self):
        """Summary updates after disabling a rule."""
        engine = RuleEngine()
        engine.disable_rule("RULE-001")
        summary = engine.get_rule_summary()
        assert summary["total_rules"] == 4
        assert summary["enabled"] == 3
        assert summary["disabled"] == 1

    def test_summary_by_type(self):
        """Summary breaks down rules by type."""
        engine = RuleEngine()
        summary = engine.get_rule_summary()
        assert summary["by_type"] == {"regex": 3, "ast": 1}

    def test_summary_by_category(self):
        """Summary breaks down rules by category attribute or defaults."""
        engine = RuleEngine()
        summary = engine.get_rule_summary()
        assert summary["by_category"] == {"custom": 4}


class TestRuleDataclass:
    """Tests for Rule dataclass fields and defaults."""

    def test_new_fields_have_correct_defaults(self):
        """category, description, and metadata have backward-compatible defaults."""
        rule = Rule(
            id="RULE-TEST",
            name="test-rule",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="test message",
        )
        assert rule.category == "custom"
        assert rule.description == ""
        assert rule.metadata == {}

    def test_new_fields_can_be_set(self):
        """category, description, and metadata can be explicitly provided."""
        rule = Rule(
            id="RULE-TEST",
            name="test-rule",
            rule_type=RuleType.REGEX,
            severity=Severity.LOW,
            message="test message",
            category="security",
            description="Checks for insecure patterns",
            metadata={"author": "test", "version": 1},
        )
        assert rule.category == "security"
        assert rule.description == "Checks for insecure patterns"
        assert rule.metadata == {"author": "test", "version": 1}
