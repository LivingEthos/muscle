"""
Host effort policy for Fable-aware orchestration.

Architecture Decision Record (ADR):
- Keep host effort separate from MiniMax M3 thinking modes; they tune different
  execution layers and must not share configuration.
- Escalate from evidence, not from static prose guidance.
- Fail safe on likely Fable fallback by suppressing max effort unless the user
  explicitly asks for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HostEffortLevel(str, Enum):
    """Host effort levels used by route and review metadata."""

    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


@dataclass(frozen=True)
class HostEffortDecision:
    """Effort decision for an expensive host-model step."""

    effort: HostEffortLevel
    max_output_tokens: int
    retry_ladder: list[HostEffortLevel]
    stop_condition: str
    rationale: str
    must_not_downgrade: bool
    avoided_escalation: bool = False

    def to_dict(self) -> dict[str, object]:
        """Serialize effort metadata for route JSON, artifacts, and reports."""
        return {
            "effort": self.effort.value,
            "max_output_tokens": self.max_output_tokens,
            "retry_ladder": [level.value for level in self.retry_ladder],
            "stop_condition": self.stop_condition,
            "rationale": self.rationale,
            "must_not_downgrade": self.must_not_downgrade,
            "avoided_escalation": self.avoided_escalation,
        }


_ORDER = (
    HostEffortLevel.MEDIUM,
    HostEffortLevel.HIGH,
    HostEffortLevel.XHIGH,
    HostEffortLevel.MAX,
)

_MAX_OUTPUT_TOKENS = {
    HostEffortLevel.MEDIUM: 4096,
    HostEffortLevel.HIGH: 8192,
    HostEffortLevel.XHIGH: 16384,
    HostEffortLevel.MAX: 32768,
}


def decide_host_effort(
    *,
    route_tier: str,
    target_type: str = "unknown",
    target_size: int = 0,
    verification_failure_count: int = 0,
    high_critical_issue_count: int = 0,
    task_novelty: bool = False,
    fallback_risk: bool = False,
    benchmark_mode: bool = False,
    explicit_user_maximum_effort: bool = False,
    time_budget_seconds: int | None = None,
    token_budget: int | None = None,
    synthesis_effort_floor: HostEffortLevel = HostEffortLevel.MEDIUM,
) -> HostEffortDecision:
    """Return a host effort decision from deterministic routing evidence.

    Args:
        route_tier: Routing tier such as ``mechanical`` or ``architectural``.
        target_type: Target shape, usually ``file`` or ``directory``.
        target_size: Optional size signal such as line or file count.
        verification_failure_count: Number of failed verification attempts.
        high_critical_issue_count: Count of unresolved high/critical issues.
        task_novelty: Whether the task is novel for this project.
        fallback_risk: Whether Fable preflight predicts fallback/degradation.
        benchmark_mode: Whether the call is part of a benchmark.
        explicit_user_maximum_effort: User explicitly requested maximum effort.
        time_budget_seconds: Optional wall-clock budget.
        token_budget: Optional token budget.
        synthesis_effort_floor: Minimum effort for intelligence-sensitive host
            synthesis, from the resolved host profile (raises the baseline only).

    Returns:
        HostEffortDecision with a bounded retry ladder and rationale.
    """
    effort = HostEffortLevel.MEDIUM
    reasons: list[str] = ["default medium for routine host synthesis"]
    must_not_downgrade = False

    floored = _max_effort(effort, synthesis_effort_floor)
    if floored != effort:
        effort = floored
        reasons.append(f"host synthesis effort floor {synthesis_effort_floor.value}")

    if route_tier == "architectural" or target_type == "directory" or target_size >= 10_000:
        effort = _max_effort(effort, HostEffortLevel.HIGH)
        reasons.append("wide or architectural task")

    if task_novelty:
        effort = _max_effort(effort, HostEffortLevel.HIGH)
        reasons.append("novel task")

    if high_critical_issue_count > 0:
        effort = _max_effort(effort, HostEffortLevel.HIGH)
        must_not_downgrade = True
        reasons.append("high/critical unverified issue present")

    if verification_failure_count > 0:
        effort = _max_effort(
            effort,
            _level_after_retries(HostEffortLevel.MEDIUM, verification_failure_count),
        )
        must_not_downgrade = True
        reasons.append(f"verification failed {verification_failure_count} time(s)")

    if benchmark_mode:
        effort = _max_effort(effort, HostEffortLevel.XHIGH)
        must_not_downgrade = True
        reasons.append("benchmark mode")

    if explicit_user_maximum_effort:
        effort = HostEffortLevel.MAX
        must_not_downgrade = True
        reasons.append("explicit maximum-effort request")

    avoided_escalation = False
    if fallback_risk and effort == HostEffortLevel.MAX and not explicit_user_maximum_effort:
        effort = HostEffortLevel.XHIGH
        avoided_escalation = True
        reasons.append("likely Fable fallback suppressed max escalation")
    elif fallback_risk:
        reasons.append("likely Fable fallback keeps effort conservative")

    if token_budget is not None and token_budget < _MAX_OUTPUT_TOKENS[effort]:
        effort = _budget_capped_effort(token_budget)
        reasons.append("token budget capped effort")

    if (
        time_budget_seconds is not None
        and time_budget_seconds < 60
        and effort.value
        in {
            "xhigh",
            "max",
        }
    ):
        effort = HostEffortLevel.HIGH
        reasons.append("short time budget capped hard-tail effort")

    retry_ladder = list(_ORDER[_ORDER.index(effort) :])
    return HostEffortDecision(
        effort=effort,
        max_output_tokens=_MAX_OUTPUT_TOKENS[effort],
        retry_ladder=retry_ladder,
        stop_condition=_stop_condition_for(
            verification_failure_count=verification_failure_count,
            high_critical_issue_count=high_critical_issue_count,
            benchmark_mode=benchmark_mode,
        ),
        rationale="; ".join(reasons),
        must_not_downgrade=must_not_downgrade,
        avoided_escalation=avoided_escalation,
    )


def host_effort_metadata(decision: HostEffortDecision) -> dict[str, object]:
    """Return standardized delegation metadata keys for host effort."""
    payload = decision.to_dict()
    return {
        "host_effort_level": payload["effort"],
        "host_effort_max_output_tokens": payload["max_output_tokens"],
        "host_effort_retry_ladder": payload["retry_ladder"],
        "host_effort_stop_condition": payload["stop_condition"],
        "host_effort_must_not_downgrade": payload["must_not_downgrade"],
        "host_effort_avoided_escalation": payload["avoided_escalation"],
    }


def _max_effort(left: HostEffortLevel, right: HostEffortLevel) -> HostEffortLevel:
    return left if _ORDER.index(left) >= _ORDER.index(right) else right


def _level_after_retries(base: HostEffortLevel, failures: int) -> HostEffortLevel:
    index = min(_ORDER.index(base) + failures, len(_ORDER) - 1)
    return _ORDER[index]


def _budget_capped_effort(token_budget: int) -> HostEffortLevel:
    for effort in reversed(_ORDER):
        if _MAX_OUTPUT_TOKENS[effort] <= token_budget:
            return effort
    return HostEffortLevel.MEDIUM


def _stop_condition_for(
    *,
    verification_failure_count: int,
    high_critical_issue_count: int,
    benchmark_mode: bool,
) -> str:
    if benchmark_mode:
        return "stop_after_benchmark_rubric_is_satisfied_or_budget_exhausted"
    if verification_failure_count > 0:
        return "stop_after_verification_passes_or_next_failure_requires_host_arbitration"
    if high_critical_issue_count > 0:
        return "stop_after_high_critical_claims_have_command_evidence"
    return "stop_after_evidence_backed_synthesis"
