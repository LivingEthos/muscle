"""Regression tests for strict fix verification."""

from __future__ import annotations

from pathlib import Path

from muscle.code_review.types import IssueCategory, ReviewIssue, Severity
from muscle.code_review.verification_loop import VerificationLoop
from muscle.m27_client import TokenUsage


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
    # The verifier usage split is threaded onto the result alongside the total.
    assert result.tokens_spent == 3
    assert result.input_tokens_spent == 1
    assert result.output_tokens_spent == 2


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


def test_repeated_rule_violation_escalates_for_opus_host(tmp_path, monkeypatch):
    import sqlite3

    from muscle.project_memory import ProjectMemory

    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    pm = ProjectMemory(str(tmp_path))
    pm._init_db()

    target = tmp_path / "f.py"
    target.write_text("original\n")

    loop = VerificationLoop(
        m27_client=object(),  # type: ignore[arg-type]
        verify_compile=False,
        verify_linter=False,
        verify_tests=False,
    )
    loop.configure_runtime(project_path=str(tmp_path), session_id="s1")
    monkeypatch.setattr(loop, "_m27_verify", lambda issue, fixed: ("NEEDS_WORK: nope", None))
    monkeypatch.setattr(loop, "_m27_analyze_failure", lambda issue, text: "analysis")

    issue = ReviewIssue(
        file_path=str(target),
        line_number=1,
        severity=Severity.HIGH,
        category=IssueCategory.CORRECTNESS,
        cwe_id="CWE-89",
        title="SQL injection",
        description="d",
        code_snippet="c",
    )
    loop.verify_fix(issue, "fixed-1\n")
    loop.verify_fix(issue, "fixed-2\n")

    db = tmp_path / ".muscle" / "project_memory.db"
    with sqlite3.connect(db) as conn:
        reasons = [r[0] for r in conn.execute("SELECT reason FROM escalations").fetchall()]
    assert "repeated_rule_violation" in reasons


def test_repeated_rule_violation_absent_for_default_host(tmp_path, monkeypatch):
    import sqlite3

    from muscle.project_memory import ProjectMemory

    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    pm = ProjectMemory(str(tmp_path))
    pm._init_db()

    target = tmp_path / "f.py"
    target.write_text("original\n")

    loop = VerificationLoop(
        m27_client=object(),  # type: ignore[arg-type]
        verify_compile=False,
        verify_linter=False,
        verify_tests=False,
    )
    loop.configure_runtime(project_path=str(tmp_path), session_id="s1")
    monkeypatch.setattr(loop, "_m27_verify", lambda issue, fixed: ("NEEDS_WORK: nope", None))
    monkeypatch.setattr(loop, "_m27_analyze_failure", lambda issue, text: "analysis")

    issue = ReviewIssue(
        file_path=str(target),
        line_number=1,
        severity=Severity.HIGH,
        category=IssueCategory.CORRECTNESS,
        cwe_id="CWE-89",
        title="SQL injection",
        description="d",
        code_snippet="c",
    )
    loop.verify_fix(issue, "fixed-1\n")
    loop.verify_fix(issue, "fixed-2\n")

    db = tmp_path / ".muscle" / "project_memory.db"
    with sqlite3.connect(db) as conn:
        reasons = [r[0] for r in conn.execute("SELECT reason FROM escalations").fetchall()]
    assert "repeated_rule_violation" not in reasons
    assert "verification_failure" in reasons
