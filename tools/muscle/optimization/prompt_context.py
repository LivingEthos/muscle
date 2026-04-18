"""
Shared prompt-context composition for lesson overlays and telemetry.

Architecture Decision Record (ADR):
- Keep prompt overlay assembly inside the optimization layer
- Use stage-specific lesson budgets so tiered lessons stay bounded
- Reuse one telemetry path for lesson-aware and project-only prompts
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..lesson_resolver import LessonRenderBudget
from .prompt_compactor import compact_prompt_text, should_compact_stage
from .types import PromptEnvelope, TelemetryContext

DEFAULT_STAGE_RENDER_BUDGETS: dict[str, LessonRenderBudget] = {
    "generate": LessonRenderBudget(
        name="generate_overlay",
        max_total_tokens=220,
        source_token_limits={"local": 120, "related": 45, "model-pack": 35, "global": 20},
    ),
    "evolve": LessonRenderBudget(
        name="evolve_overlay",
        max_total_tokens=210,
        source_token_limits={"local": 115, "related": 40, "model-pack": 35, "global": 20},
    ),
    "semantic_review": LessonRenderBudget(
        name="review_overlay",
        max_total_tokens=240,
        source_token_limits={"local": 125, "related": 50, "model-pack": 40, "global": 25},
    ),
    "fix_generation": LessonRenderBudget(
        name="fix_overlay",
        max_total_tokens=180,
        source_token_limits={"local": 95, "related": 40, "model-pack": 25, "global": 20},
    ),
    "handoff": LessonRenderBudget(
        name="handoff_overlay",
        max_total_tokens=160,
        source_token_limits={"local": 85, "related": 35, "model-pack": 25, "global": 15},
    ),
    "pressure_review": LessonRenderBudget(
        name="pressure_overlay",
        max_total_tokens=230,
        source_token_limits={"local": 120, "related": 45, "model-pack": 40, "global": 25},
    ),
}


def _stage_budget(stage: str) -> LessonRenderBudget:
    if stage in DEFAULT_STAGE_RENDER_BUDGETS:
        return DEFAULT_STAGE_RENDER_BUDGETS[stage]
    if "review" in stage:
        return DEFAULT_STAGE_RENDER_BUDGETS["semantic_review"]
    return LessonRenderBudget()


def compose_prompt_envelope(
    *,
    base_prompt: str,
    lesson_resolver: object | None,
    query_text: str,
    stage: str,
    base_context_strategy: str,
    session_id: str | None = None,
    language: str | None = None,
    render_budget: LessonRenderBudget | None = None,
    enable_prompt_compaction: bool | None = None,
) -> PromptEnvelope:
    """Return a lesson-aware prompt envelope for one model call."""
    prompt = base_prompt
    context_strategy = base_context_strategy
    metadata: dict[str, Any] = {
        "lesson_overlay_applied": False,
        "prompt_compaction_applied": False,
        "prompt_compaction_original_chars": len(base_prompt),
        "prompt_compaction_compacted_chars": len(base_prompt),
        "prompt_compaction_ratio": 1.0,
        "prompt_compaction_estimated_tokens_saved": 0,
    }
    call_id = uuid4().hex if session_id else None

    resolve_for_prompt = getattr(lesson_resolver, "resolve_for_prompt", None)
    if callable(resolve_for_prompt):
        resolved = resolve_for_prompt(
            query_text=query_text,
            stage=stage,
            session_id=session_id,
            call_id=call_id,
            language=language,
            render_budget=render_budget or _stage_budget(stage),
        )
        metadata.update(resolved.metadata())
        metadata["lesson_overlay_applied"] = bool(resolved.rendered_context)
        metadata["lesson_context_strategy"] = "budgeted_layered_overlay"
        if resolved.rendered_context:
            prompt = f"{resolved.rendered_context}\n\n{base_prompt}"
            context_strategy = f"{base_context_strategy}+lesson_overlay"

    compaction_enabled = (
        should_compact_stage(stage)
        if enable_prompt_compaction is None
        else enable_prompt_compaction
    )
    if compaction_enabled:
        prompt, compaction_metrics = compact_prompt_text(prompt)
        metadata.update(compaction_metrics.to_metadata())
        if compaction_metrics.applied:
            context_strategy = f"{context_strategy}+prompt_compaction"
    else:
        metadata["prompt_compaction_original_chars"] = len(prompt)
        metadata["prompt_compaction_compacted_chars"] = len(prompt)

    return PromptEnvelope(
        prompt=prompt,
        context_chars=len(prompt),
        context_strategy=context_strategy,
        metadata=metadata,
        call_id=call_id,
    )


def build_telemetry_context(
    *,
    project_path: str,
    session_id: str | None,
    stage: str,
    prompt_envelope: PromptEnvelope,
    metadata: dict[str, Any] | None = None,
    workflow_name: str | None = None,
    review_mode: str | None = None,
    language: str | None = None,
    complexity: str | None = None,
    target_type: str | None = None,
    task_category: str | None = None,
) -> TelemetryContext | None:
    """Build a telemetry context that reuses the shared prompt envelope."""
    if not session_id:
        return None

    combined_metadata = dict(prompt_envelope.metadata)
    if metadata:
        combined_metadata.update(metadata)

    return TelemetryContext(
        project_path=project_path,
        session_id=session_id,
        stage=stage,
        workflow_name=workflow_name,
        review_mode=review_mode,
        language=language,
        complexity=complexity,
        target_type=target_type,
        task_category=task_category,
        context_chars=prompt_envelope.context_chars,
        context_strategy=prompt_envelope.context_strategy,
        metadata=combined_metadata,
        call_id=prompt_envelope.call_id or uuid4().hex,
    )
