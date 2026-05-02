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
    routing_profile: str = "current"


@dataclass(frozen=True)
class RoutingBenchmarkCase:
    name: str
    task_description: str
    expected: Recommendation
    preferred_tier: TaskTier


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
ROUTING_PROFILE_CURRENT = "current"
ROUTING_PROFILE_LEAN_REVIEW_V1 = "lean_review_v1"
ROUTING_COST_UNITS = {
    Recommendation.M27: 1,
    Recommendation.M27_WITH_VERIFY: 2,
    Recommendation.ESCALATE_TO_HOST: 4,
}
ROUTING_BENCHMARK_CASES: tuple[RoutingBenchmarkCase, ...] = (
    RoutingBenchmarkCase(
        name="review_file_with_findings",
        task_description=(
            "mode=review; workflow=review-smart; target=file:/tmp/a.py; intensity=medium; "
            "static_issue_count=4; language=python; fetch_sources=False"
        ),
        expected=Recommendation.M27_WITH_VERIFY,
        preferred_tier=TaskTier.REASONING,
    ),
    RoutingBenchmarkCase(
        name="directory_pressure_sweep",
        task_description=(
            "mode=pressure; workflow=pressure-review; target=directory:/tmp/proj; intensity=deep; "
            "static_issue_count=12; language=python; fetch_sources=False"
        ),
        expected=Recommendation.ESCALATE_TO_HOST,
        preferred_tier=TaskTier.ARCHITECTURAL,
    ),
    RoutingBenchmarkCase(
        name="auto_fix_mechanical",
        task_description=(
            "mode=auto-fix; workflow=review-fix-verify; target=file:/tmp/app.py; intensity=medium; "
            "static_issue_count=1; language=python; fetch_sources=False"
        ),
        expected=Recommendation.M27_WITH_VERIFY,
        preferred_tier=TaskTier.MECHANICAL,
    ),
)


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
            routing_profile=ROUTING_PROFILE_CURRENT,
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
        """Look up a cached route decision by key. Returns None on miss."""
        from .response_cache import ResponseCache

        cache = ResponseCache(self._cache_db)
        raw_key = key.removeprefix("route:")
        cached = cache.get(raw_key)
        if cached is None:
            return None
        return {
            "tier": TaskTier(cached["tier"]),
            "recommended": Recommendation(cached["recommended"]),
            "confidence": cached["confidence"],
            "rationale": cached["rationale"],
            "routing_profile": cached.get("routing_profile", ROUTING_PROFILE_CURRENT),
        }

    def _cache_put(self, key: str, decision: RouteDecision) -> None:
        """Store a route decision in the response cache with 24h TTL."""
        from .response_cache import ResponseCache

        cache = ResponseCache(self._cache_db)
        raw_key = key.removeprefix("route:")
        cache.put(
            key=raw_key,
            model_id="task_router",
            response={
                "tier": decision.tier.value,
                "recommended": decision.recommended.value,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                "routing_profile": decision.routing_profile,
            },
            ttl_seconds=24 * 60 * 60,
        )


def benchmark_routing_profiles() -> dict[str, Any]:
    """Compare the current routing policy to a small candidate policy."""
    comparisons: list[dict[str, Any]] = []
    for case in ROUTING_BENCHMARK_CASES:
        baseline = _offline_route(case.task_description, ROUTING_PROFILE_CURRENT)
        candidate = _offline_route(case.task_description, ROUTING_PROFILE_LEAN_REVIEW_V1)
        comparisons.append(
            {
                "case": case.name,
                "expected": case.expected.value,
                "baseline": _route_eval(case, baseline),
                "candidate": _route_eval(case, candidate),
            }
        )

    baseline_quality = sum(int(item["baseline"]["matches_expected"]) for item in comparisons)
    candidate_quality = sum(int(item["candidate"]["matches_expected"]) for item in comparisons)
    baseline_cost = sum(int(item["baseline"]["cost_units"]) for item in comparisons)
    candidate_cost = sum(int(item["candidate"]["cost_units"]) for item in comparisons)
    candidate_kept = (candidate_quality > baseline_quality and candidate_cost <= baseline_cost) or (
        candidate_quality == baseline_quality and candidate_cost < baseline_cost
    )
    return {
        "cases": comparisons,
        "baseline_quality": baseline_quality,
        "candidate_quality": candidate_quality,
        "baseline_cost_units": baseline_cost,
        "candidate_cost_units": candidate_cost,
        "promotion_rule": (
            "Keep a routing candidate only when it improves expected-quality matches, "
            "estimated routing cost, or both without regressing the other dimension."
        ),
        "candidate_kept": candidate_kept,
    }


def _offline_route(task_description: str, profile: str) -> RouteDecision:
    features = _extract_route_features(task_description)
    mode = features.get("mode", "review")
    target_type = features.get("target_type", "file")
    intensity = features.get("intensity", "medium")
    static_issue_count = int(features.get("static_issue_count", 0) or 0)

    if "pressure-review" in task_description or mode == "pressure":
        return RouteDecision(
            tier=TaskTier.ARCHITECTURAL,
            recommended=Recommendation.ESCALATE_TO_HOST,
            confidence=0.85,
            rationale="Pressure sweeps stay host-planned.",
            routing_profile=profile,
        )

    if profile == ROUTING_PROFILE_LEAN_REVIEW_V1:
        if target_type == "directory" and intensity in {"high", "deep"}:
            return RouteDecision(
                tier=TaskTier.ARCHITECTURAL,
                recommended=Recommendation.ESCALATE_TO_HOST,
                confidence=0.72,
                rationale="Wide-scope directory reviews stay host-planned.",
                routing_profile=profile,
            )
        if static_issue_count > 0 or mode in {"auto-fix", "hybrid"}:
            return RouteDecision(
                tier=TaskTier.REASONING if static_issue_count > 0 else TaskTier.MECHANICAL,
                recommended=Recommendation.M27_WITH_VERIFY,
                confidence=0.79,
                rationale="Findings-bearing or fix-applying work gets verification.",
                routing_profile=profile,
            )

    if mode in {"auto-fix", "hybrid"}:
        return RouteDecision(
            tier=TaskTier.MECHANICAL,
            recommended=Recommendation.M27_WITH_VERIFY,
            confidence=0.81,
            rationale="Fix application requires verification.",
            routing_profile=profile,
        )

    return RouteDecision(
        tier=TaskTier.REASONING if static_issue_count > 0 else TaskTier.MECHANICAL,
        recommended=Recommendation.M27,
        confidence=0.68,
        rationale="Default review work can stay on M2.7.",
        routing_profile=profile,
    )


def _extract_route_features(task_description: str) -> dict[str, str]:
    features: dict[str, str] = {}
    for part in task_description.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "target":
            target_type, _, target_value = value.partition(":")
            features["target_type"] = target_type
            features["target_path"] = target_value
        else:
            features[key] = value
    return features


def _route_eval(case: RoutingBenchmarkCase, decision: RouteDecision) -> dict[str, Any]:
    return {
        "tier": decision.tier.value,
        "recommended": decision.recommended.value,
        "matches_expected": decision.recommended == case.expected,
        "preferred_tier_match": decision.tier == case.preferred_tier,
        "cost_units": ROUTING_COST_UNITS[decision.recommended],
        "routing_profile": decision.routing_profile,
    }


def _parse_json_response(text: str) -> dict[str, Any]:
    """Strip fences if present; parse JSON; raise on malformed."""
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    result: dict[str, Any] = json.loads(text.strip())
    return result
