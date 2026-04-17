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
        findings = ReviewFindings(
            reviews=[
                ReviewFinding(
                    file_path="a.py",
                    line_number=1,
                    severity="low",
                    category="style",
                    title="t",
                    description="d",
                    reasoning="r",
                ),
            ]
        )
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


from unittest.mock import MagicMock, patch

from tools.muscle.m27_client import M27Client, M27StructuredError, _strip_json_fences


class TestStripJsonFences:
    def test_no_fences(self) -> None:
        assert _strip_json_fences('{"a": 1}') == '{"a": 1}'

    def test_json_fence(self) -> None:
        text = '```json\n{"a": 1}\n```'
        assert _strip_json_fences(text) == '{"a": 1}'

    def test_plain_fence(self) -> None:
        text = '```\n{"a": 1}\n```'
        assert _strip_json_fences(text) == '{"a": 1}'

    def test_whitespace_only(self) -> None:
        assert _strip_json_fences("  ") == ""


class TestM27StructuredError:
    def test_is_exception(self) -> None:
        err = M27StructuredError("test")
        assert isinstance(err, Exception)
        assert str(err) == "test"


class TestChatStructured:
    @pytest.fixture()
    def client(self) -> M27Client:
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
            return M27Client(api_key="test-key")

    def test_valid_json_parses(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.return_value = (
                '{"tier": "mechanical", "recommended": "m27", '
                '"confidence": 0.9, "rationale": "simple task"}',
                MagicMock(),
            )
            result = client.chat_structured(
                schema=RouteDecisionSchema,
                messages=[{"role": "user", "content": "Classify: fix typo"}],
            )
        assert isinstance(result, RouteDecisionSchema)
        assert result.tier == "mechanical"

    def test_malformed_json_retries_then_succeeds(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.side_effect = [
                ("not json at all", MagicMock()),
                (
                    '{"tier": "reasoning", "recommended": "m27", '
                    '"confidence": 0.7, "rationale": "ok"}',
                    MagicMock(),
                ),
            ]
            result = client.chat_structured(
                schema=RouteDecisionSchema,
                messages=[{"role": "user", "content": "Classify: refactor"}],
                retries=2,
            )
        assert result.tier == "reasoning"
        assert mock_chat.call_count == 2

    def test_exhausted_retries_raises(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.return_value = ("garbage", MagicMock())
            with pytest.raises(M27StructuredError, match="Failed to produce schema-valid"):
                client.chat_structured(
                    schema=RouteDecisionSchema,
                    messages=[{"role": "user", "content": "test"}],
                    retries=2,
                )
        assert mock_chat.call_count == 3

    def test_schema_validation_failure_retries(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.side_effect = [
                (
                    '{"tier": "bad_tier", "recommended": "m27", '
                    '"confidence": 0.5, "rationale": "ok"}',
                    MagicMock(),
                ),
                (
                    '{"tier": "mechanical", "recommended": "m27", '
                    '"confidence": 0.8, "rationale": "fixed"}',
                    MagicMock(),
                ),
            ]
            result = client.chat_structured(
                schema=RouteDecisionSchema,
                messages=[{"role": "user", "content": "test"}],
                retries=1,
            )
        assert result.tier == "mechanical"
        assert mock_chat.call_count == 2

    def test_fenced_json_stripped(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.return_value = (
                '```json\n{"tier": "mechanical", "recommended": "m27", '
                '"confidence": 0.9, "rationale": "test"}\n```',
                MagicMock(),
            )
            result = client.chat_structured(
                schema=RouteDecisionSchema,
                messages=[{"role": "user", "content": "test"}],
            )
        assert result.tier == "mechanical"
