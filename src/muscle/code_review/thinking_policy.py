"""Per-stage MiniMax-M3 thinking-mode policy.

MiniMax-M3 exposes a request-time thinking toggle (see `m27_client._apply_thinking_param`).
This module maps each review-pipeline stage to the thinking mode that fits it:

- ``adaptive`` — MiniMax's recommended mode; the model decides reasoning depth.
  Used for analysis stages (semantic review, committee, verification, fix
  generation, pattern detection) where reasoning quality matters.
- ``disabled`` — reasoning off for latency-sensitive formatting / summarization
  stages (memory consolidation, handoff / skill / agent generation, strategy
  evolution) where deep reasoning adds latency without improving the output.

Both modes are billed identically by MiniMax, so this is a latency/quality lever,
not a cost lever. A single ``MUSCLE_THINKING_MODE`` env var overrides every stage
(useful for A/B measurement or forcing a mode); an unset/invalid value falls back
to the per-stage policy.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from types import MappingProxyType

from ..m27_client import VALID_THINKING_MODES

# Fail safe: an unknown/typo stage resolves to the cheapest mode (reasoning off),
# never the most expensive one, so refactor typos do not silently inflate latency.
UNKNOWN_STAGE_THINKING_MODE = "disabled"

THINKING_POLICY: Mapping[str, str] = MappingProxyType(
    {
        "semantic_review": "adaptive",
        "committee_review": "adaptive",
        "verification": "adaptive",
        "fix_generation": "adaptive",
        "pattern_detection": "adaptive",
        "memory_consolidation": "disabled",
        "handoff_generation": "disabled",
        "skill_generation": "disabled",
        "agent_generation": "disabled",
        "strategy_evolution": "disabled",
    }
)

# Fail fast on policy drift: every configured mode must be a valid thinking mode.
assert all(mode in VALID_THINKING_MODES for mode in THINKING_POLICY.values()), (
    "THINKING_POLICY contains a mode not in VALID_THINKING_MODES"
)

# One-shot guard so the global override warning fires once per process, not per call.
_override_warned = False


def thinking_for(stage: str) -> str:
    """Resolve the thinking mode for a review stage.

    ``MUSCLE_THINKING_MODE`` (if a valid mode) overrides all stages; otherwise the
    per-stage policy applies. An unknown stage warns and falls back to the cheapest
    mode (``disabled``) so typos fail loud and safe rather than silently selecting
    the most expensive mode.
    """
    global _override_warned
    override = os.environ.get("MUSCLE_THINKING_MODE", "").strip().lower()
    if override in VALID_THINKING_MODES:
        if not _override_warned:
            warnings.warn(
                f"MUSCLE_THINKING_MODE override is active: forcing thinking mode "
                f"'{override}' for ALL review stages.",
                RuntimeWarning,
                stacklevel=2,
            )
            _override_warned = True
        return override
    if stage not in THINKING_POLICY:
        warnings.warn(
            f"Unknown thinking stage '{stage}'; falling back to cheapest mode "
            f"'{UNKNOWN_STAGE_THINKING_MODE}'.",
            RuntimeWarning,
            stacklevel=2,
        )
        return UNKNOWN_STAGE_THINKING_MODE
    return THINKING_POLICY[stage]
