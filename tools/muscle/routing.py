"""Classifier that decides where a task should run (M2.7 vs host model)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TaskTier(str, Enum):
    MECHANICAL = "mechanical"
    REASONING = "reasoning"
    ARCHITECTURAL = "architectural"


class Recommendation(str, Enum):
    M27 = "m27"
    M27_WITH_VERIFY = "m27_with_verify"
    ESCALATE_TO_HOST = "escalate_to_host"


@dataclass
class RouteDecision:
    tier: TaskTier
    recommended: Recommendation
    confidence: float
    rationale: str
    from_cache: bool = False


ROUTE_SYSTEM_PROMPT = """You are a task-complexity classifier. Given a task description, decide:
1. tier: 'mechanical' (pattern/boilerplate/test), 'reasoning' (debug/trace/refactor), or 'architectural' (design/decision/multi-module).
2. recommended: 'm27' for direct M2.7 execution, 'm27_with_verify' for M2.7 with verification loop, 'escalate_to_host' for the host model to plan directly.
3. confidence: 0.0-1.0.
4. rationale: one short sentence.

Rules:
- 'architectural' tasks ALWAYS get 'escalate_to_host'.
- 'mechanical' tasks with obvious test targets get 'm27_with_verify'.
- Otherwise 'm27'.
- If confidence < 0.5, default to 'escalate_to_host'.

Return ONLY valid JSON matching the schema: {"tier": ..., "recommended": ..., "confidence": ..., "rationale": ...}.
"""

# Confidence threshold below which tasks escalate to host regardless of tier.
ESCALATION_CONFIDENCE_THRESHOLD = 0.5


class TaskRouter:
    def __init__(
        self,
        m27_client: Any,
        cache_db_path: Path | None = None,
    ) -> None:
        self._m27 = m27_client
        self._cache_db = cache_db_path or Path.home() / ".muscle" / "cache" / "cache.db"

    def route(self, task_description: str, scope: Path | None = None) -> RouteDecision:
        cache_key = self._cache_key(task_description, scope)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return RouteDecision(**cached, from_cache=True)

        decision = self._classify_via_m27(task_description, scope)
        self._cache_put(cache_key, decision)
        return decision

    def _classify_via_m27(self, task: str, scope: Path | None) -> RouteDecision:
        user_prompt = f"Task: {task}"
        if scope:
            user_prompt += f"\nScope hint: {scope}"

        response, _ = self._m27.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=ROUTE_SYSTEM_PROMPT,
            max_tokens=256,
            temperature=0.1,
        )
        data = _parse_json_response(response)

        tier = TaskTier(data["tier"])
        recommended = Recommendation(data["recommended"])
        confidence = float(data["confidence"])

        # Enforce invariant: architectural tasks always escalate.
        if tier == TaskTier.ARCHITECTURAL:
            recommended = Recommendation.ESCALATE_TO_HOST

        # Enforce invariant: low confidence always escalates.
        if confidence < ESCALATION_CONFIDENCE_THRESHOLD:
            recommended = Recommendation.ESCALATE_TO_HOST

        return RouteDecision(
            tier=tier,
            recommended=recommended,
            confidence=confidence,
            rationale=data["rationale"],
        )

    def _cache_key(self, task: str, scope: Path | None) -> str:
        scope_fp = self._scope_fingerprint(scope) if scope else ""
        h = hashlib.sha256(f"{task}||{scope_fp}".encode()).hexdigest()
        return f"route:{h}"

    @staticmethod
    def _scope_fingerprint(scope: Path) -> str:
        if not scope.exists():
            return ""
        pairs: list[tuple[str, str]] = []
        if scope.is_file():
            pairs.append((str(scope), hashlib.sha256(scope.read_bytes()).hexdigest()))
        else:
            for p in sorted(scope.rglob("*")):
                if p.is_file():
                    try:
                        pairs.append((str(p), hashlib.sha256(p.read_bytes()).hexdigest()))
                    except OSError:
                        continue
        return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        """No-op until B.3 (response cache) ships. Returns None always."""
        return None

    def _cache_put(self, key: str, decision: RouteDecision) -> None:
        """No-op until B.3 (response cache) ships."""
        pass


def _parse_json_response(text: str) -> dict[str, Any]:
    """Strip fences if present; parse JSON; raise on malformed."""
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    result: dict[str, Any] = json.loads(text.strip())
    return result
