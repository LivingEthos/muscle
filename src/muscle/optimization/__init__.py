"""
Optimization services for MUSCLE.

Provides project-local telemetry recording, prompt budgeting, workflow
recommendations, and benchmark imports without relying on global state.
"""

from .context_budgeter import ContextBudgeter
from .importers import ExternalBenchmarkImporter
from .optimizer import WorkflowOptimizer
from .prompt_context import build_telemetry_context, compose_prompt_envelope
from .recorder import LLMCallEvent, TelemetryRecorder
from .types import (
    OptimizationDecision,
    OptimizationRecommendation,
    PromptBudget,
    PromptEnvelope,
    SavingsEstimate,
    TelemetryContext,
)

__all__ = [
    "ContextBudgeter",
    "ExternalBenchmarkImporter",
    "LLMCallEvent",
    "OptimizationDecision",
    "OptimizationRecommendation",
    "PromptEnvelope",
    "PromptBudget",
    "SavingsEstimate",
    "TelemetryContext",
    "TelemetryRecorder",
    "WorkflowOptimizer",
    "build_telemetry_context",
    "compose_prompt_envelope",
]
