"""
Typed verification claims for MUSCLE reports and artifacts.

Architecture Decision Record (ADR):
- Keep verification language grounded in command evidence or explicit not-run
  limitations instead of relying on prose summaries.
- Downgrade over-strong manual claims to inspected language.
- Treat failed commands as first-class claims so summaries cannot hide them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .command_evidence import CommandEvidence, command_label


class VerificationClaimType(str, Enum):
    """Supported verification claim categories."""

    RAN_TEST = "ran_test"
    TYPECHECKED = "typechecked"
    LINTED = "linted"
    MANUAL_INSPECTION = "manual_inspection"
    RUNTIME_SMOKE = "runtime_smoke"
    NOT_RUN = "not_run"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class VerificationClaim:
    """One evidence-backed or limitation-backed verification statement."""

    claim_text: str
    claim_type: VerificationClaimType
    evidence_id: str | None = None
    command: list[str] | None = None
    exit_code: int | None = None
    observed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this claim for artifact JSON."""
        data = asdict(self)
        data["claim_type"] = self.claim_type.value
        return data


@dataclass(frozen=True)
class ClaimAuditResult:
    """Audited claim buckets for report generation."""

    allowed_claims: list[VerificationClaim] = field(default_factory=list)
    downgraded_claims: list[VerificationClaim] = field(default_factory=list)
    blocked_claims: list[VerificationClaim] = field(default_factory=list)
    not_run: list[VerificationClaim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize audit buckets for artifact JSON."""
        return {
            "allowed_claims": [claim.to_dict() for claim in self.allowed_claims],
            "downgraded_claims": [claim.to_dict() for claim in self.downgraded_claims],
            "blocked_claims": [claim.to_dict() for claim in self.blocked_claims],
            "not_run": [claim.to_dict() for claim in self.not_run],
        }


def claim_from_command_evidence(
    evidence: CommandEvidence,
    *,
    claim_type: VerificationClaimType,
    claim_text: str | None = None,
) -> VerificationClaim:
    """Create a claim linked to command evidence."""
    text = claim_text or _default_command_claim_text(evidence, claim_type)
    return VerificationClaim(
        claim_text=text,
        claim_type=claim_type,
        evidence_id=evidence.evidence_id,
        command=list(evidence.command),
        exit_code=evidence.exit_code,
        observed_at=evidence.created_at,
        limitations=list(evidence.warnings),
    )


def audit_verification_claims(claims: list[VerificationClaim]) -> ClaimAuditResult:
    """Audit claims so final reports cannot overstate verification."""
    allowed: list[VerificationClaim] = []
    downgraded: list[VerificationClaim] = []
    blocked: list[VerificationClaim] = []
    not_run: list[VerificationClaim] = []

    for claim in claims:
        lowered = claim.claim_text.lower()
        if claim.claim_type is VerificationClaimType.NOT_RUN:
            not_run.append(claim)
            continue
        if claim.claim_type is VerificationClaimType.BLOCKED:
            blocked.append(claim)
            continue
        if claim.exit_code is not None and claim.exit_code != 0:
            blocked.append(
                _with_limitation(
                    claim,
                    f"command exited with {claim.exit_code}; failed command must be surfaced",
                )
            )
            continue
        if "end-to-end" in lowered and claim.claim_type is not VerificationClaimType.RUNTIME_SMOKE:
            blocked.append(
                _with_limitation(
                    claim,
                    "end-to-end claims require runtime-smoke evidence",
                )
            )
            continue
        if "verified" in lowered and not _has_passing_evidence(claim):
            downgraded.append(_downgrade_verified_to_inspected(claim))
            continue
        allowed.append(claim)

    return ClaimAuditResult(
        allowed_claims=allowed,
        downgraded_claims=downgraded,
        blocked_claims=blocked,
        not_run=not_run,
    )


def _default_command_claim_text(
    evidence: CommandEvidence,
    claim_type: VerificationClaimType,
) -> str:
    status = "passed" if evidence.exit_code == 0 else "failed"
    return f"{claim_type.value} command {status}: {command_label(evidence.command)}"


def _has_passing_evidence(claim: VerificationClaim) -> bool:
    if claim.claim_type not in {
        VerificationClaimType.RAN_TEST,
        VerificationClaimType.TYPECHECKED,
        VerificationClaimType.LINTED,
        VerificationClaimType.RUNTIME_SMOKE,
    }:
        return False
    return bool(claim.evidence_id) and claim.exit_code == 0


def _downgrade_verified_to_inspected(claim: VerificationClaim) -> VerificationClaim:
    text = claim.claim_text.replace("verified", "inspected").replace("Verified", "Inspected")
    return _with_limitation(
        replace(claim, claim_text=text),
        "verified language downgraded because only manual or missing evidence was present",
    )


def _with_limitation(claim: VerificationClaim, limitation: str) -> VerificationClaim:
    limitations = [*claim.limitations, limitation]
    return replace(claim, limitations=limitations)
