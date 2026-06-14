"""Confidence scoring service for review suggestions.

Architecture Decision Record (ADR):
- Centralised confidence scoring decouples rule accuracy from presentation.
- Historical feedback loop lets MUSCLE learn which rules are reliable.
- Category base scores encode domain expertise (e.g. sql_injection is high-confidence).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConfidenceLevel(str, Enum):
    """Confidence levels for suggestions."""

    CERTAIN = "certain"  # 95-100% - Pattern match with high certainty
    HIGH = "high"  # 80-94%  - Strong indicators
    MEDIUM = "medium"  # 60-79%  - Moderate evidence
    LOW = "low"  # 40-59%  - Weak indicators
    UNCERTAIN = "uncertain"  # 0-39%   - Minimal evidence


@dataclass(frozen=True)
class ConfidenceScore:
    """Immutable confidence score for a suggestion."""

    score: float  # 0.0 to 1.0
    reasoning: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"Score must be between 0.0 and 1.0, got {self.score}")

    @property
    def level(self) -> ConfidenceLevel:
        """Get the confidence level category."""
        if self.score >= 0.95:
            return ConfidenceLevel.CERTAIN
        elif self.score >= 0.80:
            return ConfidenceLevel.HIGH
        elif self.score >= 0.60:
            return ConfidenceLevel.MEDIUM
        elif self.score >= 0.40:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.UNCERTAIN

    @property
    def percentage(self) -> int:
        """Get score as percentage."""
        return int(self.score * 100)

    def __str__(self) -> str:
        return f"{self.level.value} ({self.percentage}%)"

    def meets_threshold(self, threshold: float) -> bool:
        """Check if score meets a minimum threshold."""
        return self.score >= threshold


class Severity(str, Enum):
    """Review suggestion severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ConfidenceScorer:
    """Scores the confidence of suggestions based on multiple factors."""

    # Base confidence by rule category
    BASE_CONFIDENCE: dict[str, float] = {
        "sql_injection": 0.95,
        "hardcoded_secret": 0.90,
        "debug_mode": 0.95,
        "path_traversal": 0.85,
        "eval_exec": 0.98,
        "unused_export": 0.70,
        "circular_import": 0.80,
        "missing_dependency": 0.60,
        "inconsistent_signature": 0.65,
        "type_error": 0.75,
    }

    # Severity boost factors
    SEVERITY_BOOST: dict[Severity, float] = {
        Severity.CRITICAL: 0.05,
        Severity.HIGH: 0.03,
        Severity.MEDIUM: 0.0,
        Severity.LOW: -0.05,
        Severity.INFO: -0.05,
    }

    def __init__(self) -> None:
        self._rule_history: dict[str, tuple[int, int]] = {}  # rule -> (correct, total)

    def score(
        self,
        rule_id: str,
        severity: Severity,
        category: str = "",
        context_quality: float = 0.5,
        pattern_match_strength: float = 0.5,
    ) -> ConfidenceScore:
        """Calculate confidence score for a suggestion.

        Args:
            rule_id: Unique identifier for the rule.
            severity: Severity level of the finding.
            category: Category of the rule.
            context_quality: How much context is available (0.0-1.0).
            pattern_match_strength: How strong the pattern match is (0.0-1.0).

        Returns:
            ConfidenceScore with score and reasoning.

        Raises:
            ValueError: If context_quality or pattern_match_strength are outside 0.0-1.0.
        """
        if not 0.0 <= context_quality <= 1.0:
            raise ValueError(f"context_quality must be between 0.0 and 1.0, got {context_quality}")
        if not 0.0 <= pattern_match_strength <= 1.0:
            raise ValueError(
                f"pattern_match_strength must be between 0.0 and 1.0, got {pattern_match_strength}"
            )

        # Start with base confidence for the category
        base = self._get_base_confidence(category, rule_id)

        # Apply severity boost
        severity_adjustment = self.SEVERITY_BOOST.get(severity, 0.0)

        # Apply historical accuracy
        historical_adjustment = self._get_historical_adjustment(rule_id)

        # Apply context quality
        context_adjustment = (context_quality - 0.5) * 0.1

        # Apply pattern match strength
        pattern_adjustment = (pattern_match_strength - 0.5) * 0.15

        # Calculate final score
        score = (
            base
            + severity_adjustment
            + historical_adjustment
            + context_adjustment
            + pattern_adjustment
        )

        # Clamp to valid range
        score = max(0.0, min(1.0, score))

        # Build reasoning
        reasoning_parts = [
            f"Base confidence for {category or 'general'}: {base:.0%}",
            f"Severity adjustment ({severity.value}): {severity_adjustment:+.0%}",
        ]
        if historical_adjustment != 0:
            reasoning_parts.append(f"Historical accuracy: {historical_adjustment:+.0%}")
        reasoning_parts.append(
            f"Context quality ({context_quality:.0%}): {context_adjustment:+.0%}"
        )
        reasoning_parts.append(
            f"Pattern match ({pattern_match_strength:.0%}): {pattern_adjustment:+.0%}"
        )

        return ConfidenceScore(
            score=score,
            reasoning="; ".join(reasoning_parts),
        )

    def _get_base_confidence(self, category: str, rule_id: str) -> float:
        """Get base confidence for a category."""
        # Try category first, then extract from rule_id
        if category in self.BASE_CONFIDENCE:
            return self.BASE_CONFIDENCE[category]

        # Try to match rule_id prefix
        for key, value in self.BASE_CONFIDENCE.items():
            if key in rule_id.lower() or key.replace("_", "-") in rule_id.lower():
                return value

        return 0.70  # Default base confidence

    def _get_historical_adjustment(self, rule_id: str) -> float:
        """Get adjustment based on historical accuracy."""
        if rule_id not in self._rule_history:
            return 0.0

        correct, total = self._rule_history[rule_id]
        if total == 0:
            return 0.0

        accuracy = correct / total
        # Boost if accuracy is high, penalize if low
        if accuracy >= 0.9:
            return 0.05
        elif accuracy >= 0.7:
            return 0.02
        elif accuracy >= 0.5:
            return 0.0
        else:
            return -0.05

    def record_feedback(self, rule_id: str, was_correct: bool) -> None:
        """Record whether a suggestion was correct for historical tracking."""
        correct, total = self._rule_history.get(rule_id, (0, 0))
        if was_correct:
            correct += 1
        total += 1
        self._rule_history[rule_id] = (correct, total)

    def get_rule_accuracy(self, rule_id: str) -> float:
        """Get historical accuracy for a rule."""
        correct, total = self._rule_history.get(rule_id, (0, 0))
        if total == 0:
            return 0.0
        return correct / total

    def get_summary(self) -> dict[str, object]:
        """Get summary of confidence scoring history."""
        if not self._rule_history:
            return {"total_rules": 0, "average_accuracy": 0.0}

        total_correct = sum(c for c, _ in self._rule_history.values())
        total_predictions = sum(t for _, t in self._rule_history.values())

        return {
            "total_rules": len(self._rule_history),
            "total_predictions": total_predictions,
            "total_correct": total_correct,
            "average_accuracy": (
                total_correct / total_predictions if total_predictions > 0 else 0.0
            ),
            "rule_accuracies": {
                rule: f"{correct}/{total} ({correct / total:.0%})"
                for rule, (correct, total) in self._rule_history.items()
            },
        }
