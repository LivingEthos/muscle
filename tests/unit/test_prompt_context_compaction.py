"""
Unit tests for prompt-context compaction wiring.
"""

from __future__ import annotations

from muscle.optimization.prompt_context import compose_prompt_envelope


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
    assert envelope.metadata["cache_prefix_chars"] == len(envelope.prompt)
    assert isinstance(envelope.metadata["cache_prefix_digest"], str)
    assert envelope.metadata["cache_prefix_lint_warning_count"] == 0
    assert envelope.metadata["estimated_cache_fresh_cost"] > 0
    assert (
        envelope.metadata["estimated_cache_read_cost"]
        < envelope.metadata["estimated_cache_fresh_cost"]
    )
