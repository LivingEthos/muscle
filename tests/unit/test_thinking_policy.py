"""Unit tests for the per-stage MiniMax-M3 thinking policy."""

from __future__ import annotations

import pytest

from tools.muscle.code_review.thinking_policy import (
    DEFAULT_THINKING_MODE,
    THINKING_POLICY,
    thinking_for,
)
from tools.muscle.m27_client import VALID_THINKING_MODES


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


def test_unknown_stage_falls_back_to_default() -> None:
    assert thinking_for("does_not_exist") == DEFAULT_THINKING_MODE


def test_all_policy_modes_are_valid() -> None:
    for mode in THINKING_POLICY.values():
        assert mode in VALID_THINKING_MODES
    assert DEFAULT_THINKING_MODE in VALID_THINKING_MODES


def test_env_override_forces_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSCLE_THINKING_MODE", "disabled")
    assert thinking_for("semantic_review") == "disabled"
    assert thinking_for("memory_consolidation") == "disabled"


def test_invalid_env_override_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSCLE_THINKING_MODE", "not-a-mode")
    assert thinking_for("semantic_review") == "adaptive"
