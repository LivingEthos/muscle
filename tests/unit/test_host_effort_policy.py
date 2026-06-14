"""Tests for the host effort ladder."""

from __future__ import annotations

from muscle.host_effort_policy import HostEffortLevel, decide_host_effort, host_effort_metadata


def test_routine_task_defaults_to_medium() -> None:
    decision = decide_host_effort(route_tier="mechanical", target_type="file")

    assert decision.effort == HostEffortLevel.MEDIUM
    assert decision.max_output_tokens == 4096
    assert decision.must_not_downgrade is False


def test_architectural_route_uses_high_effort() -> None:
    decision = decide_host_effort(route_tier="architectural", target_type="directory")

    assert decision.effort == HostEffortLevel.HIGH
    assert decision.retry_ladder[0] == HostEffortLevel.HIGH


def test_high_critical_unverified_fixes_cannot_stay_medium() -> None:
    decision = decide_host_effort(
        route_tier="mechanical",
        high_critical_issue_count=1,
    )

    assert decision.effort == HostEffortLevel.HIGH
    assert decision.must_not_downgrade is True


def test_verification_failures_escalate_one_rung_per_retry() -> None:
    first_failure = decide_host_effort(
        route_tier="mechanical",
        verification_failure_count=1,
    )
    second_failure = decide_host_effort(
        route_tier="mechanical",
        verification_failure_count=2,
    )

    assert first_failure.effort == HostEffortLevel.HIGH
    assert second_failure.effort == HostEffortLevel.XHIGH


def test_benchmark_mode_uses_xhigh_effort() -> None:
    decision = decide_host_effort(route_tier="reasoning", benchmark_mode=True)

    assert decision.effort == HostEffortLevel.XHIGH
    assert decision.must_not_downgrade is True


def test_likely_fallback_suppresses_unrequested_max_escalation() -> None:
    decision = decide_host_effort(
        route_tier="mechanical",
        verification_failure_count=3,
        fallback_risk=True,
    )

    assert decision.effort == HostEffortLevel.XHIGH
    assert decision.avoided_escalation is True


def test_explicit_maximum_request_can_use_max_even_with_fallback_risk() -> None:
    decision = decide_host_effort(
        route_tier="mechanical",
        fallback_risk=True,
        explicit_user_maximum_effort=True,
    )

    assert decision.effort == HostEffortLevel.MAX
    assert decision.avoided_escalation is False
    assert decision.must_not_downgrade is True


def test_metadata_uses_standard_delegation_keys() -> None:
    decision = decide_host_effort(route_tier="architectural", high_critical_issue_count=2)

    metadata = host_effort_metadata(decision)

    assert metadata["host_effort_level"] == "high"
    assert metadata["host_effort_max_output_tokens"] == 8192
    assert metadata["host_effort_must_not_downgrade"] is True
    assert metadata["host_effort_retry_ladder"] == ["high", "xhigh", "max"]


def test_synthesis_floor_raises_routine_medium_to_high() -> None:
    decision = decide_host_effort(
        route_tier="mechanical",
        target_type="file",
        synthesis_effort_floor=HostEffortLevel.HIGH,
    )
    assert decision.effort == HostEffortLevel.HIGH
    assert decision.retry_ladder[0] == HostEffortLevel.HIGH
    assert "host synthesis effort floor high" in decision.rationale


def test_synthesis_floor_default_medium_is_noop() -> None:
    floored = decide_host_effort(
        route_tier="mechanical",
        target_type="file",
        synthesis_effort_floor=HostEffortLevel.MEDIUM,
    )
    baseline = decide_host_effort(route_tier="mechanical", target_type="file")
    assert floored.effort == HostEffortLevel.MEDIUM
    assert floored.to_dict() == baseline.to_dict()


def test_synthesis_floor_does_not_lower_higher_evidence_effort() -> None:
    decision = decide_host_effort(
        route_tier="mechanical",
        verification_failure_count=2,
        synthesis_effort_floor=HostEffortLevel.HIGH,
    )
    assert decision.effort == HostEffortLevel.XHIGH
    # The floor must not disturb the evidence-driven must_not_downgrade flag.
    assert decision.must_not_downgrade is True
