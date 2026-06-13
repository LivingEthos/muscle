import warnings

import pytest

from muscle.host_effort_policy import HostEffortLevel
from muscle.model_profiles import (
    PROFILES,
    AgentBehavior,
    ModelProfile,
    SecurityPosture,
    profile_for,
    validate_profile,
)

OPUS_KEY = "anthropic/claude-opus-4-8@2026-05-28"
M3_KEY = "minimax/m3@1"
FABLE_KEY = "anthropic/claude-fable-5@2026-06-09"


def _minimal_profile(**overrides) -> ModelProfile:
    base: dict[str, object] = {
        "canonical_key": "test/model@1",
        "display_name": "Test",
        "positions": frozenset({"agent"}),
    }
    base.update(overrides)
    return ModelProfile(**base)  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs; values correct at runtime


def test_defaults_are_conservative():
    p = _minimal_profile()
    assert p.agent.keep_thinking_on_all_stages is False
    assert dict(p.agent.stage_effort) == {}
    assert p.agent.default_effort == "medium"
    assert p.security.dependency_snippet_policy == "sanitize"
    assert p.host.synthesis_effort_floor is HostEffortLevel.MEDIUM


def test_validate_profile_accepts_valid():
    validate_profile(_minimal_profile())  # no raise


def test_validate_profile_rejects_bad_effort():
    bad = _minimal_profile(agent=AgentBehavior(stage_effort={"semantic_review": "turbo"}))
    with pytest.raises(AssertionError):
        validate_profile(bad)


def test_validate_profile_rejects_bad_dependency_policy():
    bad = _minimal_profile(security=SecurityPosture(dependency_snippet_policy="raw"))
    with pytest.raises(AssertionError):
        validate_profile(bad)


def test_profile_is_frozen():
    from dataclasses import FrozenInstanceError

    p = _minimal_profile()
    with pytest.raises(FrozenInstanceError):
        p.canonical_key = "other"  # type: ignore[misc]


def test_registry_contains_expected_profiles():
    assert set(PROFILES) == {"default", OPUS_KEY, M3_KEY, FABLE_KEY}


def test_default_profile_preserves_today_agent_behavior():
    d = PROFILES["default"]
    assert d.agent.keep_thinking_on_all_stages is False
    assert dict(d.agent.stage_effort) == {}
    assert d.host.doc_fragment_keys == ()


def test_m3_profile_is_byte_identical_legacy_shaped():
    m3 = PROFILES[M3_KEY]
    assert m3.agent.keep_thinking_on_all_stages is False
    assert dict(m3.agent.stage_effort) == {}
    assert m3.positions == frozenset({"agent"})


def test_opus_profile_full_values():
    opus = PROFILES[OPUS_KEY]
    assert opus.agent.keep_thinking_on_all_stages is True
    assert opus.agent.stage_effort["semantic_review"] == "xhigh"
    assert opus.agent.stage_effort["fix_generation"] == "xhigh"
    assert opus.agent.stage_effort["verification"] == "high"
    assert opus.agent.stage_effort["memory_consolidation"] == "low"
    assert opus.agent.default_effort == "high"
    assert opus.host.synthesis_effort_floor is HostEffortLevel.HIGH
    assert "untrusted_content_and_thinking" in opus.host.doc_fragment_keys
    assert "literalism_narration" in opus.host.doc_fragment_keys
    assert opus.security.prompt_injection_sensitivity == "elevated"
    assert opus.security.dependency_snippet_policy == "metadata_only"
    assert opus.security.untrusted_envelope_emphasis == "elevated"
    assert opus.security.cyber_safeguard_friction is True
    assert opus.evaluation.grader_aware is True
    assert opus.learning.point_of_action_reinforcement is True
    assert opus.learning.repeated_violation_escalation is True
    assert {"host", "agent"} <= opus.positions


def test_fable_profile_is_premium_host_placeholder():
    fable = PROFILES[FABLE_KEY]
    assert fable.positions == frozenset({"host"})
    assert fable.host.synthesis_effort_floor is HostEffortLevel.HIGH
    assert fable.host.doc_fragment_keys == ()  # no Opus-card-specific fragments


def test_profile_for_known_key_returns_it():
    assert profile_for(OPUS_KEY) is PROFILES[OPUS_KEY]


def test_profile_for_none_returns_default_quietly():
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning fails the test
        assert profile_for(None) is PROFILES["default"]


def test_profile_for_unknown_key_warns_and_defaults():
    with pytest.warns(RuntimeWarning):
        result = profile_for("anthropic/some-unreleased-model@9")
    assert result is PROFILES["default"]


def test_opus_stage_effort_is_immutable():
    with pytest.raises(TypeError):
        PROFILES[OPUS_KEY].agent.stage_effort["new_stage"] = "xhigh"  # type: ignore[index]


def test_validate_profile_rejects_empty_positions():
    bad = _minimal_profile(positions=frozenset())
    with pytest.raises(AssertionError):
        validate_profile(bad)
