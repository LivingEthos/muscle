"""
Unit tests for MemoryDecisionEngine.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.muscle.memory_decision_engine import (
    DecisionThresholds,
    DecisionType,
    MemoryDecisionEngine,
    ScoringWeights,
    ScoreBreakdown,
)
from tools.muscle.project_memory import ProjectMemory


@pytest.fixture
def temp_project_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def pm(temp_project_dir):
    """Create a ProjectMemory instance with a temporary directory."""
    return ProjectMemory(str(temp_project_dir))


@pytest.fixture
def engine(pm):
    """Create a MemoryDecisionEngine with default weights/thresholds."""
    return MemoryDecisionEngine(pm)


class TestScoring:
    """Test scoring computation."""

    def test_score_critical_high_recurrence(self, engine):
        """High severity + recurrence should produce high score."""
        score = engine.score_finding(
            severity="critical",
            recurrence_count=5,
            success_rate=0.8,
            task_relevance=0.9,
            token_savings_estimate=500,
        )
        # critical=10 + 5*2=10 + 0.8*3=2.4 + 0.9*1.5=1.35 + (1+500/1000)*1.5=1.5*1.5=2.25
        # = 10 + 10 + 2.4 + 1.35 + 2.25 = 26.0
        assert score >= 25.0

    def test_score_low_recurrence_low_success(self, engine):
        """Low severity + low recurrence should produce low/negative score."""
        score = engine.score_finding(
            severity="low",
            recurrence_count=1,
            success_rate=0.1,
            task_relevance=0.1,
            token_savings_estimate=0,
        )
        # low=1 + 1*2=2 + 0.1*3=0.3 + 0.1*1.5=0.15 + 0 = 3.45
        assert 3.0 <= score <= 4.0

    def test_score_high_severity_no_recurrence(self, engine):
        """High severity but no recurrence should still score well."""
        score = engine.score_finding(
            severity="high",
            recurrence_count=0,
            success_rate=0.0,
            task_relevance=0.5,
            token_savings_estimate=100,
        )
        # high=5 + 0 + 0 + 0.5*1.5=0.75 + (1+100/1000)*1.5=1.65
        # = 5 + 0.75 + 1.65 = 7.4
        assert score >= 7.0

    def test_score_zero_token_savings(self, engine):
        """Zero token savings should not contribute to score."""
        score_with_tokens = engine.score_finding(
            severity="medium",
            recurrence_count=2,
            success_rate=0.5,
            task_relevance=0.5,
            token_savings_estimate=1000,
        )
        score_without_tokens = engine.score_finding(
            severity="medium",
            recurrence_count=2,
            success_rate=0.5,
            task_relevance=0.5,
            token_savings_estimate=0,
        )
        # With tokens should be higher
        assert score_with_tokens > score_without_tokens

    def test_score_breakdown_components(self, engine):
        """Score breakdown should show individual components."""
        breakdown = engine.score_breakdown(
            severity="high",
            recurrence_count=3,
            success_rate=0.75,
            task_relevance=0.6,
            token_savings_estimate=800,
        )
        assert isinstance(breakdown, ScoreBreakdown)
        assert breakdown.severity_score == 5.0
        assert breakdown.recurrence_score == 6.0  # 3 * 2.0
        assert breakdown.success_rate_score == 2.25  # 0.75 * 3.0
        assert breakdown.task_relevance_score == pytest.approx(0.9)  # 0.6 * 1.5
        # token_savings = (1 + 800/1000) * 1.5 = 1.8 * 1.5 = 2.7
        assert breakdown.token_savings_score == 2.7
        # total = 5 + 6 + 2.25 + 0.9 + 2.7 = 16.85
        assert breakdown.total_score == 16.85


class TestDecisions:
    """Test decision emission based on thresholds."""

    def test_decision_promote_rule(self, engine):
        """Score >= 20 should produce PROMOTE_RULE."""
        decision = engine.decide(25.0)
        assert decision == DecisionType.PROMOTE_RULE

    def test_decision_create_skill(self, engine):
        """Score >= 30 should produce CREATE_SKILL."""
        decision = engine.decide(35.0)
        assert decision == DecisionType.CREATE_SKILL

    def test_decision_create_agent(self, engine):
        """Score >= 50 should produce CREATE_AGENT."""
        decision = engine.decide(55.0)
        assert decision == DecisionType.CREATE_AGENT

    def test_decision_archive_pattern(self, engine):
        """Score <= -5 should produce ARCHIVE_PATTERN."""
        decision = engine.decide(-10.0)
        assert decision == DecisionType.ARCHIVE_PATTERN

    def test_decision_retain_db_only(self, engine):
        """Score between archive and promote should produce RETAIN_DB_ONLY."""
        decision = engine.decide(10.0)
        assert decision == DecisionType.RETAIN_DB_ONLY

    def test_threshold_boundaries(self, engine):
        """Test exact threshold boundaries."""
        # Just below promote threshold
        assert engine.decide(19.9) == DecisionType.RETAIN_DB_ONLY
        # At promote threshold
        assert engine.decide(20.0) == DecisionType.PROMOTE_RULE
        # Just below skill threshold
        assert engine.decide(29.9) == DecisionType.PROMOTE_RULE
        # At skill threshold
        assert engine.decide(30.0) == DecisionType.CREATE_SKILL
        # Just below agent threshold
        assert engine.decide(49.9) == DecisionType.CREATE_SKILL
        # At agent threshold
        assert engine.decide(50.0) == DecisionType.CREATE_AGENT
        # Just above archive threshold
        assert engine.decide(-4.9) == DecisionType.RETAIN_DB_ONLY
        # At archive threshold
        assert engine.decide(-5.0) == DecisionType.ARCHIVE_PATTERN


class TestCustomWeightsAndThresholds:
    """Test with custom weights and thresholds."""

    def test_custom_weights(self, temp_project_dir):
        """Custom weights should affect scoring."""
        custom_weights = ScoringWeights(
            severity_critical=20.0,
            severity_high=10.0,
            severity_medium=4.0,
            severity_low=2.0,
            recurrence=3.0,
            success_rate=5.0,
            task_relevance=2.0,
            token_savings=2.0,
        )
        pm = ProjectMemory(str(temp_project_dir))
        engine = MemoryDecisionEngine(pm, weights=custom_weights)

        score = engine.score_finding(
            severity="critical",
            recurrence_count=1,
            success_rate=0.5,
            task_relevance=0.5,
            token_savings_estimate=500,
        )
        # With custom weights: critical=20 + 1*3=3 + 0.5*5=2.5 + 0.5*2=1 + (1+500/1000)*2=3
        # = 20 + 3 + 2.5 + 1 + 3 = 29.5
        assert score >= 29.0

    def test_custom_thresholds(self, temp_project_dir):
        """Custom thresholds should affect decision emission."""
        custom_thresholds = DecisionThresholds(
            promote=10.0,
            skill=15.0,
            agent=25.0,
            archive=-2.0,
        )
        pm = ProjectMemory(str(temp_project_dir))
        engine = MemoryDecisionEngine(pm, thresholds=custom_thresholds)

        # Score of 12 should trigger skill with custom threshold (>= 15)
        assert engine.decide(12.0) == DecisionType.PROMOTE_RULE
        # Score of 16 should trigger skill
        assert engine.decide(16.0) == DecisionType.CREATE_SKILL
        # Score of 26 should trigger agent
        assert engine.decide(26.0) == DecisionType.CREATE_AGENT
        # Score of -3 should trigger archive
        assert engine.decide(-3.0) == DecisionType.ARCHIVE_PATTERN


class TestRecordDecision:
    """Test decision persistence to DB."""

    def test_record_decision_persists(self, engine, temp_project_dir):
        """record_decision should write to project_memory.db."""
        decision_id = engine.record_decision(
            project_path=str(temp_project_dir),
            decision=DecisionType.PROMOTE_RULE,
            source_table="review_findings",
            source_id=1,
            evidence={"severity": "high", "recurrence_count": 3},
            score=25.0,
            reasoning="test reasoning",
        )
        assert decision_id > 0

    def test_evaluate_and_record_combined(self, engine, temp_project_dir):
        """evaluate_and_record should score, decide, and persist in one call."""
        decision, score = engine.evaluate_and_record(
            project_path=str(temp_project_dir),
            severity="critical",
            recurrence_count=5,
            success_rate=0.8,
            task_relevance=0.9,
            token_savings_estimate=500,
            source_table="review_findings",
            source_id=42,
        )
        assert decision == DecisionType.PROMOTE_RULE
        assert score >= 25.0


class TestSeverityMapping:
    """Test severity string handling."""

    def test_severity_case_insensitive(self, engine):
        """Severity should be case-insensitive."""
        score_lower = engine.score_finding(
            severity="critical",
            recurrence_count=0,
            success_rate=0.0,
            task_relevance=0.0,
            token_savings_estimate=0,
        )
        score_upper = engine.score_finding(
            severity="CRITICAL",
            recurrence_count=0,
            success_rate=0.0,
            task_relevance=0.0,
            token_savings_estimate=0,
        )
        score_mixed = engine.score_finding(
            severity="Critical",
            recurrence_count=0,
            success_rate=0.0,
            task_relevance=0.0,
            token_savings_estimate=0,
        )
        assert score_lower == score_upper == score_mixed

    def test_unknown_severity_defaults_to_low(self, engine):
        """Unknown severity should default to low (1.0)."""
        score_unknown = engine.score_finding(
            severity="unknown",
            recurrence_count=0,
            success_rate=0.0,
            task_relevance=0.0,
            token_savings_estimate=0,
        )
        score_low = engine.score_finding(
            severity="low",
            recurrence_count=0,
            success_rate=0.0,
            task_relevance=0.0,
            token_savings_estimate=0,
        )
        assert score_unknown == score_low == 1.0
