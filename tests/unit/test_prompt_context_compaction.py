"""
Unit tests for prompt-context compaction wiring.
"""

from __future__ import annotations

from tools.muscle.optimization.prompt_context import compose_prompt_envelope


def test_compose_prompt_envelope_applies_prompt_compaction_for_safe_stage() -> None:
    envelope = compose_prompt_envelope(
        base_prompt=(
            "Your task is to:\n"
            "Please investigate this thoroughly and provide your findings and proposed solutions."
        ),
        lesson_resolver=None,
        query_text="handoff summary",
        stage="handoff",
        base_context_strategy="handoff_prompt",
        session_id="sess-3",
    )

    assert envelope.prompt == "Task:\nInvestigate thoroughly and propose validated fixes."
    assert envelope.context_strategy == "handoff_prompt+prompt_compaction"
    assert envelope.metadata["prompt_compaction_applied"] is True
    assert (
        envelope.metadata["prompt_compaction_compacted_chars"]
        < envelope.metadata["prompt_compaction_original_chars"]
    )
