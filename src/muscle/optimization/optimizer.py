"""
Workflow optimizer and savings tracker for MUSCLE.

Builds project-scoped recommendations from MUSCLE telemetry and persisted review
outcomes. Recommendations are conservative and only target safe runtime knobs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from statistics import median
from typing import Any

from ..project_memory import ProjectMemory
from .types import OptimizationRecommendation, SavingsEstimate

logger = logging.getLogger(__name__)

SAFE_CONTEXT_KEYS = {
    "semantic_review": "optimize.context.semantic_review",
    "fix_generation": "optimize.context.fix_generation",
}
WORKFLOW_STATE_KEY = "optimize.default_workflow"


class WorkflowOptimizer:
    """Compute project-local workflow and context recommendations."""

    def __init__(self, project_memory: ProjectMemory, project_path: str):
        self._pm = project_memory
        self.project_path = str(Path(project_path).resolve())

    def comparable_key(
        self,
        stage: str,
        language: str | None,
        complexity: str | None,
        target_type: str | None,
    ) -> str:
        """Build a stable comparable bucket key."""
        return "|".join(
            [
                stage,
                language or "unknown",
                complexity or "unknown",
                target_type or "unknown",
            ]
        )

    def get_applied_settings(self) -> dict[str, str]:
        """Read persisted optimization settings for the current project."""
        values: dict[str, str] = {}
        workflow_state = self._pm.get_automation_state(self.project_path, WORKFLOW_STATE_KEY)
        if workflow_state and workflow_state.get("state_value"):
            values[WORKFLOW_STATE_KEY] = str(workflow_state["state_value"])
        for state_key in SAFE_CONTEXT_KEYS.values():
            row = self._pm.get_automation_state(self.project_path, state_key)
            if row and row.get("state_value"):
                values[state_key] = str(row["state_value"])
        return values

    def _current_canonical_model_key(self) -> str | None:
        """Return the latest resolved canonical model key for this project."""
        latest_identity = self._pm.get_latest_model_identity(self.project_path)
        canonical_model_key = (
            latest_identity.get("canonical_model_key") if latest_identity else None
        )
        return str(canonical_model_key) if canonical_model_key else None

    def _call_canonical_model_key(self, call: dict[str, Any]) -> str | None:
        """Extract a persisted canonical model key from one llm_call row."""
        direct_value = call.get("canonical_model_key")
        if direct_value:
            return str(direct_value)
        raw_metadata = call.get("metadata_json")
        if not raw_metadata:
            return None
        try:
            metadata = json.loads(raw_metadata)
        except json.JSONDecodeError:
            return None
        canonical_model_key = metadata.get("canonical_model_key")
        return str(canonical_model_key) if canonical_model_key else None

    def record_review_outcome(
        self,
        session_id: str,
        workflow_name: str,
        language: str | None,
        complexity: str | None,
        target_type: str | None,
        total_tokens: int,
        duration_ms: int,
        valid_findings: int,
        verified_fixes: int,
        one_shot_verified_fixes: int,
        high_critical_findings: int,
        validation_success: bool,
        success: bool,
        stage_totals: dict[str, int] | None = None,
    ) -> SavingsEstimate:
        """Persist aggregate workflow metrics and record savings deltas."""
        self._pm.upsert_workflow_rollup(
            project_path=self.project_path,
            workflow_name=workflow_name,
            stage="review_total",
            language=language or "unknown",
            complexity=complexity or "unknown",
            target_type=target_type or "unknown",
            success_count=1 if success else 0,
            total_tokens=total_tokens,
            total_duration_ms=duration_ms,
            valid_findings=valid_findings,
            verified_fixes=verified_fixes,
            one_shot_verified_fixes=one_shot_verified_fixes,
            high_critical_findings=high_critical_findings,
            validation_successes=1 if validation_success else 0,
            last_session_id=session_id,
        )
        for stage_name, stage_tokens in (stage_totals or {}).items():
            self._pm.upsert_workflow_rollup(
                project_path=self.project_path,
                workflow_name=workflow_name,
                stage=stage_name,
                language=language or "unknown",
                complexity=complexity or "unknown",
                target_type=target_type or "unknown",
                success_count=1 if success else 0,
                total_tokens=stage_tokens,
                total_duration_ms=0,
                last_session_id=session_id,
            )

        estimate = self.estimate_savings(
            session_id=session_id,
            stage="review_total",
            workflow_name=workflow_name,
            language=language,
            complexity=complexity,
            target_type=target_type,
            actual_tokens=total_tokens,
        )
        self._pm.insert_token_savings_entry(
            project_path=self.project_path,
            session_id=session_id,
            stage="review_total",
            workflow_name=workflow_name,
            comparable_key=estimate.comparable_key,
            baseline_tokens=estimate.baseline_tokens,
            actual_tokens=estimate.actual_tokens,
            delta_tokens=estimate.delta_tokens,
            confidence=estimate.confidence,
            realized=estimate.realized,
            estimation_type=estimate.estimation_type,
            metadata_json=json.dumps(
                {
                    "valid_findings": valid_findings,
                    "verified_fixes": verified_fixes,
                    "high_critical_findings": high_critical_findings,
                }
            ),
        )
        return estimate

    def estimate_savings(
        self,
        session_id: str,
        stage: str,
        workflow_name: str,
        language: str | None,
        complexity: str | None,
        target_type: str | None,
        actual_tokens: int,
    ) -> SavingsEstimate:
        """Estimate baseline token use from comparable historical runs."""
        comparable_key = self.comparable_key(stage, language, complexity, target_type)
        samples = self._collect_comparable_token_samples(
            stage=stage,
            workflow_name=workflow_name,
            language=language,
            complexity=complexity,
            target_type=target_type,
            exclude_session_id=session_id,
        )
        baseline = int(median(samples)) if samples else None
        delta = 0 if baseline is None else max(0, baseline - actual_tokens)
        if baseline is not None and actual_tokens > baseline:
            delta = baseline - actual_tokens
        sample_count = len(samples)
        estimation_type = "observed" if sample_count >= 10 else "estimated"
        confidence = min(1.0, sample_count / 15.0) if sample_count else 0.1
        return SavingsEstimate(
            comparable_key=comparable_key,
            actual_tokens=actual_tokens,
            baseline_tokens=baseline,
            delta_tokens=delta,
            confidence=confidence,
            estimation_type=estimation_type,
            realized=sample_count >= 10,
        )

    def get_status(self) -> dict[str, Any]:
        """Return optimization summary for CLI/TUI views."""
        return {
            "hotspots": self._pm.get_llm_stage_summary(self.project_path, limit=6),
            "savings": self._pm.get_token_savings_summary(self.project_path),
            "settings": self.get_applied_settings(),
            "recommendations": [rec.__dict__ for rec in self.build_recommendations()],
        }

    def build_recommendations(self) -> list[OptimizationRecommendation]:
        """Build safe workflow and context recommendations."""
        recommendations: list[OptimizationRecommendation] = []
        recommendations.extend(self._workflow_recommendations())
        recommendations.extend(self._context_recommendations())
        return recommendations

    def apply_recommendations(self, safe_only: bool = True) -> list[OptimizationRecommendation]:
        """Apply safe recommendations by storing project-local automation state."""
        applied: list[OptimizationRecommendation] = []
        for recommendation in self.build_recommendations():
            if safe_only and recommendation.decision_type not in {"workflow", "context"}:
                continue
            if recommendation.decision_type == "workflow":
                self._pm.set_automation_state(
                    self.project_path,
                    WORKFLOW_STATE_KEY,
                    recommendation.recommended_value,
                )
            elif recommendation.decision_type == "context":
                state_key = SAFE_CONTEXT_KEYS.get(recommendation.decision_scope)
                if state_key is None:
                    continue
                self._pm.set_automation_state(
                    self.project_path,
                    state_key,
                    recommendation.recommended_value,
                )
            else:
                continue

            self._pm.insert_optimization_decision(
                project_path=self.project_path,
                decision_type=recommendation.decision_type,
                decision_scope=recommendation.decision_scope,
                comparable_key=recommendation.comparable_key,
                recommendation_json=json.dumps(recommendation.__dict__),
                applied=True,
                confidence=recommendation.confidence,
                outcome_json=json.dumps({"safe_only": safe_only}),
            )
            applied.append(recommendation)
        return applied

    def _workflow_recommendations(self) -> list[OptimizationRecommendation]:
        rollups = self._pm.list_workflow_rollups(self.project_path, stage="review_total", limit=50)
        by_workflow: dict[str, dict[str, Any]] = {}
        for row in rollups:
            workflow_name = str(row.get("workflow_name") or "")
            if not workflow_name:
                continue
            bucket = by_workflow.setdefault(
                workflow_name,
                {
                    "run_count": 0,
                    "success_count": 0,
                    "total_tokens": 0,
                    "verified_fixes": 0,
                    "one_shot_verified_fixes": 0,
                    "high_critical_findings": 0,
                    "validation_successes": 0,
                },
            )
            for key in bucket:
                bucket[key] += int(row.get(key, 0) or 0)

        current = self.get_applied_settings().get(WORKFLOW_STATE_KEY, "review-smart")
        current_metrics = by_workflow.get(current)
        if current_metrics is None:
            return []

        current_runs = current_metrics["run_count"]
        if current_runs < 15:
            return []

        current_avg_tokens = current_metrics["total_tokens"] / max(
            1, current_metrics["success_count"]
        )
        current_validation_rate = current_metrics["validation_successes"] / max(1, current_runs)
        current_high_yield = current_metrics["high_critical_findings"] / max(1, current_runs)
        current_one_shot = current_metrics["one_shot_verified_fixes"] / max(
            1, current_metrics["verified_fixes"] or current_runs
        )

        recommendations: list[OptimizationRecommendation] = []
        for workflow_name, metrics in by_workflow.items():
            if workflow_name == current or metrics["run_count"] < 15:
                continue
            candidate_avg_tokens = metrics["total_tokens"] / max(1, metrics["success_count"])
            candidate_validation_rate = metrics["validation_successes"] / max(
                1, metrics["run_count"]
            )
            candidate_high_yield = metrics["high_critical_findings"] / max(1, metrics["run_count"])
            candidate_one_shot = metrics["one_shot_verified_fixes"] / max(
                1, metrics["verified_fixes"] or metrics["run_count"]
            )
            token_gain = (current_avg_tokens - candidate_avg_tokens) / max(1.0, current_avg_tokens)
            one_shot_gain = candidate_one_shot - current_one_shot
            if candidate_validation_rate < current_validation_rate:
                continue
            if candidate_high_yield + 1e-9 < current_high_yield:
                continue
            if token_gain < 0.15 and one_shot_gain < 0.10:
                continue

            recommendations.append(
                OptimizationRecommendation(
                    decision_type="workflow",
                    decision_scope="review",
                    comparable_key="review_total",
                    current_value=current,
                    recommended_value=workflow_name,
                    confidence=min(0.95, metrics["run_count"] / 20.0),
                    reason=(
                        f"{workflow_name} uses fewer tokens per successful run "
                        f"and keeps validation/high-severity yield at or above {current}."
                    ),
                    evidence={
                        "current_avg_tokens": round(current_avg_tokens, 1),
                        "candidate_avg_tokens": round(candidate_avg_tokens, 1),
                        "current_validation_rate": round(current_validation_rate, 3),
                        "candidate_validation_rate": round(candidate_validation_rate, 3),
                        "current_one_shot_rate": round(current_one_shot, 3),
                        "candidate_one_shot_rate": round(candidate_one_shot, 3),
                    },
                )
            )
        return recommendations

    def _context_recommendations(self) -> list[OptimizationRecommendation]:
        calls = self._pm.list_llm_calls(project_path=self.project_path, limit=5000)
        if not calls:
            return []

        current_canonical_model_key = self._current_canonical_model_key()
        by_stage: dict[str, dict[str, dict[str, float]]] = {}
        for call in calls:
            if current_canonical_model_key:
                if self._call_canonical_model_key(call) != current_canonical_model_key:
                    continue
            stage = str(call.get("stage") or "")
            if stage not in SAFE_CONTEXT_KEYS:
                continue
            strategy = str(call.get("context_strategy") or "default")
            bucket = by_stage.setdefault(stage, {}).setdefault(
                strategy,
                {"count": 0.0, "tokens": 0.0, "parse_success": 0.0, "validation_success": 0.0},
            )
            bucket["count"] += 1
            bucket["tokens"] += int(call.get("input_tokens", 0) or 0) + int(
                call.get("output_tokens", 0) or 0
            )
            if call.get("parse_success") == 1:
                bucket["parse_success"] += 1
            if call.get("validation_success") == 1:
                bucket["validation_success"] += 1

        settings = self.get_applied_settings()
        recommendations: list[OptimizationRecommendation] = []
        for stage, strategies in by_stage.items():
            current_value = settings.get(SAFE_CONTEXT_KEYS[stage], "default")
            current_metrics = strategies.get(current_value)
            if current_metrics is None or current_metrics["count"] < 10:
                continue
            current_avg_tokens = current_metrics["tokens"] / current_metrics["count"]
            current_parse_rate = current_metrics["parse_success"] / current_metrics["count"]
            current_validation_rate = (
                current_metrics["validation_success"] / current_metrics["count"]
            )

            for strategy_name, metrics in strategies.items():
                if strategy_name == current_value or metrics["count"] < 10:
                    continue
                avg_tokens = metrics["tokens"] / metrics["count"]
                parse_rate = metrics["parse_success"] / metrics["count"]
                validation_rate = metrics["validation_success"] / metrics["count"]
                token_gain = (current_avg_tokens - avg_tokens) / max(1.0, current_avg_tokens)
                if parse_rate + 1e-9 < current_parse_rate:
                    continue
                if validation_rate + 1e-9 < current_validation_rate:
                    continue
                if token_gain < 0.15:
                    continue
                recommendations.append(
                    OptimizationRecommendation(
                        decision_type="context",
                        decision_scope=stage,
                        comparable_key=stage,
                        current_value=current_value,
                        recommended_value=strategy_name,
                        confidence=min(0.95, metrics["count"] / 20.0),
                        reason=(
                            f"{strategy_name} lowers token use for {stage} "
                            f"without hurting parse or validation success."
                        ),
                        evidence={
                            "current_avg_tokens": round(current_avg_tokens, 1),
                            "candidate_avg_tokens": round(avg_tokens, 1),
                            "current_parse_rate": round(current_parse_rate, 3),
                            "candidate_parse_rate": round(parse_rate, 3),
                            "current_validation_rate": round(current_validation_rate, 3),
                            "candidate_validation_rate": round(validation_rate, 3),
                        },
                    )
                )
        return recommendations

    def _collect_comparable_token_samples(
        self,
        stage: str,
        workflow_name: str,
        language: str | None,
        complexity: str | None,
        target_type: str | None,
        exclude_session_id: str,
    ) -> list[int]:
        calls = self._pm.list_llm_calls(project_path=self.project_path, limit=5000)
        current_canonical_model_key = self._current_canonical_model_key()
        per_session: dict[str, int] = {}
        for call in calls:
            if call.get("session_id") == exclude_session_id:
                continue
            if current_canonical_model_key:
                if self._call_canonical_model_key(call) != current_canonical_model_key:
                    continue
            if str(call.get("stage") or "") != stage:
                continue
            if str(call.get("workflow_name") or "") != workflow_name:
                continue
            try:
                metadata = json.loads(call.get("metadata_json") or "{}")
            except json.JSONDecodeError:
                metadata = {}
            if (metadata.get("language") or "unknown") != (language or "unknown"):
                continue
            if (metadata.get("complexity") or "unknown") != (complexity or "unknown"):
                continue
            if (metadata.get("target_type") or "unknown") != (target_type or "unknown"):
                continue
            session_id = str(call.get("session_id") or "")
            if not session_id:
                continue
            per_session[session_id] = (
                per_session.get(session_id, 0)
                + int(call.get("input_tokens", 0) or 0)
                + int(call.get("output_tokens", 0) or 0)
            )
        return list(per_session.values())
