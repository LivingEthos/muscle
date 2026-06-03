"""Tests for confidence_scorer."""

from __future__ import annotations

import pytest

from tools.muscle.services.confidence_scorer import ConfidenceScorer, Severity


def test_base_confidence_for_known_category():
    scorer = ConfidenceScorer()
    result = scorer.score("sql-001", Severity.HIGH, category="sql_injection")
    assert result.score >= 0.95
    assert "sql_injection" in result.reasoning


def test_severity_boost_applied():
    scorer = ConfidenceScorer()
    critical = scorer.score("r1", Severity.CRITICAL, category="debug_mode")
    high = scorer.score("r1", Severity.HIGH, category="debug_mode")
    low = scorer.score("r1", Severity.LOW, category="debug_mode")
    assert critical.score > high.score > low.score


def test_historical_adjustment_changes_score():
    scorer = ConfidenceScorer()
    before = scorer.score("hist-rule", Severity.MEDIUM)
    # Record 10 correct predictions (accuracy >= 0.9)
    for _ in range(10):
        scorer.record_feedback("hist-rule", was_correct=True)
    after = scorer.score("hist-rule", Severity.MEDIUM)
    assert after.score > before.score


def test_record_feedback_tracks_accuracy():
    scorer = ConfidenceScorer()
    scorer.record_feedback("rule-a", was_correct=True)
    scorer.record_feedback("rule-a", was_correct=False)
    assert scorer.get_rule_accuracy("rule-a") == 0.5


def test_get_summary_with_no_history():
    scorer = ConfidenceScorer()
    summary = scorer.get_summary()
    assert summary["total_rules"] == 0
    assert summary["average_accuracy"] == 0.0


def test_get_summary_with_history():
    scorer = ConfidenceScorer()
    scorer.record_feedback("rule-x", was_correct=True)
    scorer.record_feedback("rule-x", was_correct=True)
    scorer.record_feedback("rule-y", was_correct=False)
    summary = scorer.get_summary()
    assert summary["total_rules"] == 2
    assert summary["total_predictions"] == 3
    assert summary["total_correct"] == 2
    assert summary["average_accuracy"] == pytest.approx(2 / 3)
    assert "rule-x" in summary["rule_accuracies"]


def test_base_confidence_eval_exec():
    scorer = ConfidenceScorer()
    result = scorer.score("eval-001", Severity.CRITICAL, category="eval_exec")
    assert result.score >= 0.98
    assert "eval_exec" in result.reasoning


def test_base_confidence_hardcoded_secret():
    scorer = ConfidenceScorer()
    result = scorer.score("secret-001", Severity.HIGH, category="hardcoded_secret")
    assert result.score >= 0.90
    assert "hardcoded_secret" in result.reasoning


def test_base_confidence_path_traversal():
    scorer = ConfidenceScorer()
    result = scorer.score("path-001", Severity.HIGH, category="path_traversal")
    assert result.score >= 0.85
    assert "path_traversal" in result.reasoning


def test_base_confidence_unused_export():
    scorer = ConfidenceScorer()
    result = scorer.score("unused-001", Severity.LOW, category="unused_export")
    assert result.score == pytest.approx(0.65, abs=1e-9)  # 0.70 base - 0.05 severity
    assert "unused_export" in result.reasoning


def test_base_confidence_circular_import():
    scorer = ConfidenceScorer()
    result = scorer.score("circ-001", Severity.MEDIUM, category="circular_import")
    assert result.score >= 0.80
    assert "circular_import" in result.reasoning


def test_base_confidence_missing_dependency():
    scorer = ConfidenceScorer()
    result = scorer.score("dep-001", Severity.LOW, category="missing_dependency")
    assert result.score == pytest.approx(0.55, abs=1e-9)  # 0.60 base - 0.05 severity
    assert "missing_dependency" in result.reasoning


def test_base_confidence_inconsistent_signature():
    scorer = ConfidenceScorer()
    result = scorer.score("sig-001", Severity.MEDIUM, category="inconsistent_signature")
    assert result.score >= 0.65
    assert "inconsistent_signature" in result.reasoning


def test_base_confidence_type_error():
    scorer = ConfidenceScorer()
    result = scorer.score("type-001", Severity.HIGH, category="type_error")
    assert result.score >= 0.75
    assert "type_error" in result.reasoning


def test_get_rule_accuracy_no_history():
    scorer = ConfidenceScorer()
    assert scorer.get_rule_accuracy("unknown-rule") == 0.0


def test_get_rule_accuracy_perfect():
    scorer = ConfidenceScorer()
    for _ in range(5):
        scorer.record_feedback("perfect-rule", was_correct=True)
    assert scorer.get_rule_accuracy("perfect-rule") == 1.0


def test_get_rule_accuracy_zero():
    scorer = ConfidenceScorer()
    for _ in range(5):
        scorer.record_feedback("bad-rule", was_correct=False)
    assert scorer.get_rule_accuracy("bad-rule") == 0.0


def test_get_summary_empty():
    scorer = ConfidenceScorer()
    summary = scorer.get_summary()
    assert summary == {"total_rules": 0, "average_accuracy": 0.0}


def test_get_summary_rule_accuracies_format():
    scorer = ConfidenceScorer()
    scorer.record_feedback("rule-a", was_correct=True)
    scorer.record_feedback("rule-a", was_correct=False)
    summary = scorer.get_summary()
    assert summary["rule_accuracies"]["rule-a"] == "1/2 (50%)"

