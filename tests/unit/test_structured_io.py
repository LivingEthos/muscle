"""Tests for structured_io — Phase B.2 Pydantic v2 schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tools.muscle.structured_io import (
    FixCandidate,
    PatternScanResult,
    ReviewFinding,
    ReviewFindings,
    RouteDecisionSchema,
    VerificationReport,
)


class TestReviewFinding:
    def test_valid_finding(self) -> None:
        f = ReviewFinding(
            file_path="src/main.py",
            line_number=42,
            severity="high",
            category="correctness",
            title="Null dereference",
            description="Variable may be None",
            reasoning="Path analysis shows branch where x is unchecked",
        )
        assert f.file_path == "src/main.py"
        assert f.line_number == 42
        assert f.auto_fixable is False
        assert f.suggested_fix is None
        assert f.code_snippet == ""

    def test_invalid_severity_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewFinding(
                file_path="a.py",
                line_number=1,
                severity="catastrophic",
                category="correctness",
                title="t",
                description="d",
                reasoning="r",
            )

    def test_invalid_category_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewFinding(
                file_path="a.py",
                line_number=1,
                severity="high",
                category="quantum",
                title="t",
                description="d",
                reasoning="r",
            )

    def test_line_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            ReviewFinding(
                file_path="a.py",
                line_number=0,
                severity="high",
                category="correctness",
                title="t",
                description="d",
                reasoning="r",
            )

    def test_optional_fields_default(self) -> None:
        f = ReviewFinding(
            file_path="a.py",
            line_number=1,
            severity="info",
            category="style",
            title="t",
            description="d",
            reasoning="r",
            suggested_fix="fix it",
        )
        assert f.suggested_fix == "fix it"


class TestReviewFindings:
    def test_wraps_list(self) -> None:
        findings = ReviewFindings(reviews=[
            ReviewFinding(
                file_path="a.py",
                line_number=1,
                severity="low",
                category="style",
                title="t",
                description="d",
                reasoning="r",
            ),
        ])
        assert len(findings.reviews) == 1

    def test_empty_reviews_valid(self) -> None:
        findings = ReviewFindings(reviews=[])
        assert len(findings.reviews) == 0


class TestFixCandidate:
    def test_valid(self) -> None:
        fc = FixCandidate(
            file_path="a.py",
            original_snippet="old",
            fixed_snippet="new",
            rationale="fix bug",
        )
        assert fc.file_path == "a.py"


class TestPatternScanResult:
    def test_valid(self) -> None:
        ps = PatternScanResult(
            patterns_found=["god_class", "long_method"],
            occurrences_by_pattern={"god_class": 1, "long_method": 3},
        )
        assert ps.occurrences_by_pattern["long_method"] == 3


class TestVerificationReport:
    def test_passed(self) -> None:
        vr = VerificationReport(passed=True, tests_run=10, tests_failed=0)
        assert vr.passed is True
        assert vr.lint_passed is None

    def test_failed_with_warnings(self) -> None:
        vr = VerificationReport(
            passed=False,
            tests_run=5,
            tests_failed=2,
            warnings=["flake8 error", "mypy error"],
        )
        assert vr.passed is False
        assert len(vr.warnings) == 2

    def test_defaults(self) -> None:
        vr = VerificationReport(passed=True)
        assert vr.tests_run == 0
        assert vr.tests_failed == 0
        assert vr.lint_passed is None
        assert vr.type_check_passed is None
        assert vr.warnings == []


class TestRouteDecisionSchema:
    def test_valid_mechanical(self) -> None:
        rd = RouteDecisionSchema(
            tier="mechanical",
            recommended="m27",
            confidence=0.9,
            rationale="simple test task",
        )
        assert rd.tier == "mechanical"

    def test_confidence_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RouteDecisionSchema(
                tier="mechanical",
                recommended="m27",
                confidence=1.5,
                rationale="bad",
            )

    def test_invalid_tier_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RouteDecisionSchema(
                tier="impossible",
                recommended="m27",
                confidence=0.8,
                rationale="bad",
            )
