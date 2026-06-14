"""Tests for deterministic async worker hard-tail policy."""

from __future__ import annotations

from muscle.code_review.async_worker_policy import (
    SKIP_EASY_TASK,
    TRIGGER_MULTI_SUBSYSTEM_ISSUE,
    TRIGGER_VERIFICATION_FAILED_ONCE,
    AsyncWorkerPolicyInput,
    build_worker_evidence_id,
    decide_async_worker_policy,
    dedupe_worker_findings,
)
from muscle.code_review.types import IssueCategory, ReviewIssue, Severity


def _issue(
    *,
    category: IssueCategory = IssueCategory.SECURITY,
    source_agent: str = "agent-a",
) -> ReviewIssue:
    return ReviewIssue(
        file_path="src/auth.py",
        line_number=12,
        severity=Severity.HIGH,
        category=category,
        cwe_id="CWE-89",
        title="Finding",
        description="Description",
        code_snippet="code",
        source_agent=source_agent,
    )


def test_easy_task_does_not_trigger_workers() -> None:
    decision = decide_async_worker_policy(
        AsyncWorkerPolicyInput(
            enabled=True,
            target_file_count=1,
            module_count=1,
            verification_failure_count=0,
            subsystem_count=1,
            route_confidence=0.9,
            route_tier="reasoning",
            historical_pass_rate=0.9,
        )
    )

    assert decision.should_run is False
    assert decision.skipped_reason == SKIP_EASY_TASK
    assert decision.worker_jobs == []


def test_verification_failure_triggers_workers() -> None:
    decision = decide_async_worker_policy(
        AsyncWorkerPolicyInput(
            enabled=True,
            target_file_count=1,
            module_count=1,
            verification_failure_count=1,
            subsystem_count=1,
        )
    )

    assert decision.should_run is True
    assert decision.trigger_reasons == [TRIGGER_VERIFICATION_FAILED_ONCE]


def test_multi_subsystem_trigger_is_distinct() -> None:
    decision = decide_async_worker_policy(
        AsyncWorkerPolicyInput(
            enabled=True,
            target_file_count=2,
            module_count=2,
            subsystem_count=2,
        )
    )

    assert decision.should_run is True
    assert TRIGGER_MULTI_SUBSYSTEM_ISSUE in decision.trigger_reasons


def test_worker_dedupe_preserves_distinct_issue_categories() -> None:
    security = _issue(category=IssueCategory.SECURITY)
    correctness = _issue(category=IssueCategory.CORRECTNESS)
    duplicate_security = _issue(category=IssueCategory.SECURITY)

    deduped = dedupe_worker_findings([security, correctness, duplicate_security])

    assert deduped == [security, correctness]


def test_worker_evidence_id_is_deterministic() -> None:
    first = build_worker_evidence_id(
        session_id="session",
        job_id="job",
        trigger_reasons=["b", "a"],
    )
    second = build_worker_evidence_id(
        session_id="session",
        job_id="job",
        trigger_reasons=["a", "b"],
    )

    assert first == second
    assert first.startswith("async-worker:")
