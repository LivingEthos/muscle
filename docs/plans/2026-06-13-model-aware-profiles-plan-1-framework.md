# Model-Aware Optimization Profiles — Plan 1: Framework & Detection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dark foundation — a typed per-model optimization-profile registry plus a host/agent model-detection layer — that later plans consume, with zero change to production behavior.

**Architecture:** A new `model_profiles.py` holds frozen `ModelProfile` dataclasses keyed on the existing `canonical_model_key`, with a validated registry and a `profile_for()` lookup that falls back to a behavior-preserving `default` profile (loudly, never silently). A new `host_model_resolver.py` resolves the host (planner) model from injectable signals — explicit override → imported-session evidence → `settings.json` → unresolved — mirroring the existing `ModelIdentityResolver` precedence/confidence contract. A `resolve_active_profiles()` facade ties host + agent profiles together. Nothing in the review pipeline consumes these yet (that's Plans 2+).

**Tech Stack:** Python 3.10+, frozen `dataclasses`, `types.MappingProxyType` for immutable registries, `pytest` + `unittest.mock`/`monkeypatch`, `uv run` for all gates.

**Spec:** [2026-06-13-model-aware-optimization-profiles-design.md](2026-06-13-model-aware-optimization-profiles-design.md) (this plan implements Phase 0 / §3.1–§3.3 framework + detection).

**Conventions (from CLAUDE.md):**
- Run gates via `uv run`: `uv run pytest tests/unit/<file> -v`, `uv run mypy src/muscle/`, `uv run ruff check src/muscle/`, `uv run ruff format src/muscle/`.
- mypy is strict (`disallow_untyped_defs`, `warn_return_any`) — every new function needs annotations.
- Tests live in `tests/unit/` with a `test_` prefix; `asyncio_mode = "auto"`.
- The full suite takes 1–3.5 min; run targeted files while iterating.

---

## File Structure

- **Create `src/muscle/model_profiles.py`** — `AgentBehavior`, `HostBehavior`, `SecurityPosture`, `EvalPosture`, `LearningPosture`, `ModelProfile` dataclasses; the validated `PROFILES` registry (4 profiles); `profile_for()`; `ActiveProfiles`; `resolve_active_profiles()`. One responsibility: declare and resolve optimization profiles.
- **Create `src/muscle/host_model_resolver.py`** — `HostModelResolver` + the three default signal functions + host-label canonicalization. One responsibility: detect the host (planner) model.
- **Modify `src/muscle/model_identity.py`** — add the `claude-opus-4-8` canonical key, aliases, introspection patterns, and a `canonical_for_label()` helper.
- **Create `tests/unit/test_model_profiles.py`**, **`tests/unit/test_host_model_resolver.py`**; extend **`tests/unit/test_model_identity.py`**.

No production seam (anthropic_client, host_memory_templates, review_benchmark, routing, …) is touched in this plan.

---

## Task 1: Add the Opus 4.8 canonical identity + `canonical_for_label` helper

**Files:**
- Modify: `src/muscle/model_identity.py` (`SUPPORTED_CANONICAL_MODELS`, `HEURISTIC_ALIAS_MAP`, `INTROSPECTION_MODEL_PATTERNS`; new helper)
- Test: `tests/unit/test_model_identity.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_model_identity.py`:

```python
from muscle.model_identity import canonical_for_label

OPUS_KEY = "anthropic/claude-opus-4-8@2026-05-28"


def test_canonical_for_label_resolves_opus_aliases():
    assert canonical_for_label("claude-opus-4-8") == OPUS_KEY
    assert canonical_for_label("Opus 4.8") == OPUS_KEY
    assert canonical_for_label("opus-4-8") == OPUS_KEY


def test_canonical_for_label_resolves_existing_models():
    assert canonical_for_label("MiniMax-M3") == "minimax/m3@1"
    assert canonical_for_label("claude-fable-5") == "anthropic/claude-fable-5@2026-06-09"


def test_canonical_for_label_unknown_returns_none():
    assert canonical_for_label("totally-unknown-model") is None
    assert canonical_for_label(None) is None


def test_opus_key_is_supported():
    from muscle.model_identity import SUPPORTED_CANONICAL_MODELS

    assert OPUS_KEY in SUPPORTED_CANONICAL_MODELS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_model_identity.py -k "canonical_for_label or opus_key" -v`
Expected: FAIL — `ImportError: cannot import name 'canonical_for_label'`.

- [ ] **Step 3: Implement**

In `src/muscle/model_identity.py`, add the Opus key to `SUPPORTED_CANONICAL_MODELS` (inside the set literal):

```python
        "anthropic/claude-opus-4-8@2026-05-28",
```

Add aliases to `HEURISTIC_ALIAS_MAP`:

```python
    "claude-opus-4-8": "anthropic/claude-opus-4-8@2026-05-28",
    "opus 4.8": "anthropic/claude-opus-4-8@2026-05-28",
    "opus-4-8": "anthropic/claude-opus-4-8@2026-05-28",
    "anthropic/claude-opus-4-8@2026-05-28": "anthropic/claude-opus-4-8@2026-05-28",
```

Add to the `"anthropic"` tuple in `INTROSPECTION_MODEL_PATTERNS` (before the fable entry):

```python
        ("claude-opus-4-8", "anthropic/claude-opus-4-8@2026-05-28"),
        ("opus-4-8", "anthropic/claude-opus-4-8@2026-05-28"),
```

Add the helper at module level (after `HEURISTIC_ALIAS_MAP`):

```python
def canonical_for_label(label: str | None) -> str | None:
    """Map a free-form model label to a canonical model key, or None.

    Pure alias lookup (no endpoint/provenance). Used to canonicalize a
    provider's configured model string or a host label into a registry key.
    """
    if not label:
        return None
    return HEURISTIC_ALIAS_MAP.get(label.strip().lower())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_model_identity.py -k "canonical_for_label or opus_key" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/model_identity.py tests/unit/test_model_identity.py
git commit -m "feat(model-identity): add claude-opus-4-8 canonical key + canonical_for_label helper"
```

---

## Task 2: `ModelProfile` dataclasses + import-time validation

**Files:**
- Create: `src/muscle/model_profiles.py`
- Test: `tests/unit/test_model_profiles.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_model_profiles.py`:

```python
import pytest

from muscle.host_effort_policy import HostEffortLevel
from muscle.model_profiles import (
    AgentBehavior,
    HostBehavior,
    ModelProfile,
    SecurityPosture,
    validate_profile,
)


def _minimal_profile(**overrides) -> ModelProfile:
    base = dict(
        canonical_key="test/model@1",
        display_name="Test",
        positions=frozenset({"agent"}),
    )
    base.update(overrides)
    return ModelProfile(**base)


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
    p = _minimal_profile()
    with pytest.raises(Exception):
        p.canonical_key = "other"  # type: ignore[misc]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_model_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'muscle.model_profiles'`.

- [ ] **Step 3: Implement the module skeleton (dataclasses + validation)**

Create `src/muscle/model_profiles.py`:

```python
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
from types import MappingProxyType

from .host_effort_policy import HostEffortLevel

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
    stage_effort: Mapping[str, str] = field(default_factory=dict)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_model_profiles.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/model_profiles.py tests/unit/test_model_profiles.py
git commit -m "feat(model-profiles): typed ModelProfile dataclasses + validation"
```

---

## Task 3: The four profiles + `profile_for()` lookup

**Files:**
- Modify: `src/muscle/model_profiles.py`
- Test: `tests/unit/test_model_profiles.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_model_profiles.py`:

```python
import warnings

from muscle.model_profiles import PROFILES, profile_for

OPUS_KEY = "anthropic/claude-opus-4-8@2026-05-28"
M3_KEY = "minimax/m3@1"
FABLE_KEY = "anthropic/claude-fable-5@2026-06-09"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_model_profiles.py -k "registry or profile_for or _profile" -v`
Expected: FAIL — `ImportError: cannot import name 'PROFILES'`.

- [ ] **Step 3: Implement the registry + lookup**

Append to `src/muscle/model_profiles.py`:

```python
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
        positions=VALID_POSITIONS,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_model_profiles.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/model_profiles.py tests/unit/test_model_profiles.py
git commit -m "feat(model-profiles): register default/M3/Opus-4.8/Fable-5 profiles + profile_for"
```

---

## Task 4: `HostModelResolver` with the explicit-override signal

**Files:**
- Create: `src/muscle/host_model_resolver.py`
- Test: `tests/unit/test_host_model_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_host_model_resolver.py`:

```python
import json

from muscle.host_model_resolver import (
    HostModelResolver,
    canonical_for_host_label,
    default_explicit_host_label,
)

OPUS_KEY = "anthropic/claude-opus-4-8@2026-05-28"
FABLE_KEY = "anthropic/claude-fable-5@2026-06-09"


def test_canonical_for_host_label_handles_bare_and_suffixed():
    assert canonical_for_host_label("opus") == OPUS_KEY
    assert canonical_for_host_label("fable") == FABLE_KEY
    assert canonical_for_host_label("opus[1m]") == OPUS_KEY
    assert canonical_for_host_label("claude-opus-4-8") == OPUS_KEY
    assert canonical_for_host_label("mystery") is None


def test_explicit_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    assert default_explicit_host_label(tmp_path) == "opus"


def test_explicit_config_override(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    (muscle_dir / "config.yaml").write_text(json.dumps({"host": {"model": "fable"}}))
    assert default_explicit_host_label(tmp_path) == "fable"


def test_resolver_explicit_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    resolver = HostModelResolver(session_fn=lambda _p: None, settings_fn=lambda _p: None)
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key == OPUS_KEY
    assert identity.identity_source == "host_explicit"
    assert identity.confidence == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'muscle.host_model_resolver'`.

- [ ] **Step 3: Implement the module + explicit signal + resolver core**

Create `src/muscle/host_model_resolver.py`:

```python
"""Resolve the host (planner) model that consumes MUSCLE's output.

Claude Code exposes no stable model signal to plugins/hooks, so detection draws
on MUSCLE-side signals, in descending authority:

1. explicit override   — MUSCLE_HOST_MODEL env, then .muscle/config.yaml host.model
2. session evidence     — most recent imported host-session model (Task 6)
3. host settings        — ~/.claude/settings.json then .claude/settings.json "model" (Task 5)
4. unresolved           — caller falls back to the conservative default profile

Mirrors ``ModelIdentityResolver``: every result is a ``ModelIdentity`` carrying a
confidence + source so resolution stays explainable.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from .model_identity import canonical_for_label
from .project_memory_types import ModelIdentity

logger = logging.getLogger(__name__)

# Host-context short aliases that settings.json / users commonly use, beyond the
# full labels handled by canonical_for_label.
_HOST_SHORT_ALIASES = {
    "opus": "anthropic/claude-opus-4-8@2026-05-28",
    "fable": "anthropic/claude-fable-5@2026-06-09",
    "sonnet": "anthropic/claude-sonnet@4",
}

LabelFn = Callable[[Path | None], str | None]


def canonical_for_host_label(label: str | None) -> str | None:
    """Canonicalize a host label, tolerating bare names and ``[1m]`` suffixes."""
    if not label:
        return None
    normalized = label.strip().lower()
    if normalized.endswith("[1m]"):
        normalized = normalized[: -len("[1m]")].strip()
    direct = canonical_for_label(normalized)
    if direct is not None:
        return direct
    return _HOST_SHORT_ALIASES.get(normalized)


def _config_host_model(project_path: Path | None) -> str | None:
    if project_path is None:
        return None
    config_path = Path(project_path) / ".muscle" / "config.yaml"
    if not config_path.exists():
        return None
    try:
        # .muscle/config.yaml holds JSON content (see ProjectManager).
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("host_model_resolver: could not read %s", config_path, exc_info=True)
        return None
    host = data.get("host") if isinstance(data, dict) else None
    value = host.get("model") if isinstance(host, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def default_explicit_host_label(project_path: Path | None) -> str | None:
    """MUSCLE_HOST_MODEL env, then .muscle/config.yaml host.model."""
    env = os.environ.get("MUSCLE_HOST_MODEL")
    if env and env.strip():
        return env.strip()
    return _config_host_model(project_path)


def default_session_host_label(project_path: Path | None) -> str | None:
    """Placeholder until Task 6 wires imported-session evidence."""
    return None


def default_settings_host_label(project_path: Path | None) -> str | None:
    """Placeholder until Task 5 wires settings.json."""
    return None


class HostModelResolver:
    """Resolve the host model from injectable signals (precedence above)."""

    def __init__(
        self,
        *,
        explicit_fn: LabelFn | None = None,
        session_fn: LabelFn | None = None,
        settings_fn: LabelFn | None = None,
    ) -> None:
        self._explicit_fn = explicit_fn or default_explicit_host_label
        self._session_fn = session_fn or default_session_host_label
        self._settings_fn = settings_fn or default_settings_host_label

    def resolve(self, project_path: Path | None = None) -> ModelIdentity:
        signals: list[tuple[LabelFn, str, float]] = [
            (self._explicit_fn, "host_explicit", 1.0),
            (self._session_fn, "host_session_evidence", 0.8),
            (self._settings_fn, "host_settings", 0.5),
        ]
        for fn, source, confidence in signals:
            label = fn(project_path)
            if not label:
                continue
            canonical = canonical_for_host_label(label)
            # A label we cannot canonicalize is weaker evidence than one we can.
            effective = confidence if canonical else confidence * 0.5
            return ModelIdentity(
                requested_label=label,
                provider_endpoint=None,
                provider_fingerprint=None,
                canonical_model_key=canonical,
                identity_source=source,
                confidence=effective,
                metadata={"position": "host"},
            )
        return ModelIdentity(
            requested_label=None,
            provider_endpoint=None,
            provider_fingerprint=None,
            canonical_model_key=None,
            identity_source="host_unresolved",
            confidence=0.0,
            metadata={"position": "host"},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/host_model_resolver.py tests/unit/test_host_model_resolver.py
git commit -m "feat(host-resolver): HostModelResolver + explicit-override signal"
```

---

## Task 5: Wire the `settings.json` signal

**Files:**
- Modify: `src/muscle/host_model_resolver.py` (`default_settings_host_label`)
- Test: `tests/unit/test_host_model_resolver.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_host_model_resolver.py`:

```python
from muscle.host_model_resolver import default_settings_host_label


def test_settings_project_then_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    (project / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    # Project-scoped settings win over home.
    (project / ".claude" / "settings.json").write_text(json.dumps({"model": "opus"}))
    (home / ".claude" / "settings.json").write_text(json.dumps({"model": "fable"}))
    assert default_settings_host_label(project) == "opus"


def test_settings_falls_back_to_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".claude" / "settings.json").write_text(json.dumps({"model": "fable"}))
    assert default_settings_host_label(project) == "fable"


def test_settings_absent_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    assert default_settings_host_label(tmp_path / "no-proj") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -k settings -v`
Expected: FAIL — both project/home tests fail (placeholder returns `None`).

- [ ] **Step 3: Implement**

Replace `default_settings_host_label` in `src/muscle/host_model_resolver.py`:

```python
def _read_settings_model(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("host_model_resolver: could not read %s", path, exc_info=True)
        return None
    value = data.get("model") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def default_settings_host_label(project_path: Path | None) -> str | None:
    """Project ``.claude/settings.json`` model, else ``~/.claude/settings.json``.

    This is the *configured* default and may lag a mid-session ``/model`` switch;
    it sits below explicit override and session evidence in precedence.
    """
    if project_path is not None:
        project_model = _read_settings_model(Path(project_path) / ".claude" / "settings.json")
        if project_model:
            return project_model
    return _read_settings_model(Path.home() / ".claude" / "settings.json")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -k settings -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/host_model_resolver.py tests/unit/test_host_model_resolver.py
git commit -m "feat(host-resolver): settings.json model signal (project then home)"
```

---

## Task 6: Wire the imported-session evidence signal

**Files:**
- Modify: `src/muscle/host_model_resolver.py` (`default_session_host_label`)
- Test: `tests/unit/test_host_model_resolver.py`

**Context:** `ProjectMemory(project_path).list_external_benchmark_turns(project_path, provider=..., limit=...)` returns turn dict rows (most recent last; rows are `ORDER BY ebt.id ASC`) that include `model` and `provider`. Host providers are `claude` and `codex` (the planners that consume MUSCLE). We take the most recent turn whose `model` is non-empty.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_host_model_resolver.py` (the `Path` import is needed here):

```python
from pathlib import Path

from muscle.host_model_resolver import default_session_host_label


class _FakeMemory:
    def __init__(self, rows):
        self._rows = rows

    def list_external_benchmark_turns(self, project_path, provider=None, limit=200):
        rows = self._rows
        if provider:
            rows = [r for r in rows if r.get("provider") == provider]
        return rows[:limit]


def test_session_evidence_takes_most_recent_model():
    # Rows are ASC by id; the most recent host turn is last.
    rows = [
        {"id": 1, "provider": "claude", "model": "claude-fable-5"},
        {"id": 2, "provider": "claude", "model": "claude-opus-4-8"},
    ]
    label = default_session_host_label(Path("/proj"), memory=_FakeMemory(rows))
    assert label == "claude-opus-4-8"


def test_session_evidence_ignores_non_host_providers():
    rows = [{"id": 3, "provider": "minimax", "model": "MiniMax-M3"}]
    assert default_session_host_label(Path("/proj"), memory=_FakeMemory(rows)) is None


def test_session_evidence_empty_returns_none():
    assert default_session_host_label(Path("/proj"), memory=_FakeMemory([])) is None


def test_session_evidence_none_project_returns_none():
    assert default_session_host_label(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -k session_evidence -v`
Expected: FAIL — `TypeError: default_session_host_label() got an unexpected keyword argument 'memory'`.

- [ ] **Step 3: Implement**

Replace `default_session_host_label` in `src/muscle/host_model_resolver.py`. Add `from typing import Any` to the imports.

```python
# Host planners that consume MUSCLE output (excludes the MiniMax executor).
_HOST_SESSION_PROVIDERS = ("claude", "codex")


def default_session_host_label(
    project_path: Path | None,
    *,
    memory: Any | None = None,
) -> str | None:
    """Most-recent host model from imported Claude/Codex sessions, or None.

    ``memory`` is injectable for testing; in production it is a ``ProjectMemory``
    bound to ``project_path``. Turn rows arrive id-ASC, so the most recent host
    turn with a non-empty model is the last match.
    """
    if project_path is None:
        return None
    if memory is None:
        try:
            from .project_memory import ProjectMemory

            memory = ProjectMemory(str(project_path))
        except Exception:
            logger.debug("host_model_resolver: ProjectMemory unavailable", exc_info=True)
            return None
    try:
        turns = memory.list_external_benchmark_turns(str(project_path), limit=200)
    except Exception:
        logger.debug("host_model_resolver: could not list session turns", exc_info=True)
        return None
    for row in reversed(list(turns)):
        if row.get("provider") not in _HOST_SESSION_PROVIDERS:
            continue
        model = row.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -k session_evidence -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/host_model_resolver.py tests/unit/test_host_model_resolver.py
git commit -m "feat(host-resolver): imported-session host-model evidence signal"
```

---

## Task 7: Full-precedence resolver test (integration of signals)

**Files:**
- Test: `tests/unit/test_host_model_resolver.py` (no production change — characterizes precedence)

- [ ] **Step 1: Write the test**

Append to `tests/unit/test_host_model_resolver.py`:

```python
def test_precedence_session_beats_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    resolver = HostModelResolver(
        explicit_fn=lambda _p: None,
        session_fn=lambda _p: "claude-opus-4-8",
        settings_fn=lambda _p: "fable",
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key == OPUS_KEY
    assert identity.identity_source == "host_session_evidence"
    assert identity.confidence == 0.8


def test_precedence_settings_used_when_higher_absent(tmp_path):
    resolver = HostModelResolver(
        explicit_fn=lambda _p: None,
        session_fn=lambda _p: None,
        settings_fn=lambda _p: "fable",
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key == FABLE_KEY
    assert identity.identity_source == "host_settings"


def test_unresolved_when_all_signals_silent(tmp_path):
    resolver = HostModelResolver(
        explicit_fn=lambda _p: None,
        session_fn=lambda _p: None,
        settings_fn=lambda _p: None,
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key is None
    assert identity.identity_source == "host_unresolved"
    assert identity.confidence == 0.0


def test_uncanonicalizable_label_halves_confidence(tmp_path):
    resolver = HostModelResolver(
        explicit_fn=lambda _p: "some-unknown-host",
        session_fn=lambda _p: None,
        settings_fn=lambda _p: None,
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key is None
    assert identity.requested_label == "some-unknown-host"
    assert identity.confidence == 0.5
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_host_model_resolver.py -k "precedence or unresolved or uncanonical" -v`
Expected: PASS (these characterize already-implemented behavior).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_host_model_resolver.py
git commit -m "test(host-resolver): full signal-precedence characterization"
```

---

## Task 8: `ActiveProfiles` + `resolve_active_profiles()` facade

**Files:**
- Modify: `src/muscle/model_profiles.py`
- Test: `tests/unit/test_model_profiles.py`

**Context:** The agent canonical key comes from the active provider: `resolve_provider(project_path)` (in `providers.py`) returns `(ProviderProfile, source)`; `ProviderProfile.model` is e.g. `"MiniMax-M3"` or `"claude-opus-4-8"`. Import `resolve_provider` lazily inside the function to avoid an import cycle (providers → m27_client → …).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_model_profiles.py`:

```python
from muscle.model_profiles import ActiveProfiles, resolve_active_profiles


def test_resolve_active_profiles_opus_host_minimax_agent(monkeypatch, tmp_path):
    # Host = Opus via explicit env; agent = default MiniMax provider.
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
    active = resolve_active_profiles(tmp_path)
    assert isinstance(active, ActiveProfiles)
    assert active.host.canonical_key == OPUS_KEY
    assert active.agent.canonical_key == M3_KEY
    assert active.host_identity.identity_source == "host_explicit"


def test_resolve_active_profiles_unknown_host_is_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
    active = resolve_active_profiles(tmp_path)
    assert active.host.canonical_key == "default"


def test_resolve_active_profiles_opus_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_PROVIDER", "anthropic-api")
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    active = resolve_active_profiles(tmp_path)
    assert active.agent.canonical_key == OPUS_KEY
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_model_profiles.py -k resolve_active -v`
Expected: FAIL — `ImportError: cannot import name 'ActiveProfiles'`.

- [ ] **Step 3: Implement the facade**

Append to `src/muscle/model_profiles.py` (add `from .project_memory_types import ModelIdentity` and `from pathlib import Path` to the imports):

```python
@dataclass(frozen=True)
class ActiveProfiles:
    """The profiles for the two positions, plus their resolved identities."""

    host: ModelProfile
    agent: ModelProfile
    host_identity: ModelIdentity
    agent_identity: ModelIdentity  # _agent_identity always returns an identity (agent_unresolved on failure), never None


def _agent_identity(project_path: Path | None) -> ModelIdentity:
    """Resolve the agent (executor) identity from the active provider."""
    from .model_identity import canonical_for_label
    from .providers import resolve_provider

    try:
        profile, source = resolve_provider(project_path)
    except Exception:
        logger.debug("resolve_active_profiles: provider resolution failed", exc_info=True)
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
    from .host_model_resolver import HostModelResolver

    host_identity = HostModelResolver().resolve(project_path)
    agent_identity = _agent_identity(project_path)
    return ActiveProfiles(
        host=profile_for(host_identity.canonical_model_key),
        agent=profile_for(agent_identity.canonical_model_key),
        host_identity=host_identity,
        agent_identity=agent_identity,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_model_profiles.py -k resolve_active -v`
Expected: PASS (3 tests). If the agent test fails because `anthropic-api` requires a key at resolution time, note: `resolve_provider` only reads config; `create_client` (not called here) is what validates keys — so resolution should succeed. If it does not, inject the provider via a `provider_fn` parameter instead (mirror the `HostModelResolver` injection pattern).

- [ ] **Step 5: Commit**

```bash
git add src/muscle/model_profiles.py tests/unit/test_model_profiles.py
git commit -m "feat(model-profiles): ActiveProfiles + resolve_active_profiles facade"
```

---

## Task 9: Gate sweep + dark-foundation confirmation

**Files:** none (verification only)

- [ ] **Step 1: Full new-module test run**

Run: `uv run pytest tests/unit/test_model_profiles.py tests/unit/test_host_model_resolver.py tests/unit/test_model_identity.py -v`
Expected: PASS (all).

- [ ] **Step 2: Type + lint + format gates**

Run:
```bash
uv run mypy src/muscle/model_profiles.py src/muscle/host_model_resolver.py src/muscle/model_identity.py
uv run ruff check src/muscle/model_profiles.py src/muscle/host_model_resolver.py src/muscle/model_identity.py
uv run ruff format --check src/muscle/model_profiles.py src/muscle/host_model_resolver.py
```
Expected: no errors. Auto-fix if needed: `uv run ruff check --fix …` and `uv run ruff format …`, then re-run.

- [ ] **Step 3: Confirm no production seam imports the new modules (dark foundation)**

Run: `grep -rn "model_profiles\|host_model_resolver\|resolve_active_profiles" src/muscle --include=*.py | grep -v "model_profiles.py\|host_model_resolver.py"`
Expected: **no matches** — nothing in production code consumes the framework yet. This is the proof Plan 1 changed zero runtime behavior.

- [ ] **Step 4: Full suite (background) for regression safety**

Run: `uv run pytest tests/ -q` (run in background per project memory; ~1–3.5 min).
Expected: PASS — no existing test regresses (the framework is unconsumed).

- [ ] **Step 5: Commit (if any lint/format auto-fixes were applied)**

```bash
git add -A
git commit -m "chore(model-profiles): pass mypy/ruff gates for Plan 1 framework"
```

---

## Self-Review (completed by plan author)

**Spec coverage (Plan 1 scope = framework + detection):**
- ✅ Typed `ModelProfile` registry (spec §3.1) — Tasks 2–3.
- ✅ Host detection via full resolver (spec §3.2) — Tasks 4–7.
- ✅ Agent detection via provider profile (spec §3.2) — Task 8.
- ✅ Opus canonical-key addition (spec §3.3) — Task 1.
- ✅ Conservative `default` + M3-no-op + Opus-full + Fable-placeholder profiles (spec §5) — Task 3.
- ✅ Fail-loud-on-unknown, quiet-on-None (spec §7) — Task 3 (`profile_for`).
- ⏭️ **Deferred to later plans (consumer seams):** agent-side thinking/effort (Plan 2), host docs + literalism fragment migration (Plan 3), oracle hardening (Plan 4), dependency/envelope (Plan 4), effort floor (Plan 5), learning reinforcement (Plan 6), handoff/cyber docs (Plan 7). Golden characterization snapshots are captured *inside* each consumer plan, immediately before its change.

**Placeholder scan:** `default_session_host_label`/`default_settings_host_label` are introduced as real no-op stubs in Task 4 and *fully implemented* in Tasks 5–6 (TDD ordering, not abandoned placeholders). No `TBD`/`TODO` remains in shipped code.

**Type consistency:** `ModelIdentity` fields match `project_memory_types.py`; `HostEffortLevel` from `host_effort_policy.py`; `profile_for`/`canonical_for_label`/`canonical_for_host_label` signatures are used consistently across tasks; `list_external_benchmark_turns(project_path, provider=, limit=)` matches `project_memory.py:3621`.

---

## Next plans (roadmap — written just-in-time before each is executed)

| Plan | Spec phase | Seam(s) | Key guard |
|---|---|---|---|
| **2 — Agent-side** | P3 | `anthropic_client._prepare_payload`, m27 | M3 request payload golden = byte-identical |
| **3 — Host docs** | P5 | `host_memory_templates`, publisher, plugin descriptions; migrate literalism into fragment | unknown/Fable host loses Opus lines; Opus keeps them |
| **4 — Security/eval** | P2+P4 | `review_benchmark` oracle, `source_context`, `untrusted_content` | oracle + dependency-context goldens |
| **5 — Effort floor** | P6 | `host_effort_policy`, `routing` | floor med→high only for Opus host |
| **6 — Learning** | P7 | `claude_publisher`, `verification_loop` | reinforcement behind `learning.*` |
| **7 — Handoff/cyber docs** | P8 | `handoff_generator`, `cli/provider` | text-only |
