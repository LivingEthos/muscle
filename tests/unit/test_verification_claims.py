"""Tests for typed verification claims and claim auditing."""

from __future__ import annotations

from muscle.verification_claims import (
    VerificationClaim,
    VerificationClaimType,
    audit_verification_claims,
)


def test_rejects_verified_end_to_end_with_lint_only_evidence() -> None:
    claim = VerificationClaim(
        claim_text="Verified end-to-end with ruff.",
        claim_type=VerificationClaimType.LINTED,
        evidence_id="cmd-abc",
        command=["ruff", "check"],
        exit_code=0,
    )

    audit = audit_verification_claims([claim])

    assert audit.allowed_claims == []
    assert audit.blocked_claims[0].claim_text == "Verified end-to-end with ruff."
    assert "runtime-smoke" in audit.blocked_claims[0].limitations[0]


def test_failed_command_evidence_must_be_surfaced() -> None:
    claim = VerificationClaim(
        claim_text="pytest validation failed.",
        claim_type=VerificationClaimType.RAN_TEST,
        evidence_id="cmd-fail",
        command=["pytest"],
        exit_code=1,
    )

    audit = audit_verification_claims([claim])

    assert audit.blocked_claims == [audit.blocked_claims[0]]
    assert audit.blocked_claims[0].exit_code == 1
    assert "failed command" in audit.blocked_claims[0].limitations[0]


def test_manual_inspection_downgrades_verified_language() -> None:
    claim = VerificationClaim(
        claim_text="Verified by manual inspection.",
        claim_type=VerificationClaimType.MANUAL_INSPECTION,
        limitations=["no command was run"],
    )

    audit = audit_verification_claims([claim])

    assert audit.allowed_claims == []
    assert audit.downgraded_claims[0].claim_text == "Inspected by manual inspection."
    assert "downgraded" in audit.downgraded_claims[0].limitations[-1]


def test_not_run_claims_stay_explicit() -> None:
    claim = VerificationClaim(
        claim_text="Runtime smoke was not run.",
        claim_type=VerificationClaimType.NOT_RUN,
        limitations=["review-only"],
    )

    audit = audit_verification_claims([claim])

    assert audit.not_run == [claim]
    assert audit.allowed_claims == []
