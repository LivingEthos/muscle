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

from ..m27_client import VALID_THINKING_MODES

DEFAULT_THINKING_MODE = "adaptive"

THINKING_POLICY: dict[str, str] = {
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


def thinking_for(stage: str) -> str:
    """Resolve the thinking mode for a review stage.

    ``MUSCLE_THINKING_MODE`` (if a valid mode) overrides all stages; otherwise the
    per-stage policy applies, defaulting to ``adaptive`` for unknown stages.
    """
    override = os.environ.get("MUSCLE_THINKING_MODE", "").strip().lower()
    if override in VALID_THINKING_MODES:
        return override
    return THINKING_POLICY.get(stage, DEFAULT_THINKING_MODE)
