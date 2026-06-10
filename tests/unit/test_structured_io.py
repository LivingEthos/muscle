"""Tests for structured_io — Phase B.2 Pydantic v2 schemas."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from muscle.m27_client import M27Client, M27StructuredError, _strip_json_fences
from muscle.structured_io import (
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

    def test_negative_line_number_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ReviewFinding(
                file_path="a.py",
                line_number=-1,
                severity="high",
                category="correctness",
                title="t",
                description="d",
                reasoning="r",
            )

    def test_line_number_omitted_defaults_to_none(self) -> None:
        # A line-less finding is represented as None (not fabricated line 1) so
        # downstream emitters can render JSON null.
        f = ReviewFinding(
            file_path="a.py",
            severity="high",
            category="correctness",
            title="t",
            description="d",
            reasoning="r",
        )
        assert f.line_number is None

    def test_line_number_zero_allowed_as_unknown(self) -> None:
        f = ReviewFinding(
            file_path="a.py",
            line_number=0,
            severity="high",
            category="correctness",
            title="t",
            description="d",
            reasoning="r",
        )
        assert f.line_number == 0

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


# Real MiniMax-M3 nested-shape payloads captured from ~/.muscle/cache/cache.db.
# String fields are truncated for readability; the field SHAPE (nested ``issues``,
# ``line``/``lines`` vs ``line_number``, ``cwe`` vs ``cwe_id``, container ``summary``)
# is verbatim. These are the exact shapes that silently dropped findings before the
# ReviewFindings._normalize_nested_reviews salvage existed.

# auth.py: nested ``issues``, scalar ``line``, ``cwe`` alias, dict ``summary``.
_NESTED_AUTH_PAYLOAD = {
    "reviews": [
        {
            "file_path": "auth.py",
            "severity": "CRITICAL",
            "issues": [
                {
                    "id": 1,
                    "title": "Hardcoded production API secret key in source code",
                    "severity": "CRITICAL",
                    "severity_score": 5,
                    "category": "security",
                    "cwe": "CWE-798",
                    "line": 9,
                    "description": "The API_SECRET_KEY is hardcoded directly in source code.",
                    "auto_fixable": True,
                    "suggested_fix": "API_SECRET_KEY = os.environ['API_SECRET_KEY']",
                    "rationale": "Environment variables keep credentials out of version control.",
                },
                {
                    "id": 2,
                    "title": "verify_token() bypasses signature verification",
                    "severity": "CRITICAL",
                    "severity_score": 5,
                    "category": "correctness",
                    "cwe": "CWE-665",
                    "line": 34,
                    "description": "The function body ends mid-statement and never returns.",
                    "auto_fixable": True,
                    "suggested_fix": "def verify_token(token): ...",
                    "rationale": "Adds the missing branch so the comparison gates auth.",
                },
            ],
            "summary": {
                "total_issues": 8,
                "critical": 2,
                "headline_findings": ["Hardcoded live-looking API secret key (CWE-798)."],
            },
        }
    ]
}

# orders.py: nested ``issues`` with ``lines`` LIST instead of a scalar line.
_NESTED_ORDERS_PAYLOAD = {
    "reviews": [
        {
            "file_path": "orders.py",
            "severity": "CRITICAL",
            "issues": [
                {
                    "id": 1,
                    "title": "Path traversal vulnerability in export_receipt (CWE-22)",
                    "lines": [38, 39, 40, 41, 42, 43, 44, 45],
                    "severity": "CRITICAL",
                    "category": "security",
                    "cwe": "CWE-22",
                    "description": "The filename parameter is passed to os.path.join without validation.",
                    "auto_fixable": True,
                    "suggested_fix": "safe_name = os.path.basename(filename)",
                },
                {
                    "id": 2,
                    "title": "Bare except Exception: pass swallows all errors",
                    "lines": [26, 27, 28, 29, 30, 31, 32, 33, 34, 35],
                    "severity": "HIGH",
                    "category": "correctness",
                    "cwe": "CWE-703",
                    "description": "The try block discards every failure mode silently.",
                    "auto_fixable": True,
                    "suggested_fix": "except sqlite3.IntegrityError: ...",
                },
            ],
        }
    ]
}

# utils.py: nested ``issues`` with a container-level ``summary`` (string) to ignore.
_NESTED_UTILS_PAYLOAD = {
    "reviews": [
        {
            "file_path": "utils.py",
            "severity": "HIGH",
            "summary": "utils.py has a path-traversal vulnerability and a TOCTOU race.",
            "issues": [
                {
                    "id": 1,
                    "title": "Path traversal via unsanitized key parameter (CWE-22)",
                    "severity": "HIGH",
                    "category": "security",
                    "cwe": "CWE-22",
                    "line": 23,
                    "description": "The key argument is interpolated directly into a filesystem path.",
                    "auto_fixable": True,
                    "suggested_fix": "validate the key and resolve within cache_dir",
                },
                {
                    "id": 2,
                    "title": "TOCTOU race condition undermines atomicish guarantee (CWE-367)",
                    "severity": "MEDIUM",
                    "category": "correctness",
                    "cwe": "CWE-367",
                    "line": 25,
                    "description": "Classic check-then-act lets concurrent callers clobber writes.",
                    "auto_fixable": True,
                    "suggested_fix": "use O_CREAT | O_EXCL and write-then-rename",
                },
            ],
        }
    ]
}


class TestReviewFindingsNestedSalvage:
    """MiniMax-M3 nested-shape payloads must flatten losslessly (no silent drop)."""

    def test_auth_nested_flattens_with_line_and_cwe(self) -> None:
        findings = ReviewFindings.model_validate(_NESTED_AUTH_PAYLOAD)
        assert len(findings.reviews) == 2
        first = findings.reviews[0]
        # file_path inherited from the container.
        assert first.file_path == "auth.py"
        # ``line`` alias -> line_number; ``cwe`` alias -> cwe_id.
        assert first.line_number == 9
        assert first.cwe_id == "CWE-798"
        assert first.severity == "critical"
        assert first.category == "security"
        assert first.title == "Hardcoded production API secret key in source code"
        assert first.description.startswith("The API_SECRET_KEY is hardcoded")
        assert findings.reviews[1].line_number == 34
        assert findings.reviews[1].cwe_id == "CWE-665"

    def test_orders_nested_flattens_lines_list_to_first_element(self) -> None:
        findings = ReviewFindings.model_validate(_NESTED_ORDERS_PAYLOAD)
        assert len(findings.reviews) == 2
        first = findings.reviews[0]
        assert first.file_path == "orders.py"
        # ``lines`` LIST -> first element.
        assert first.line_number == 38
        assert first.cwe_id == "CWE-22"
        assert first.title.startswith("Path traversal")
        assert findings.reviews[1].line_number == 26

    def test_utils_nested_ignores_container_summary(self) -> None:
        findings = ReviewFindings.model_validate(_NESTED_UTILS_PAYLOAD)
        assert len(findings.reviews) == 2
        first = findings.reviews[0]
        assert first.file_path == "utils.py"
        assert first.line_number == 23
        assert first.cwe_id == "CWE-22"
        # Inner severity wins over container ("HIGH"); second item keeps its own.
        assert first.severity == "high"
        assert findings.reviews[1].severity == "medium"
        # Container "summary" must not leak into any finding field.
        assert all("path-traversal vulnerability and a TOCTOU" not in f.description
                   for f in findings.reviews)

    def test_inner_severity_falls_back_to_container(self) -> None:
        payload = {
            "reviews": [
                {
                    "file_path": "x.py",
                    "severity": "HIGH",
                    "issues": [
                        {"title": "no severity here", "description": "d", "line": 5},
                    ],
                }
            ]
        }
        findings = ReviewFindings.model_validate(payload)
        assert len(findings.reviews) == 1
        # Inner item lacked severity -> inherits the container severity.
        assert findings.reviews[0].severity == "high"
        assert findings.reviews[0].file_path == "x.py"

    def test_findings_alias_list_also_flattens(self) -> None:
        payload = {
            "reviews": [
                {
                    "file_path": "y.py",
                    "severity": "low",
                    "findings": [
                        {"title": "t", "description": "d", "line": 1, "severity": "low"},
                    ],
                }
            ]
        }
        findings = ReviewFindings.model_validate(payload)
        assert len(findings.reviews) == 1
        assert findings.reviews[0].file_path == "y.py"
        assert findings.reviews[0].line_number == 1

    def test_flat_payload_parses_identically_no_regression(self) -> None:
        flat = {
            "reviews": [
                {
                    "file_path": "a.py",
                    "line_number": 7,
                    "severity": "high",
                    "category": "security",
                    "title": "flat finding",
                    "description": "already flat",
                    "cwe_id": "CWE-89",
                },
                {
                    "file_path": "b.py",
                    "line_number": 3,
                    "severity": "low",
                    "category": "style",
                    "title": "second flat",
                    "description": "still flat",
                },
            ]
        }
        findings = ReviewFindings.model_validate(flat)
        assert len(findings.reviews) == 2
        assert findings.reviews[0].cwe_id == "CWE-89"
        assert findings.reviews[0].line_number == 7
        assert findings.reviews[1].file_path == "b.py"

    def test_mixed_flat_and_nested_payload_parses_both(self) -> None:
        mixed = {
            "reviews": [
                {
                    "file_path": "flat.py",
                    "line_number": 1,
                    "severity": "low",
                    "category": "style",
                    "title": "a flat one",
                    "description": "flat desc",
                },
                {
                    "file_path": "nested.py",
                    "severity": "CRITICAL",
                    "issues": [
                        {
                            "title": "nested one",
                            "description": "nested desc",
                            "line": 42,
                            "cwe": "CWE-22",
                            "severity": "CRITICAL",
                        },
                    ],
                },
            ]
        }
        findings = ReviewFindings.model_validate(mixed)
        assert len(findings.reviews) == 2
        assert findings.reviews[0].file_path == "flat.py"
        assert findings.reviews[0].line_number == 1
        assert findings.reviews[1].file_path == "nested.py"
        assert findings.reviews[1].line_number == 42
        assert findings.reviews[1].cwe_id == "CWE-22"

    def test_nested_payload_produces_no_droppable_findings(self) -> None:
        # Every flattened finding must carry a real title AND description, so the
        # downstream empty-finding drop logic (code_reviewer._normalize_finding_fields)
        # never triggers for a genuine nested payload.
        from muscle.code_review.code_reviewer import _normalize_finding_fields

        for payload in (
            _NESTED_AUTH_PAYLOAD,
            _NESTED_ORDERS_PAYLOAD,
            _NESTED_UTILS_PAYLOAD,
        ):
            findings = ReviewFindings.model_validate(payload)
            assert findings.reviews, "nested payload must yield findings"
            for f in findings.reviews:
                result = _normalize_finding_fields(
                    title=f.title,
                    description=f.description,
                    line_number=f.line_number,
                )
                assert result is not None, "genuine finding must not be dropped"

    def test_schema_hint_suffix_present_and_flat_directive(self) -> None:
        suffix = ReviewFindings.schema_hint_suffix
        assert isinstance(suffix, str) and suffix
        assert "FLAT" in suffix
        assert "issues" in suffix or "nest" in suffix


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
    def client(self, tmp_path) -> M27Client:
        with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
            return M27Client(api_key="test-key", cache_db_path=tmp_path / "cache.db")

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

    def test_review_findings_schema_appends_flat_hint(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.return_value = ('{"reviews": [], "summary": {}}', MagicMock())
            client.chat_structured(
                schema=ReviewFindings,
                messages=[{"role": "user", "content": "review"}],
            )
        system_arg = mock_chat.call_args.kwargs["system"]
        assert ReviewFindings.schema_hint_suffix in system_arg

    def test_other_schema_omits_flat_hint(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.return_value = (
                '{"tier": "mechanical", "recommended": "m27", '
                '"confidence": 0.9, "rationale": "x"}',
                MagicMock(),
            )
            client.chat_structured(
                schema=RouteDecisionSchema,
                messages=[{"role": "user", "content": "classify"}],
            )
        system_arg = mock_chat.call_args.kwargs["system"]
        assert ReviewFindings.schema_hint_suffix not in system_arg

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

    def test_thinking_tags_stripped_before_json_parse(self, client: M27Client) -> None:
        with patch.object(client, "chat") as mock_chat:
            mock_chat.return_value = (
                '<think>internal reasoning</think>{"tier": "mechanical", '
                '"recommended": "m27", "confidence": 0.9, "rationale": "test"}',
                MagicMock(),
            )
            result = client.chat_structured(
                schema=RouteDecisionSchema,
                messages=[{"role": "user", "content": "test"}],
            )
        assert result.tier == "mechanical"
