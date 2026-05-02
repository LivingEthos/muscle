"""Regression tests for strict fix verification."""

from __future__ import annotations

from pathlib import Path

from tools.muscle.code_review.types import IssueCategory, ReviewIssue, Severity
from tools.muscle.code_review.verification_loop import VerificationLoop
from tools.muscle.m27_client import TokenUsage


def _issue(file_path: Path) -> ReviewIssue:
    return ReviewIssue(
        file_path=str(file_path),
        line_number=1,
        severity=Severity.MEDIUM,
        category=IssueCategory.CORRECTNESS,
        cwe_id=None,
        title="Incomplete fix",
        description="The proposed fix must be semantically verified.",
        code_snippet="value = 1",
        suggested_fix=None,
        auto_fixable=True,
    )


def test_needs_work_verifier_response_rejects_and_reverts(tmp_path, monkeypatch):
    target = tmp_path / "sample.py"
    original = "value = 1\n"
    fixed = "value = 2\n"
    target.write_text(original, encoding="utf-8")

    verifier = VerificationLoop(
        m27_client=object(),  # type: ignore[arg-type]
        verify_compile=False,
        verify_linter=False,
        verify_tests=False,
    )
    monkeypatch.setattr(
        verifier,
        "_m27_verify",
        lambda _issue, _fixed: ("NEEDS_WORK: still misses the edge case", TokenUsage(1, 2)),
    )
    monkeypatch.setattr(verifier, "_m27_analyze_failure", lambda _issue, _text: "incomplete")

    result = verifier.verify_fix(_issue(target), fixed)

    assert result.fix_verified is False
    assert result.reverted is True
    assert result.failure_analysis == "incomplete"
    assert target.read_text(encoding="utf-8") == original


def test_validator_exceptions_fail_closed(tmp_path, monkeypatch):
    target = tmp_path / "sample.py"
    original = "value = 1\n"
    fixed = "value = 2\n"
    target.write_text(original, encoding="utf-8")

    verifier = VerificationLoop(
        m27_client=None,
        verify_compile=True,
        verify_linter=False,
        verify_tests=False,
    )
    monkeypatch.setattr(
        verifier,
        "_check_compilation",
        lambda _path, _language: (_ for _ in ()).throw(OSError("boom")),
    )

    result = verifier.verify_fix(_issue(target), fixed)

    assert result.fix_verified is False
    assert result.reverted is True
    assert "Exception during verification" in result.verification_details
    assert target.read_text(encoding="utf-8") == original
