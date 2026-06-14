"""
Async worker policy for hard-tail review orchestration.

Architecture Decision Record (ADR):
- Keep async review workers opt-in so easy foreground reviews stay deterministic.
- Use explicit hard-tail triggers rather than LLM judgment for worker fan-out.
- Deduplicate worker findings with structured keys to avoid fuzzy issue loss.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from .types import ReviewIssue

DEFAULT_ASYNC_WORKER_LIMIT = 3
TARGET_FILE_THRESHOLD = 6
TARGET_MODULE_THRESHOLD = 3
LOW_ROUTE_CONFIDENCE_THRESHOLD = 0.55
POOR_HISTORICAL_PASS_RATE_THRESHOLD = 0.50

TRIGGER_WIDE_TARGET_SCOPE = "wide_target_scope"
TRIGGER_VERIFICATION_FAILED_ONCE = "verification_failed_once"
TRIGGER_MULTI_SUBSYSTEM_ISSUE = "multi_subsystem_issue"
TRIGGER_LOW_NON_ARCH_ROUTE_CONFIDENCE = "low_non_architectural_route_confidence"
TRIGGER_POOR_HISTORICAL_PASS_RATE = "poor_historical_pass_rate"

SKIP_DISABLED = "disabled"
SKIP_EASY_TASK = "easy_task"


@dataclass(frozen=True)
class AsyncWorkerPolicyInput:
    """Inputs used by the deterministic hard-tail async-worker policy."""

    enabled: bool
    target_file_count: int = 0
    module_count: int = 0
    verification_failure_count: int = 0
    subsystem_count: int = 0
    route_confidence: float | None = None
    route_tier: str | None = None
    historical_pass_rate: float | None = None
    worker_limit: int = DEFAULT_ASYNC_WORKER_LIMIT
    target_file_threshold: int = TARGET_FILE_THRESHOLD
    target_module_threshold: int = TARGET_MODULE_THRESHOLD
    low_route_confidence_threshold: float = LOW_ROUTE_CONFIDENCE_THRESHOLD
    poor_historical_pass_rate_threshold: float = POOR_HISTORICAL_PASS_RATE_THRESHOLD


@dataclass(frozen=True)
class AsyncWorkerJobMetadata:
    """Metadata for one queued or completed async worker job."""

    job_id: str
    status: str
    target_path: str
    trigger_reasons: list[str]
    evidence_id: str
    token_usage: int = 0
    artifact_dir: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable worker job record."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "target_path": self.target_path,
            "trigger_reasons": list(self.trigger_reasons),
            "evidence_id": self.evidence_id,
            "token_usage": self.token_usage,
            "artifact_dir": self.artifact_dir,
        }


@dataclass
class AsyncWorkerPolicyDecision:
    """Decision and artifact metadata for async-worker orchestration."""

    enabled: bool
    should_run: bool
    trigger_reasons: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    worker_limit: int = DEFAULT_ASYNC_WORKER_LIMIT
    critical_path_time_ms: int = 0
    worker_token_usage: int = 0
    worker_evidence_ids: list[str] = field(default_factory=list)
    worker_jobs: list[AsyncWorkerJobMetadata] = field(default_factory=list)
    worker_errors: list[str] = field(default_factory=list)
    arbitration_scope: str = "compact_disagreements"

    def add_worker_job(self, job: AsyncWorkerJobMetadata) -> None:
        """Attach one worker job and update derived evidence/token metadata."""
        self.worker_jobs.append(job)
        self.worker_evidence_ids.append(job.evidence_id)
        self.worker_token_usage += job.token_usage

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-serializable decision payload."""
        return {
            "enabled": self.enabled,
            "should_run": self.should_run,
            "trigger_reasons": list(self.trigger_reasons),
            "skipped_reason": self.skipped_reason,
            "worker_limit": self.worker_limit,
            "critical_path_time_ms": self.critical_path_time_ms,
            "worker_token_usage": self.worker_token_usage,
            "worker_evidence_ids": list(self.worker_evidence_ids),
            "worker_jobs": [job.to_dict() for job in self.worker_jobs],
            "worker_errors": list(self.worker_errors),
            "arbitration_scope": self.arbitration_scope,
        }


def decide_async_worker_policy(inputs: AsyncWorkerPolicyInput) -> AsyncWorkerPolicyDecision:
    """Evaluate deterministic hard-tail triggers for async worker fan-out."""
    start = perf_counter()
    worker_limit = max(1, inputs.worker_limit)
    if not inputs.enabled:
        return AsyncWorkerPolicyDecision(
            enabled=False,
            should_run=False,
            skipped_reason=SKIP_DISABLED,
            worker_limit=worker_limit,
            critical_path_time_ms=_elapsed_ms(start),
        )

    reasons: list[str] = []
    if (
        inputs.target_file_count >= inputs.target_file_threshold
        or inputs.module_count >= inputs.target_module_threshold
    ):
        reasons.append(TRIGGER_WIDE_TARGET_SCOPE)

    if inputs.verification_failure_count > 0:
        reasons.append(TRIGGER_VERIFICATION_FAILED_ONCE)

    if inputs.subsystem_count >= 2:
        reasons.append(TRIGGER_MULTI_SUBSYSTEM_ISSUE)

    route_tier = (inputs.route_tier or "").lower()
    if (
        inputs.route_confidence is not None
        and inputs.route_confidence < inputs.low_route_confidence_threshold
        and route_tier != "architectural"
    ):
        reasons.append(TRIGGER_LOW_NON_ARCH_ROUTE_CONFIDENCE)

    if (
        inputs.historical_pass_rate is not None
        and inputs.historical_pass_rate < inputs.poor_historical_pass_rate_threshold
    ):
        reasons.append(TRIGGER_POOR_HISTORICAL_PASS_RATE)

    return AsyncWorkerPolicyDecision(
        enabled=True,
        should_run=bool(reasons),
        trigger_reasons=reasons,
        skipped_reason=None if reasons else SKIP_EASY_TASK,
        worker_limit=worker_limit,
        critical_path_time_ms=_elapsed_ms(start),
    )


def build_worker_evidence_id(*, session_id: str, job_id: str, trigger_reasons: list[str]) -> str:
    """Build a deterministic evidence id for an async worker job record."""
    raw = "|".join([session_id, job_id, ",".join(sorted(trigger_reasons))])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"async-worker:{digest}"


def dedupe_worker_findings(findings: list[ReviewIssue]) -> list[ReviewIssue]:
    """Deduplicate worker findings by structured issue identity.

    The key intentionally includes category and source agent so distinct issue
    classes or independent agents are not merged merely because they mention the
    same line.
    """
    seen: set[tuple[str, int, str, str, str]] = set()
    deduped: list[ReviewIssue] = []
    for issue in findings:
        key = (
            issue.file_path,
            issue.line_number,
            issue.category.value,
            issue.cwe_id or "",
            issue.source_agent or "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _elapsed_ms(start: float) -> int:
    return max(0, int((perf_counter() - start) * 1000))
