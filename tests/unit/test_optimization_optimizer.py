from __future__ import annotations

from pathlib import Path

from tools.muscle.optimization.optimizer import WorkflowOptimizer
from tools.muscle.project_memory import ProjectMemory


def test_get_applied_settings_are_project_local(tmp_path: Path) -> None:
    project_one = tmp_path / "project-one"
    project_two = tmp_path / "project-two"
    project_one.mkdir()
    project_two.mkdir()

    pm_one = ProjectMemory(str(project_one))
    pm_two = ProjectMemory(str(project_two))
    pm_one.set_automation_state(
        str(project_one),
        "optimize.default_workflow",
        "review-comprehensive",
    )
    pm_two.set_automation_state(
        str(project_two),
        "optimize.default_workflow",
        "review-smart",
    )

    first_optimizer = WorkflowOptimizer(pm_one, str(project_one))
    second_optimizer = WorkflowOptimizer(pm_two, str(project_two))

    assert first_optimizer.get_applied_settings()["optimize.default_workflow"] == (
        "review-comprehensive"
    )
    assert second_optimizer.get_applied_settings()["optimize.default_workflow"] == "review-smart"


def test_build_recommendations_prefers_lower_token_workflow_without_quality_loss(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "optimizer-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    optimizer = WorkflowOptimizer(pm, str(project_path))

    pm.set_automation_state(str(project_path), "optimize.default_workflow", "review-smart")
    for _ in range(16):
        pm.upsert_workflow_rollup(
            project_path=str(project_path),
            workflow_name="review-smart",
            stage="review_total",
            language="python",
            complexity="medium",
            target_type="directory",
            success_count=1,
            total_tokens=1200,
            total_duration_ms=1000,
            valid_findings=2,
            verified_fixes=1,
            one_shot_verified_fixes=1,
            high_critical_findings=1,
            validation_successes=1,
            last_session_id="smart",
        )
        pm.upsert_workflow_rollup(
            project_path=str(project_path),
            workflow_name="review-comprehensive",
            stage="review_total",
            language="python",
            complexity="medium",
            target_type="directory",
            success_count=1,
            total_tokens=900,
            total_duration_ms=1000,
            valid_findings=2,
            verified_fixes=1,
            one_shot_verified_fixes=1,
            high_critical_findings=1,
            validation_successes=1,
            last_session_id="comprehensive",
        )

    recommendations = optimizer.build_recommendations()

    assert any(
        recommendation.decision_type == "workflow"
        and recommendation.recommended_value == "review-comprehensive"
        for recommendation in recommendations
    )


def test_estimate_savings_uses_comparable_historical_median(tmp_path: Path) -> None:
    project_path = tmp_path / "savings-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    optimizer = WorkflowOptimizer(pm, str(project_path))

    baseline_tokens = [1000, 1100, 900, 950]
    for index, tokens in enumerate(baseline_tokens, start=1):
        pm.insert_llm_call(
            project_path=str(project_path),
            call_id=f"call-{index}",
            session_id=f"session-{index}",
            stage="review_total",
            workflow_name="review-smart",
            review_mode="review",
            model="MiniMax-M2.7",
            input_tokens=tokens,
            output_tokens=0,
            duration_ms=100,
            success=True,
            context_chars=1000,
            context_strategy="issue_windows",
            metadata_json=('{"language":"python","complexity":"medium","target_type":"directory"}'),
        )

    estimate = optimizer.estimate_savings(
        session_id="current-session",
        stage="review_total",
        workflow_name="review-smart",
        language="python",
        complexity="medium",
        target_type="directory",
        actual_tokens=800,
    )

    assert estimate.baseline_tokens == 975
    assert estimate.delta_tokens == 175
    assert estimate.estimation_type == "estimated"


def test_estimate_savings_filters_to_current_canonical_model_key(tmp_path: Path) -> None:
    project_path = tmp_path / "model-scoped-savings-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    optimizer = WorkflowOptimizer(pm, str(project_path))

    pm.insert_model_identity_history(
        str(project_path),
        {
            "requested_label": "gpt-5",
            "provider_endpoint": "https://api.openai.com/v1",
            "provider_fingerprint": "api.openai.com/v1",
            "canonical_model_key": "openai/gpt-5@1",
            "identity_source": "manual_override",
            "confidence": 1.0,
            "manual_override": True,
        },
    )

    for index, tokens in enumerate([1000, 1100, 900], start=1):
        pm.insert_llm_call(
            project_path=str(project_path),
            call_id=f"openai-call-{index}",
            session_id=f"openai-session-{index}",
            stage="review_total",
            workflow_name="review-smart",
            review_mode="review",
            model="gpt-5",
            input_tokens=tokens,
            output_tokens=0,
            duration_ms=100,
            success=True,
            context_chars=1000,
            context_strategy="issue_windows",
            canonical_model_key="openai/gpt-5@1",
            identity_source="manual_override",
            metadata_json=('{"language":"python","complexity":"medium","target_type":"directory"}'),
        )

    for index, tokens in enumerate([300, 350, 400], start=1):
        pm.insert_llm_call(
            project_path=str(project_path),
            call_id=f"foreign-call-{index}",
            session_id=f"foreign-session-{index}",
            stage="review_total",
            workflow_name="review-smart",
            review_mode="review",
            model="MiniMax-M2.7",
            input_tokens=tokens,
            output_tokens=0,
            duration_ms=100,
            success=True,
            context_chars=1000,
            context_strategy="issue_windows",
            canonical_model_key="minimax/m2.7@1",
            identity_source="provider_endpoint",
            metadata_json=('{"language":"python","complexity":"medium","target_type":"directory"}'),
        )

    estimate = optimizer.estimate_savings(
        session_id="current-session",
        stage="review_total",
        workflow_name="review-smart",
        language="python",
        complexity="medium",
        target_type="directory",
        actual_tokens=800,
    )

    assert estimate.baseline_tokens == 1000
    assert estimate.delta_tokens == 200


def test_context_recommendations_ignore_foreign_model_buckets(tmp_path: Path) -> None:
    project_path = tmp_path / "context-recommendation-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    optimizer = WorkflowOptimizer(pm, str(project_path))

    pm.insert_model_identity_history(
        str(project_path),
        {
            "requested_label": "gpt-5",
            "provider_endpoint": "https://api.openai.com/v1",
            "provider_fingerprint": "api.openai.com/v1",
            "canonical_model_key": "openai/gpt-5@1",
            "identity_source": "manual_override",
            "confidence": 1.0,
            "manual_override": True,
        },
    )
    pm.set_automation_state(str(project_path), "optimize.context.semantic_review", "default")

    for index in range(12):
        pm.insert_llm_call(
            project_path=str(project_path),
            call_id=f"default-openai-{index}",
            session_id=f"default-openai-session-{index}",
            stage="semantic_review",
            workflow_name="review-smart",
            review_mode="review",
            model="gpt-5",
            input_tokens=1000,
            output_tokens=0,
            duration_ms=100,
            success=True,
            parse_success=True,
            validation_success=True,
            context_chars=1000,
            context_strategy="default",
            canonical_model_key="openai/gpt-5@1",
        )
        pm.insert_llm_call(
            project_path=str(project_path),
            call_id=f"optimized-openai-{index}",
            session_id=f"optimized-openai-session-{index}",
            stage="semantic_review",
            workflow_name="review-smart",
            review_mode="review",
            model="gpt-5",
            input_tokens=700,
            output_tokens=0,
            duration_ms=100,
            success=True,
            parse_success=True,
            validation_success=True,
            context_chars=800,
            context_strategy="issue_windows",
            canonical_model_key="openai/gpt-5@1",
        )
        pm.insert_llm_call(
            project_path=str(project_path),
            call_id=f"foreign-{index}",
            session_id=f"foreign-session-{index}",
            stage="semantic_review",
            workflow_name="review-smart",
            review_mode="review",
            model="MiniMax-M2.7",
            input_tokens=200,
            output_tokens=0,
            duration_ms=100,
            success=True,
            parse_success=True,
            validation_success=True,
            context_chars=400,
            context_strategy="summary_only",
            canonical_model_key="minimax/m2.7@1",
        )

    recommendations = optimizer.build_recommendations()

    assert any(
        recommendation.decision_type == "context"
        and recommendation.decision_scope == "semantic_review"
        and recommendation.recommended_value == "issue_windows"
        for recommendation in recommendations
    )
    assert not any(
        recommendation.decision_type == "context"
        and recommendation.decision_scope == "semantic_review"
        and recommendation.recommended_value == "summary_only"
        for recommendation in recommendations
    )
