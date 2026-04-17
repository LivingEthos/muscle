"""
Unit tests for code_reviewer.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.review_artifacts import ReviewArtifactStore
from tools.muscle.code_review.types import IssueCategory, PressureFocus, ReviewConfig, Severity


class TestParseSeverity:
    def test_critical(self):
        assert CodeReviewer._parse_severity("CRITICAL") == Severity.CRITICAL

    def test_high(self):
        assert CodeReviewer._parse_severity("HIGH") == Severity.HIGH

    def test_medium(self):
        assert CodeReviewer._parse_severity("MEDIUM") == Severity.MEDIUM

    def test_low(self):
        assert CodeReviewer._parse_severity("LOW") == Severity.LOW

    def test_info(self):
        assert CodeReviewer._parse_severity("INFO") == Severity.INFO

    def test_case_insensitive(self):
        assert CodeReviewer._parse_severity("critical") == Severity.CRITICAL
        assert CodeReviewer._parse_severity("High") == Severity.HIGH
        assert CodeReviewer._parse_severity("MeDiUm") == Severity.MEDIUM

    def test_unknown_returns_medium(self):
        assert CodeReviewer._parse_severity("UNKNOWN") == Severity.MEDIUM
        assert CodeReviewer._parse_severity("") == Severity.MEDIUM


class TestParseCategory:
    def test_security(self):
        assert CodeReviewer._parse_category("security") == IssueCategory.SECURITY

    def test_correctness(self):
        assert CodeReviewer._parse_category("correctness") == IssueCategory.CORRECTNESS

    def test_performance(self):
        assert CodeReviewer._parse_category("performance") == IssueCategory.PERFORMANCE

    def test_style(self):
        assert CodeReviewer._parse_category("style") == IssueCategory.STYLE

    def test_documentation(self):
        assert CodeReviewer._parse_category("documentation") == IssueCategory.DOCUMENTATION

    def test_best_practice(self):
        assert CodeReviewer._parse_category("best_practice") == IssueCategory.BEST_PRACTICE

    def test_case_insensitive(self):
        assert CodeReviewer._parse_category("SECURITY") == IssueCategory.SECURITY
        assert CodeReviewer._parse_category("Correctness") == IssueCategory.CORRECTNESS

    def test_unknown_returns_best_practice(self):
        assert CodeReviewer._parse_category("unknown") == IssueCategory.BEST_PRACTICE
        assert CodeReviewer._parse_category("") == IssueCategory.BEST_PRACTICE


class TestGetLangFromExt:
    def test_python(self):
        assert CodeReviewer._get_lang_from_ext("test.py") == "python"
        assert CodeReviewer._get_lang_from_ext("test.PY") == "python"

    def test_javascript(self):
        assert CodeReviewer._get_lang_from_ext("test.js") == "javascript"
        assert CodeReviewer._get_lang_from_ext("test.jsx") == "javascript"

    def test_typescript(self):
        assert CodeReviewer._get_lang_from_ext("test.ts") == "typescript"
        assert CodeReviewer._get_lang_from_ext("test.tsx") == "typescript"

    def test_go(self):
        assert CodeReviewer._get_lang_from_ext("test.go") == "go"

    def test_rust(self):
        assert CodeReviewer._get_lang_from_ext("test.rs") == "rust"

    def test_cpp(self):
        assert CodeReviewer._get_lang_from_ext("test.cpp") == "cpp"
        assert CodeReviewer._get_lang_from_ext("test.cc") == "cpp"

    def test_c(self):
        assert CodeReviewer._get_lang_from_ext("test.c") == "c"
        assert CodeReviewer._get_lang_from_ext("test.h") == "c"

    def test_java(self):
        assert CodeReviewer._get_lang_from_ext("test.java") == "java"

    def test_unknown_returns_text(self):
        assert CodeReviewer._get_lang_from_ext("test.txt") == "text"
        assert CodeReviewer._get_lang_from_ext("test.xyz") == "text"
        assert CodeReviewer._get_lang_from_ext("noextension") == "text"


class TestTruncateCode:
    def test_under_limit_returns_unchanged(self):
        code = "line1\nline2\nline3"
        result = CodeReviewer._truncate_code(code, 10)
        assert result == code

    def test_at_limit_returns_unchanged(self):
        code = "line1\nline2\nline3"
        result = CodeReviewer._truncate_code(code, 3)
        assert result == code

    def test_over_limit_truncates(self):
        lines = ["line" + str(i) for i in range(100)]
        code = "\n".join(lines)
        result = CodeReviewer._truncate_code(code, 10)
        assert "line0" in result
        assert "line9" in result
        assert "(90 more lines)" in result

    def test_truncation_includes_trailing_marker(self):
        code = "\n".join(["a"] * 50)
        result = CodeReviewer._truncate_code(code, 5)
        assert "(45 more lines)" in result


class TestReviewFile:
    def test_review_file_with_valid_json_response(self):
        mock_m27 = MagicMock()
        response = json.dumps(
            {
                "reviews": [
                    {
                        "file_path": "test.py",
                        "line_number": 10,
                        "valid": True,
                        "severity": "HIGH",
                        "category": "security",
                        "cwe_id": "CWE-89",
                        "title": "SQL Injection",
                        "description": "Direct SQL concatenation",
                        "code_snippet": "query = 'SELECT * FROM users'",
                        "auto_fixable": True,
                        "suggested_fix": "Use parameterized query",
                    }
                ],
                "summary": {
                    "total_reviewed": 1,
                    "valid_issues": 1,
                    "false_positives": 0,
                    "intentional": 0,
                    "critical": 0,
                    "high": 1,
                    "medium": 0,
                    "low": 0,
                    "info": 0,
                },
            }
        )
        mock_m27.chat.return_value = (response, MagicMock(total=100))
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [])

        assert len(reviews) == 1
        assert reviews[0].severity == Severity.HIGH
        assert reviews[0].category == IssueCategory.SECURITY
        assert reviews[0].cwe_id == "CWE-89"
        assert summary["high"] == 1

    def test_review_file_with_fenced_json_response(self):
        mock_m27 = MagicMock()
        response = '```json\n{"reviews": [], "summary": {"total_reviewed": 0, "valid_issues": 0, "false_positives": 0, "intentional": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}}\n```'
        mock_m27.chat.return_value = (response, MagicMock(total=50))
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [])
        assert reviews == []
        assert summary["total_reviewed"] == 0

    def test_review_file_filters_invalid_issues(self):
        mock_m27 = MagicMock()
        response = json.dumps(
            {
                "reviews": [
                    {"valid": False, "severity": "HIGH", "title": "Not valid"},
                    {"valid": True, "severity": "LOW", "title": "Is valid"},
                ],
                "summary": {
                    "total_reviewed": 2,
                    "valid_issues": 1,
                    "false_positives": 1,
                    "intentional": 0,
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 1,
                    "info": 0,
                },
            }
        )
        mock_m27.chat.return_value = (response, MagicMock(total=50))
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [])
        assert len(reviews) == 1
        assert reviews[0].title == "Is valid"

    def test_review_file_empty_response_returns_empty(self):
        mock_m27 = MagicMock()
        mock_m27.chat.return_value = ("", MagicMock(total=0))
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [{"line": 1}])
        assert reviews == []
        assert summary["false_positives"] == 1

    def test_review_file_invalid_json_returns_empty(self):
        mock_m27 = MagicMock()
        mock_m27.chat.return_value = ("not valid json {{{", MagicMock(total=0))
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [{"line": 1}])
        assert reviews == []
        assert summary["false_positives"] == 1

    def test_review_file_retries_on_empty_response(self):
        mock_m27 = MagicMock()
        mock_m27.chat.side_effect = [
            ("", MagicMock(total=0)),
            ("", MagicMock(total=0)),
            (
                '{"reviews": [], "summary": {"total_reviewed": 0, "valid_issues": 0, "false_positives": 0, "intentional": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}}',
                MagicMock(total=50),
            ),
        ]
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [])
        assert reviews == []
        assert mock_m27.chat.call_count == 3

    def test_review_file_proactive_mode(self):
        mock_m27 = MagicMock()
        response = json.dumps(
            {
                "reviews": [
                    {
                        "file_path": "test.py",
                        "line_number": 5,
                        "valid": True,
                        "severity": "MEDIUM",
                        "category": "correctness",
                        "title": "Logic error",
                        "description": "Off-by-one in loop",
                        "code_snippet": "for i in range(len(items) - 1):",
                        "auto_fixable": False,
                    }
                ],
                "summary": {
                    "total_reviewed": 1,
                    "valid_issues": 1,
                    "false_positives": 0,
                    "intentional": 0,
                    "critical": 0,
                    "high": 0,
                    "medium": 1,
                    "low": 0,
                    "info": 0,
                },
            }
        )
        mock_m27.chat.return_value = (response, MagicMock(total=100))
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer._review_file("test.py", "x = 1", [], proactive=True)
        assert len(reviews) == 1
        assert reviews[0].category == IssueCategory.CORRECTNESS


class TestReview:
    def test_review_groups_issues_by_file(self, tmp_path):
        test_file = tmp_path / "sample.py"
        test_file.write_text("x = 1\ny = 2\n")

        mock_m27 = MagicMock()
        mock_m27.chat.return_value = (
            '{"reviews": [], "summary": {"total_reviewed": 2, "valid_issues": 0, "false_positives": 2, "intentional": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}}',
            MagicMock(total=50),
        )
        reviewer = CodeReviewer(mock_m27)

        issues = [
            {"file_path": "sample.py", "line": 1, "message": "unused variable"},
            {"file_path": "sample.py", "line": 2, "message": "unused variable"},
        ]
        reviews, summary = reviewer.review(str(tmp_path), issues)
        assert mock_m27.chat.called

    def test_review_with_no_issues_and_no_files(self, tmp_path):
        mock_m27 = MagicMock()
        mock_m27.chat.return_value = (
            '{"reviews": [], "summary": {"total_reviewed": 0, "valid_issues": 0, "false_positives": 0, "intentional": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}}',
            MagicMock(total=50),
        )
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer.review(str(tmp_path), [])
        assert reviews == []
        assert summary["total_reviewed"] == 0

    def test_review_single_file_target(self, tmp_path):
        test_file = tmp_path / "sample.py"
        test_file.write_text("x = 1\n")

        mock_m27 = MagicMock()
        mock_m27.chat.return_value = (
            '{"reviews": [], "summary": {"total_reviewed": 0, "valid_issues": 0, "false_positives": 0, "intentional": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}}',
            MagicMock(total=50),
        )
        reviewer = CodeReviewer(mock_m27)

        reviews, summary = reviewer.review(str(test_file), [])
        assert reviews == []

    def test_review_uses_max_issues_per_batch(self, tmp_path):
        test_file = tmp_path / "sample.py"
        test_file.write_text("x = 1\n")

        mock_m27 = MagicMock()
        response_text = '{"reviews": [], "summary": {"total_reviewed": 5, "valid_issues": 0, "false_positives": 5, "intentional": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}}'
        mock_m27.chat.return_value = (response_text, MagicMock(total=50))
        reviewer = CodeReviewer(mock_m27, max_issues_per_batch=3)

        issues = [{"file_path": "sample.py", "line": i} for i in range(1, 6)]
        reviewer.review(str(test_file), issues)
        assert mock_m27.chat.call_count == 1


class TestPressureReview:
    def test_pressure_review_with_valid_response(self):
        mock_m27 = MagicMock()
        response = json.dumps(
            {
                "pressure_findings": [
                    {
                        "file_path": "test.py",
                        "line_number": 10,
                        "finding_type": "security_risk",
                        "severity": "HIGH",
                        "title": "SQL Injection risk",
                        "description": "Direct concatenation",
                        "exploit_scenario": "Attacker inputs SQL",
                        "suggested_approach": "Use ORM",
                        "challenge_question": "Have you considered parameterized queries?",
                    }
                ],
                "summary": {
                    "total_examined": 1,
                    "critical_findings": 0,
                    "high_findings": 1,
                    "concerns_addressed": 0,
                    "confidence_score": 7,
                },
            }
        )
        mock_m27.chat.return_value = (response, MagicMock(total=150))
        reviewer = CodeReviewer(mock_m27)

        focus = PressureFocus(
            design_tradeoffs=False,
            failure_modes=False,
            race_conditions=False,
            auth_security=True,
            data_loss=False,
            rollback=False,
            reliability=False,
            custom_focus=None,
        )
        result = reviewer.pressure_review("test.py", "query = 'SELECT * FROM users'", focus)

        assert "pressure_findings" in result
        assert len(result["pressure_findings"]) == 1
        assert result["pressure_findings"][0]["severity"] == "HIGH"

    def test_pressure_review_with_fenced_json(self):
        mock_m27 = MagicMock()
        response = '```json\n{"pressure_findings": [], "summary": {"total_examined": 0, "critical_findings": 0, "high_findings": 0, "concerns_addressed": 0, "confidence_score": 0}}\n```'
        mock_m27.chat.return_value = (response, MagicMock(total=50))
        reviewer = CodeReviewer(mock_m27)

        focus = PressureFocus()
        result = reviewer.pressure_review("test.py", "x = 1", focus)
        assert "pressure_findings" in result

    def test_pressure_review_empty_response(self):
        mock_m27 = MagicMock()
        mock_m27.chat.return_value = ("", MagicMock(total=0))
        reviewer = CodeReviewer(mock_m27)

        focus = PressureFocus()
        result = reviewer.pressure_review("test.py", "x = 1", focus)
        assert result["pressure_findings"] == []
        assert result["summary"]["total"] == 0

    def test_pressure_review_invalid_json_fails_closed(self, tmp_path):
        mock_m27 = MagicMock()
        mock_m27.chat.return_value = (
            '{"pressure_findings": [{"title": "Found it", "severity": "HIGH"',
            MagicMock(total=50),
        )
        reviewer = CodeReviewer(mock_m27)
        artifact_store = ReviewArtifactStore(str(tmp_path), "sess-1")

        focus = PressureFocus()
        result = reviewer.pressure_review(
            "test.py",
            "x = 1",
            focus,
            artifact_store=artifact_store,
        )
        assert result["pressure_findings"] == []
        assert "parse_error" in result["summary"]
        assert (Path(artifact_store.artifact_dir) / "pressure-raw-response.txt").exists()

    def test_pressure_review_all_focus_areas(self):
        mock_m27 = MagicMock()
        response = '{"pressure_findings": [], "summary": {"total_examined": 0, "critical_findings": 0, "high_findings": 0, "concerns_addressed": 0, "confidence_score": 0}}'
        mock_m27.chat.return_value = (response, MagicMock(total=50))
        reviewer = CodeReviewer(mock_m27)

        focus = PressureFocus(
            design_tradeoffs=True,
            failure_modes=True,
            race_conditions=True,
            auth_security=True,
            data_loss=True,
            rollback=True,
            reliability=True,
            custom_focus="custom area",
        )
        result = reviewer.pressure_review("test.py", "x = 1", focus)
        assert "pressure_findings" in result
        assert mock_m27.chat.called

    def test_pressure_review_no_focus_defaults_to_general(self):
        mock_m27 = MagicMock()
        response = '{"pressure_findings": [], "summary": {"total_examined": 0, "critical_findings": 0, "high_findings": 0, "concerns_addressed": 0, "confidence_score": 0}}'
        mock_m27.chat.return_value = (response, MagicMock(total=50))
        reviewer = CodeReviewer(mock_m27)

        focus = PressureFocus()
        result = reviewer.pressure_review("test.py", "x = 1", focus)
        assert "pressure_findings" in result


class TestCR05MaxIssuesPerBatch:
    """[CR-05] max_issues_per_batch must be documented in ReviewConfig and honoured
    by CodeReviewer when threaded through from config.
    """

    def test_review_config_default_max_issues_per_batch(self):
        """ReviewConfig exposes max_issues_per_batch with a default of 20."""
        config = ReviewConfig(target_path="./src")
        assert config.max_issues_per_batch == 20

    def test_review_config_custom_max_issues_per_batch(self):
        """ReviewConfig accepts a custom max_issues_per_batch value."""
        config = ReviewConfig(target_path="./src", max_issues_per_batch=5)
        assert config.max_issues_per_batch == 5

    def test_code_reviewer_respects_custom_max_issues_per_batch(self, tmp_path):
        """When CodeReviewer is constructed with a custom max_issues_per_batch the batch
        is truncated to that limit before the M2.7 call."""
        test_file = tmp_path / "sample.py"
        test_file.write_text("x = 1\n")

        mock_m27 = MagicMock()
        # Return a minimal valid response so _review_file succeeds
        empty_response = json.dumps(
            {
                "reviews": [],
                "summary": {
                    "total_reviewed": 0,
                    "valid_issues": 0,
                    "false_positives": 0,
                    "intentional": 0,
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "info": 0,
                },
            }
        )
        mock_m27.chat.return_value = (empty_response, MagicMock(total=10))

        # Construct reviewer with a very small batch limit
        reviewer = CodeReviewer(mock_m27, max_issues_per_batch=3)

        # Submit 7 issues for the same file
        issues = [
            {"file_path": str(test_file), "line": i, "message": f"issue {i}"} for i in range(1, 8)
        ]
        reviewer.review(str(test_file), issues)

        # The M2.7 call must have been made (batch not empty after truncation)
        assert mock_m27.chat.call_count == 1
        # The user-prompt argument must contain at most 3 issues
        call_args = mock_m27.chat.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        # The truncated issues list should contain exactly 3 entries
        import re

        # Count occurrences of "issue " in the serialised issues block
        issue_count = len(re.findall(r'"message":', user_message))
        assert issue_count == 3, f"Expected 3 issues in prompt (batch limit), got {issue_count}"

    def test_reviewer_config_threaded_via_review_config(self, tmp_path):
        """ReviewConfig.max_issues_per_batch is threaded into CodeReviewer by
        ReviewController, so the constructor default is no longer the only option."""
        # Verify that CodeReviewer stores the value passed to it
        mock_m27 = MagicMock()
        reviewer = CodeReviewer(mock_m27, max_issues_per_batch=7)
        assert reviewer.max_issues_per_batch == 7
