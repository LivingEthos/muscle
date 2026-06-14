"""
Optimization-layer types for MUSCLE.

These types keep telemetry, prompt budgeting, recommendations, and savings
tracking explicit and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class TelemetryContext:
    """Metadata describing a single model call."""

    project_path: str
    session_id: str
    stage: str
    workflow_name: str | None = None
    review_mode: str | None = None
    language: str | None = None
    complexity: str | None = None
    target_type: str | None = None
    task_category: str | None = None
    context_chars: int = 0
    context_strategy: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class PromptEnvelope:
    """Final prompt plus the optimization metadata used to assemble it."""

    prompt: str
    context_chars: int
    context_strategy: str
    metadata: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass
class PromptBudget:
    """A selected prompt context along with the strategy used to build it."""

    content: str
    strategy: str
    context_chars: int
    truncated: bool = False
    escalated: bool = False
    signals: list[str] = field(default_factory=list)


@dataclass
class OptimizationRecommendation:
    """A suggested safe optimization for the current project."""

    decision_type: str
    decision_scope: str
    comparable_key: str
    current_value: str
    recommended_value: str
    confidence: float
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationDecision:
    """A persisted recommendation or applied optimization."""

    decision_type: str
    decision_scope: str
    comparable_key: str
    recommendation: dict[str, Any]
    applied: bool = False
    confidence: float = 0.0
    outcome: dict[str, Any] = field(default_factory=dict)


@dataclass
class SavingsEstimate:
    """Estimated or observed token savings for a comparable bucket."""

    comparable_key: str
    actual_tokens: int
    baseline_tokens: int | None
    delta_tokens: int
    confidence: float
    estimation_type: str
    realized: bool
