"""
MemoryDecisionEngine - Scores findings and emits structured promotion decisions.

Architecture Decision Record (ADR):
- Evidence-driven scoring replaces ad-hoc promotion decisions
- Composite score based on severity, recurrence, fix success rate, task relevance, token savings
- Structured decisions written to project_memory.db for audit trail
- Decisions drive LearningPipeline actions (promote, archive, skill/agent creation)

This engine is the central router for the self-learning system.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)


class DecisionType(Enum):
    """Structured decisions emitted by the MemoryDecisionEngine."""

    PROMOTE_RULE = "promote_rule"
    RETAIN_DB_ONLY = "retain_db_only"
    ARCHIVE_PATTERN = "archive_pattern"
    CREATE_SKILL = "create_skill"
    CREATE_AGENT = "create_agent"


@dataclass
class ScoringWeights:
    """Configurable weights for the composite scoring formula."""

    severity_critical: float = 10.0
    severity_high: float = 5.0
    severity_medium: float = 2.0
    severity_low: float = 1.0
    recurrence: float = 2.0
    success_rate: float = 3.0
    task_relevance: float = 1.5
    token_savings: float = 1.5


@dataclass
class DecisionThresholds:
    """Thresholds for triggering different decision types."""

    promote: float = 20.0  # → promote to CLAUDE.md
    skill: float = 30.0  # → create skill
    agent: float = 50.0  # → create agent
    archive: float = -5.0  # → archive (negative = bad)


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of a finding's composite score."""

    severity_score: float
    recurrence_score: float
    success_rate_score: float
    task_relevance_score: float
    token_savings_score: float
    total_score: float


class MemoryDecisionEngine:
    """
    Scores findings/rules and emits structured decisions.

    The engine computes a composite score using weighted factors:
    - severity (critical=10, high=5, medium=2, low=1)
    - recurrence (count × 2.0)
    - fix success rate (rate × 3.0)
    - task relevance (0.0-1.0 × 1.5)
    - estimated token savings (log-scaled × 1.5)

    Based on the score and thresholds, it emits a DecisionType that
    drives the LearningPipeline's actions.
    """

    def __init__(
        self,
        project_memory: ProjectMemory,
        weights: ScoringWeights | None = None,
        thresholds: DecisionThresholds | None = None,
    ):
        """
        Initialize the MemoryDecisionEngine.

        Args:
            project_memory: The ProjectMemory database access layer.
            weights: Optional custom scoring weights.
            thresholds: Optional custom decision thresholds.
        """
        self._pm = project_memory
        self.weights = weights or ScoringWeights()
        self.thresholds = thresholds or DecisionThresholds()

    def _get_severity_score(self, severity: str) -> float:
        """Get severity score using weights."""
        severity_lower = severity.lower()
        if severity_lower == "critical":
            return self.weights.severity_critical
        elif severity_lower == "high":
            return self.weights.severity_high
        elif severity_lower == "medium":
            return self.weights.severity_medium
        elif severity_lower == "low":
            return self.weights.severity_low
        else:
            # Unknown severity defaults to low weight
            return self.weights.severity_low

    def score_finding(
        self,
        severity: str,
        recurrence_count: int,
        success_rate: float,
        task_relevance: float,
        token_savings_estimate: int,
    ) -> float:
        """
        Compute the composite score for a finding.

        Args:
            severity: Severity level (critical, high, medium, low).
            recurrence_count: Number of times this pattern has recurred.
            success_rate: Fix success rate (0.0 to 1.0).
            task_relevance: How relevant this is to current tasks (0.0 to 1.0).
            token_savings_estimate: Estimated tokens saved if this is fixed.

        Returns:
            Composite score (float). Higher = more worthy of promotion.
        """
        severity_score = self._get_severity_score(severity)

        recurrence_score = recurrence_count * self.weights.recurrence
        success_rate_score = success_rate * self.weights.success_rate
        task_relevance_score = task_relevance * self.weights.task_relevance

        # Log-scale token savings to dampen extreme values
        if token_savings_estimate > 0:
            token_savings_score = (1 + (token_savings_estimate / 1000)) * self.weights.token_savings
        else:
            token_savings_score = 0.0

        total = (
            severity_score
            + recurrence_score
            + success_rate_score
            + task_relevance_score
            + token_savings_score
        )

        return total

    def score_breakdown(
        self,
        severity: str,
        recurrence_count: int,
        success_rate: float,
        task_relevance: float,
        token_savings_estimate: int,
    ) -> ScoreBreakdown:
        """
        Compute detailed score breakdown for transparency.

        Returns a ScoreBreakdown showing each component of the composite score.
        """
        severity_score = self._get_severity_score(severity)
        recurrence_score = recurrence_count * self.weights.recurrence
        success_rate_score = success_rate * self.weights.success_rate
        task_relevance_score = task_relevance * self.weights.task_relevance

        if token_savings_estimate > 0:
            token_savings_score = (1 + (token_savings_estimate / 1000)) * self.weights.token_savings
        else:
            token_savings_score = 0.0

        total = (
            severity_score
            + recurrence_score
            + success_rate_score
            + task_relevance_score
            + token_savings_score
        )

        return ScoreBreakdown(
            severity_score=severity_score,
            recurrence_score=recurrence_score,
            success_rate_score=success_rate_score,
            task_relevance_score=task_relevance_score,
            token_savings_score=token_savings_score,
            total_score=total,
        )

    def decide(self, score: float, context: dict[str, Any] | None = None) -> DecisionType:
        """
        Emit a structured decision based on the composite score.

        Args:
            score: The composite score from score_finding().
            context: Optional context dict (unused, reserved for future).

        Returns:
            DecisionType enum value indicating the action to take.
        """
        if score >= self.thresholds.agent:
            return DecisionType.CREATE_AGENT
        elif score >= self.thresholds.skill:
            return DecisionType.CREATE_SKILL
        elif score >= self.thresholds.promote:
            return DecisionType.PROMOTE_RULE
        elif score <= self.thresholds.archive:
            return DecisionType.ARCHIVE_PATTERN
        else:
            return DecisionType.RETAIN_DB_ONLY

    def record_decision(
        self,
        project_path: str,
        decision: DecisionType,
        source_table: str,
        source_id: int,
        evidence: dict[str, Any],
        score: float,
        reasoning: str,
    ) -> int:
        """
        Persist a decision to project_memory.db for audit trail.

        Args:
            project_path: Absolute path to the project.
            decision: The DecisionType that was emitted.
            source_table: Table name the finding came from.
            source_id: Row ID in the source table.
            evidence: Dict of evidence used for scoring.
            score: The composite score computed.
            reasoning: Human-readable reasoning for this decision.

        Returns:
            The row ID of the inserted memory_decision record.
        """
        try:
            return self._pm.insert_decision(
                project_path=project_path,
                decision_type=decision.value,
                source_table=source_table,
                source_id=source_id,
                evidence_json=json.dumps(evidence),
                score_json=json.dumps({"score": score}),
                reasoning=reasoning,
            )
        except Exception as e:
            logger.warning(f"Failed to record memory decision: {e}")
            return 0

    def evaluate_and_record(
        self,
        project_path: str,
        severity: str,
        recurrence_count: int,
        success_rate: float,
        task_relevance: float,
        token_savings_estimate: int,
        source_table: str,
        source_id: int,
    ) -> tuple[DecisionType, float]:
        """
        Convenience method: score, decide, and record in one call.

        Returns:
            Tuple of (DecisionType, score) for immediate use by caller.
        """
        score = self.score_finding(
            severity=severity,
            recurrence_count=recurrence_count,
            success_rate=success_rate,
            task_relevance=task_relevance,
            token_savings_estimate=token_savings_estimate,
        )

        decision = self.decide(score, context=None)

        breakdown = self.score_breakdown(
            severity=severity,
            recurrence_count=recurrence_count,
            success_rate=success_rate,
            task_relevance=task_relevance,
            token_savings_estimate=token_savings_estimate,
        )

        reasoning = (
            f"severity={breakdown.severity_score:.1f}, "
            f"recurrence={breakdown.recurrence_score:.1f}, "
            f"success_rate={breakdown.success_rate_score:.1f}, "
            f"task_relevance={breakdown.task_relevance_score:.1f}, "
            f"token_savings={breakdown.token_savings_score:.1f}, "
            f"total={breakdown.total_score:.1f}"
        )

        evidence = {
            "severity": severity,
            "recurrence_count": recurrence_count,
            "success_rate": success_rate,
            "task_relevance": task_relevance,
            "token_savings_estimate": token_savings_estimate,
        }

        self.record_decision(
            project_path=project_path,
            decision=decision,
            source_table=source_table,
            source_id=source_id,
            evidence=evidence,
            score=score,
            reasoning=reasoning,
        )

        return decision, score
