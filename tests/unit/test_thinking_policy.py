"""Unit tests for the per-stage MiniMax-M3 thinking policy."""

from __future__ import annotations

import pytest

from muscle.code_review import thinking_policy
from muscle.code_review.thinking_policy import (
    THINKING_POLICY,
    UNKNOWN_STAGE_THINKING_MODE,
    thinking_for,
)
from muscle.m27_client import VALID_THINKING_MODES


@pytest.fixture(autouse=True)
def _reset_override_warning() -> None:
    """Reset the process-wide one-shot override-warning flag between tests."""
    thinking_policy._override_warned = False


def test_analysis_stages_use_adaptive() -> None:
    assert thinking_for("semantic_review") == "adaptive"
    assert thinking_for("committee_review") == "adaptive"
    assert thinking_for("verification") == "adaptive"
    assert thinking_for("fix_generation") == "adaptive"
    assert thinking_for("pattern_detection") == "adaptive"


def test_formatting_stages_disable_thinking() -> None:
    assert thinking_for("memory_consolidation") == "disabled"
    assert thinking_for("handoff_generation") == "disabled"
    assert thinking_for("skill_generation") == "disabled"
    assert thinking_for("agent_generation") == "disabled"
    assert thinking_for("strategy_evolution") == "disabled"


def test_unknown_stage_warns_and_falls_back_to_cheapest() -> None:
    with pytest.warns(RuntimeWarning):
        result = thinking_for("does_not_exist")
    # Fail safe: cheapest mode, never the most expensive ("adaptive").
    assert result == UNKNOWN_STAGE_THINKING_MODE
    assert result == "disabled"


def test_all_policy_modes_are_valid() -> None:
    for mode in THINKING_POLICY.values():
        assert mode in VALID_THINKING_MODES
    assert UNKNOWN_STAGE_THINKING_MODE in VALID_THINKING_MODES


def test_policy_is_read_only() -> None:
    with pytest.raises(TypeError):
        THINKING_POLICY["semantic_review"] = "disabled"  # type: ignore[index]


def test_env_override_forces_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSCLE_THINKING_MODE", "disabled")
    with pytest.warns(RuntimeWarning):
        assert thinking_for("semantic_review") == "disabled"
    assert thinking_for("memory_consolidation") == "disabled"


def test_env_override_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSCLE_THINKING_MODE", "disabled")
    with pytest.warns(RuntimeWarning) as recorded:
        thinking_for("semantic_review")
        thinking_for("fix_generation")
    # One-shot: only a single override warning across multiple calls.
    override_warnings = [w for w in recorded if "MUSCLE_THINKING_MODE override" in str(w.message)]
    assert len(override_warnings) == 1


def test_invalid_env_override_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSCLE_THINKING_MODE", "not-a-mode")
    assert thinking_for("semantic_review") == "adaptive"
