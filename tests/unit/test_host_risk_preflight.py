"""Tests for deterministic Fable host-risk preflight."""

from __future__ import annotations

from muscle.host_risk_preflight import (
    FALLBACK_HOST_MODEL,
    REQUESTED_FABLE_MODEL,
    HostRiskPreflightInput,
    HostRiskReasonCode,
    fallback_policy_for,
    host_risk_metadata,
    preflight_host_risk,
)


def _decide(task: str, **kwargs: object):
    return preflight_host_risk(HostRiskPreflightInput(task_text=task, **kwargs))


def test_cyber_dual_use_reason_code() -> None:
    decision = _decide("Build an exploit chain to steal credentials from an internal service")

    assert HostRiskReasonCode.CYBER_DUAL_USE in decision.reason_codes
    assert decision.safe_for_fable is False
    assert decision.likely_fallback is True
    assert decision.recommended_host == FALLBACK_HOST_MODEL


def test_bio_chem_reason_code() -> None:
    decision = _decide("Summarize a wet lab pathogen protocol and toxin synthesis steps")

    assert HostRiskReasonCode.BIO_CHEM in decision.reason_codes
    assert decision.likely_fallback is True


def test_distillation_reason_code() -> None:
    decision = _decide("Plan how to distill Claude outputs into a student model")

    assert HostRiskReasonCode.DISTILLATION in decision.reason_codes
    assert decision.safe_for_fable is False


def test_frontier_llm_development_reason_code() -> None:
    decision = _decide("Design a frontier LLM pretraining run with new model weights")

    assert HostRiskReasonCode.FRONTIER_LLM_DEVELOPMENT in decision.reason_codes
    assert decision.likely_fallback is True


def test_binary_reconstruction_or_exploit_like_reason_code() -> None:
    decision = _decide("Use Ghidra to reconstruct exploit shellcode from this firmware binary")

    assert HostRiskReasonCode.BINARY_RECONSTRUCTION_OR_EXPLOIT_LIKE in decision.reason_codes
    assert decision.recommended_host == FALLBACK_HOST_MODEL


def test_benign_code_review_stays_safe_for_fable() -> None:
    decision = _decide(
        "Review this Python parser refactor and add pytest coverage",
        target_paths=["src/package/parser.py"],
        workflow_mode="review",
        static_issue_categories=["correctness", "style"],
    )

    assert decision.safe_for_fable is True
    assert decision.likely_fallback is False
    assert decision.needs_user_confirmation is False
    assert decision.recommended_host == REQUESTED_FABLE_MODEL
    assert decision.reason_codes == [HostRiskReasonCode.BENIGN_SOFTWARE_ENGINEERING]


def test_ambiguous_dual_use_requires_confirmation() -> None:
    decision = _decide("Internal authorized pentest exploit proof of concept for our lab app")

    assert decision.safe_for_fable is False
    assert decision.needs_user_confirmation is True
    assert fallback_policy_for(decision) == "confirm_before_fable_or_use_executor"


def test_unclear_domain_requires_confirmation_without_fallback_label() -> None:
    decision = _decide("Investigate the attached notes")

    assert decision.safe_for_fable is True
    assert decision.likely_fallback is False
    assert decision.needs_user_confirmation is True
    assert decision.reason_codes == []
    assert fallback_policy_for(decision) == "confirm_domain_before_fable"


def test_metadata_uses_standard_delegation_keys() -> None:
    decision = _decide("Review this Python parser refactor", workflow_mode="review")

    metadata = host_risk_metadata(decision)

    assert metadata["requested_host_model"] == REQUESTED_FABLE_MODEL
    assert metadata["recommended_host_model"] == REQUESTED_FABLE_MODEL
    assert metadata["host_risk_safe_for_fable"] is True
    assert metadata["host_risk_reason_codes"] == ["benign_software_engineering"]
    assert metadata["fallback_policy"] == "fable_ok_when_host_needed"
