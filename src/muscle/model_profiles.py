"""Per-model optimization profiles.

Keyed on ``canonical_model_key`` (see ``model_identity``). Each profile groups
the behavior knobs MUSCLE's review pipeline consults so that optimizations match
the model occupying a position — host planner or agent executor.

The ``default`` profile reproduces today's behavior; populated profiles override
specific knobs. Unknown models resolve to ``default`` with a RuntimeWarning
(never silent — see ``profile_for``).

This module is *declarative + resolution only*. It does not itself change request
shapes, prompts, or docs; consumers (later plans) read these knobs at their seams.
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from .host_effort_policy import HostEffortLevel
from .project_memory_types import ModelIdentity

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_KEY = "default"

VALID_POSITIONS = frozenset({"host", "agent"})
VALID_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
VALID_INJECTION_SENSITIVITY = frozenset({"standard", "elevated"})
VALID_DEPENDENCY_POLICY = frozenset({"metadata_only", "sanitize"})
VALID_ENVELOPE_EMPHASIS = frozenset({"standard", "elevated"})
VALID_REASONING_DISPLAY = frozenset({None, "summarized"})


@dataclass(frozen=True)
class AgentBehavior:
    """How the agent (executor) client should shape requests for this model."""

    keep_thinking_on_all_stages: bool = False
    stage_effort: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    default_effort: str = "medium"
    reasoning_display: str | None = None


@dataclass(frozen=True)
class HostBehavior:
    """How MUSCLE should tailor host-facing output for this planner model."""

    doc_fragment_keys: tuple[str, ...] = ()
    synthesis_effort_floor: HostEffortLevel = HostEffortLevel.MEDIUM


@dataclass(frozen=True)
class SecurityPosture:
    """Injection/untrusted-content posture for this model."""

    prompt_injection_sensitivity: str = "standard"
    dependency_snippet_policy: str = "sanitize"
    untrusted_envelope_emphasis: str = "standard"
    cyber_safeguard_friction: bool = False


@dataclass(frozen=True)
class EvalPosture:
    """Benchmark/eval posture for this model."""

    grader_aware: bool = False


@dataclass(frozen=True)
class LearningPosture:
    """How learned rules are reinforced for this model."""

    point_of_action_reinforcement: bool = False
    repeated_violation_escalation: bool = False


@dataclass(frozen=True)
class ModelProfile:
    """The optimization profile for one canonical model."""

    canonical_key: str
    display_name: str
    positions: frozenset[str]
    agent: AgentBehavior = field(default_factory=AgentBehavior)
    host: HostBehavior = field(default_factory=HostBehavior)
    security: SecurityPosture = field(default_factory=SecurityPosture)
    evaluation: EvalPosture = field(default_factory=EvalPosture)
    learning: LearningPosture = field(default_factory=LearningPosture)


def validate_profile(profile: ModelProfile) -> None:
    """Assert every enum-like field holds an allowed value. Fail fast on drift."""
    assert len(profile.positions) >= 1, f"{profile.canonical_key}: positions must be non-empty"
    assert profile.positions <= VALID_POSITIONS, (
        f"{profile.canonical_key}: invalid positions {profile.positions - VALID_POSITIONS}"
    )
    assert profile.agent.default_effort in VALID_EFFORTS, (
        f"{profile.canonical_key}: bad default_effort {profile.agent.default_effort!r}"
    )
    for stage, effort in profile.agent.stage_effort.items():
        assert effort in VALID_EFFORTS, (
            f"{profile.canonical_key}: stage {stage!r} has bad effort {effort!r}"
        )
    assert profile.agent.reasoning_display in VALID_REASONING_DISPLAY, (
        f"{profile.canonical_key}: bad reasoning_display {profile.agent.reasoning_display!r}"
    )
    assert profile.security.prompt_injection_sensitivity in VALID_INJECTION_SENSITIVITY
    assert profile.security.dependency_snippet_policy in VALID_DEPENDENCY_POLICY
    assert profile.security.untrusted_envelope_emphasis in VALID_ENVELOPE_EMPHASIS


OPUS_4_8_KEY = "anthropic/claude-opus-4-8@2026-05-28"
MINIMAX_M3_KEY = "minimax/m3@1"
FABLE_5_KEY = "anthropic/claude-fable-5@2026-06-09"

# Opus 4.8 per-stage effort. Coding-agentic stages get xhigh; verification/
# pattern stay high; formatting/summarization stages drop to low (the card's
# "subagents or simple tasks" setting) — never the off-shape.
_OPUS_STAGE_EFFORT: Mapping[str, str] = MappingProxyType(
    {
        "semantic_review": "xhigh",
        "committee_review": "xhigh",
        "fix_generation": "xhigh",
        "verification": "high",
        "pattern_detection": "high",
        "memory_consolidation": "low",
        "handoff_generation": "low",
        "skill_generation": "low",
        "agent_generation": "low",
        "strategy_evolution": "low",
    }
)

_REGISTERED: dict[str, ModelProfile] = {}


def _register(profile: ModelProfile) -> None:
    validate_profile(profile)
    _REGISTERED[profile.canonical_key] = profile


# default — reproduces today's behavior for any unknown/other model.
_register(
    ModelProfile(
        canonical_key=DEFAULT_PROFILE_KEY,
        display_name="Default (conservative)",
        positions=frozenset({"host", "agent"}),
    )
)

# MiniMax M3 — encodes current MiniMax behavior so the default agent path is a
# guaranteed no-op (disabled thinking truly off / byte-identical-legacy).
_register(
    ModelProfile(
        canonical_key=MINIMAX_M3_KEY,
        display_name="MiniMax M3",
        positions=frozenset({"agent"}),
    )
)

# Opus 4.8 — fully populated from the system-card analysis (P1–P3).
_register(
    ModelProfile(
        canonical_key=OPUS_4_8_KEY,
        display_name="Claude Opus 4.8",
        positions=frozenset({"host", "agent"}),
        agent=AgentBehavior(
            keep_thinking_on_all_stages=True,
            stage_effort=_OPUS_STAGE_EFFORT,
            default_effort="high",
            reasoning_display=None,
        ),
        host=HostBehavior(
            doc_fragment_keys=(
                "untrusted_content_and_thinking",
                "delegation_triggers",
                "report_everything_then_filter",
                "autonomy_small_decisions",
                "literalism_narration",
            ),
            synthesis_effort_floor=HostEffortLevel.HIGH,
        ),
        security=SecurityPosture(
            prompt_injection_sensitivity="elevated",
            dependency_snippet_policy="metadata_only",
            untrusted_envelope_emphasis="elevated",
            cyber_safeguard_friction=True,
        ),
        evaluation=EvalPosture(grader_aware=True),
        learning=LearningPosture(
            point_of_action_reinforcement=True,
            repeated_violation_escalation=True,
        ),
    )
)

# Fable 5 — premium host. Deliberately omits Opus-card-specific fragments (no
# Fable system card exists to justify them). Placeholder: enrich when there is
# Fable-specific guidance.
_register(
    ModelProfile(
        canonical_key=FABLE_5_KEY,
        display_name="Claude Fable 5",
        positions=frozenset({"host"}),
        host=HostBehavior(
            doc_fragment_keys=(),
            synthesis_effort_floor=HostEffortLevel.HIGH,
        ),
        security=SecurityPosture(prompt_injection_sensitivity="elevated"),
    )
)

PROFILES: Mapping[str, ModelProfile] = MappingProxyType(_REGISTERED)


def profile_for(canonical_key: str | None) -> ModelProfile:
    """Return the profile for a canonical key, or the ``default`` profile.

    A ``None`` key (e.g. an unresolved host) is the expected path and resolves
    to ``default`` quietly. A *non-empty* key with no registered profile is a
    real gap — warn (RuntimeWarning) and log, never silently swallow it.
    """
    if canonical_key is None:
        logger.debug("profile_for: no canonical key; using default profile")
        return PROFILES[DEFAULT_PROFILE_KEY]
    profile = PROFILES.get(canonical_key)
    if profile is not None:
        return profile
    warnings.warn(
        f"No model profile registered for {canonical_key!r}; using "
        f"'{DEFAULT_PROFILE_KEY}'. Optimizations for this model will not apply.",
        RuntimeWarning,
        stacklevel=2,
    )
    logger.info("profile_for: unresolved canonical_key=%r -> default", canonical_key)
    return PROFILES[DEFAULT_PROFILE_KEY]


@dataclass(frozen=True)
class ActiveProfiles:
    """The profiles for the two positions, plus their resolved identities."""

    host: ModelProfile
    agent: ModelProfile
    host_identity: ModelIdentity
    agent_identity: ModelIdentity


def _agent_identity(project_path: Path | None) -> ModelIdentity:
    """Resolve the agent (executor) identity from the active provider."""
    # Lazy imports to avoid import cycles: providers → m27_client → …
    from .model_identity import canonical_for_label  # noqa: PLC0415
    from .providers import resolve_provider  # noqa: PLC0415

    try:
        profile, source = resolve_provider(project_path)
    except Exception:
        logger.debug("_agent_identity: provider resolution failed", exc_info=True)
        return ModelIdentity(
            requested_label=None,
            provider_endpoint=None,
            provider_fingerprint=None,
            canonical_model_key=None,
            identity_source="agent_unresolved",
            confidence=0.0,
            metadata={"position": "agent"},
        )
    canonical = canonical_for_label(profile.model)
    return ModelIdentity(
        requested_label=profile.model,
        provider_endpoint=None,
        provider_fingerprint=None,
        canonical_model_key=canonical,
        identity_source=f"agent_provider:{source}",
        confidence=0.9 if canonical else 0.3,
        metadata={"position": "agent", "provider": profile.name},
    )


def resolve_active_profiles(project_path: Path | None = None) -> ActiveProfiles:
    """Resolve host + agent profiles for the current context.

    Single entry point for consumers. Unknown/low-confidence positions resolve to
    the conservative ``default`` profile (loudly via ``profile_for``), so this is
    safe to call from any seam without changing behavior until a profile is both
    populated and consumed.
    """
    # Lazy import to avoid import cycle with host_model_resolver → model_identity → …
    from .host_model_resolver import HostModelResolver  # noqa: PLC0415

    host_identity = HostModelResolver().resolve(project_path)
    agent_identity = _agent_identity(project_path)
    return ActiveProfiles(
        host=profile_for(host_identity.canonical_model_key),
        agent=profile_for(agent_identity.canonical_model_key),
        host_identity=host_identity,
        agent_identity=agent_identity,
    )
