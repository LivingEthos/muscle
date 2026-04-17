"""
Unit tests for the shared optimization-layer prompt context helpers.
"""

from __future__ import annotations

from tools.muscle.lesson_resolver import LessonRenderBudget, ResolvedLesson, ResolvedLessonSet
from tools.muscle.optimization.prompt_context import (
    build_telemetry_context,
    compose_prompt_envelope,
)


class _StubLessonResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def resolve_for_prompt(self, **kwargs: object) -> ResolvedLessonSet:
        self.calls.append(dict(kwargs))
        return ResolvedLessonSet(
            lessons=[
                ResolvedLesson(
                    lesson_key="local-1",
                    lesson_text="Validate inputs before writing files.",
                    source="local",
                )
            ],
            rendered_context="Project-local lessons (authoritative):\n- Validate inputs before writing files.",
            render_budget_name="review_overlay",
            source_render_counts={"local": 1},
        )


def test_compose_prompt_envelope_applies_shared_lesson_overlay() -> None:
    resolver = _StubLessonResolver()
    budget = LessonRenderBudget(
        name="test-overlay",
        max_total_tokens=90,
        source_token_limits={"local": 60, "related": 15, "model-pack": 10, "global": 5},
    )

    envelope = compose_prompt_envelope(
        base_prompt="Review this file.",
        lesson_resolver=resolver,
        query_text="write files safely",
        stage="semantic_review",
        base_context_strategy="issue_windows",
        session_id="sess-1",
        language="python",
        render_budget=budget,
    )

    assert envelope.prompt.startswith("Project-local lessons")
    assert envelope.context_strategy == "issue_windows+lesson_overlay"
    assert envelope.metadata["lesson_overlay_applied"] is True
    assert envelope.metadata["lesson_render_budget"] == "review_overlay"
    assert envelope.call_id is not None
    assert resolver.calls[0]["render_budget"] == budget
    assert resolver.calls[0]["call_id"] == envelope.call_id


def test_build_telemetry_context_reuses_prompt_envelope_metadata() -> None:
    envelope = compose_prompt_envelope(
        base_prompt="Generate code.",
        lesson_resolver=None,
        query_text="generate code",
        stage="generate",
        base_context_strategy="default_generation_prompt",
        session_id="sess-2",
    )

    telemetry = build_telemetry_context(
        project_path="/tmp/project",
        session_id="sess-2",
        stage="generate",
        prompt_envelope=envelope,
        metadata={"task": "generate"},
        workflow_name="default",
        language="python",
    )

    assert telemetry is not None
    assert telemetry.context_strategy == "default_generation_prompt"
    assert telemetry.call_id == envelope.call_id
    assert telemetry.metadata["lesson_overlay_applied"] is False
    assert telemetry.metadata["task"] == "generate"
