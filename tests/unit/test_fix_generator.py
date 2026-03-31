"""
Unit tests for FixGenerator.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from tools.scle.code_review.fix_generator import FixGenerator, FixResult
from tools.scle.code_review.types import ReviewIssue, Severity, IssueCategory


class MockM27Client:
    """Mock M27 client for testing."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def chat(self, messages: list[dict], system: str | None = None, **kwargs):
        return '{"file_path": "test.py", "fixed_code": "print(1)"}', MagicMock(total=100)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def python_file(temp_dir):
    """Create a Python file with issues for testing."""
    content = '''"""Test module."""


def unsafe_function(user_input):
    result = eval(user_input)
    return result


password = "secret123"


def example():
    print("Hello")
'''
    path = temp_dir / "test.py"
    path.write_text(content)
    return path


@pytest.fixture
def review_issue_sql_injection(python_file):
    """Create a review issue for SQL injection."""
    return ReviewIssue(
        file_path=str(python_file),
        line_number=6,
        severity=Severity.HIGH,
        category=IssueCategory.SECURITY,
        cwe_id="CWE-89",
        title="SQL Injection vulnerability",
        description="User input directly interpolated into SQL query",
        code_snippet='result = eval(user_input)',
        suggested_fix="result = ast.literal_eval(user_input)",
        auto_fixable=True,
    )


@pytest.fixture
def review_issue_hardcoded_secret(python_file):
    """Create a review issue for hardcoded secret."""
    return ReviewIssue(
        file_path=str(python_file),
        line_number=10,
        severity=Severity.CRITICAL,
        category=IssueCategory.SECURITY,
        cwe_id="CWE-798",
        title="Hardcoded secret",
        description="Password or API key hardcoded in source code",
        code_snippet='password = "secret123"',
        suggested_fix="import os\npassword = os.environ.get('PASSWORD')",
        auto_fixable=False,
    )


class TestFixGeneratorInitialization:
    """Test FixGenerator initialization."""

    def test_init_with_mock_client(self):
        """Test FixGenerator initializes with mock client."""
        mock_client = MockM27Client(api_key="test-key")
        generator = FixGenerator(mock_client)
        assert generator.m27_client == mock_client
        assert generator.verify_compile is True

    def test_init_verify_compile_false(self):
        """Test FixGenerator with verify_compile=False."""
        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=False)
        assert generator.verify_compile is False


class TestApplyFixFromSuggestion:
    """Test applying fixes from suggestions."""

    def test_apply_fix_success(self, review_issue_sql_injection):
        """Test successful fix application."""
        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=False)

        result = generator.apply_fix_from_suggestion(review_issue_sql_injection)

        assert result.success is True
        assert result.file_path == review_issue_sql_injection.file_path
        assert result.applied is True

    def test_apply_fix_no_suggested_fix(self, python_file):
        """Test fix fails when no suggested fix available."""
        issue = ReviewIssue(
            file_path=str(python_file),
            line_number=10,
            severity=Severity.INFO,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Style issue",
            description="Minor style issue",
            code_snippet="x=1",
            suggested_fix=None,
            auto_fixable=False,
        )

        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=False)

        result = generator.apply_fix_from_suggestion(issue)

        assert result.success is False
        assert "No suggested fix" in result.error

    def test_apply_fix_file_not_found(self):
        """Test fix fails when file doesn't exist."""
        issue = ReviewIssue(
            file_path="/nonexistent/path/file.py",
            line_number=10,
            severity=Severity.HIGH,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="Error",
            description="Error description",
            code_snippet="bad code",
            suggested_fix="good code",
            auto_fixable=True,
        )

        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=False)

        result = generator.apply_fix_from_suggestion(issue)

        assert result.success is False
        assert "File not found" in result.error

    def test_apply_fix_line_out_of_range(self, python_file):
        """Test fix fails when line number is out of range."""
        issue = ReviewIssue(
            file_path=str(python_file),
            line_number=9999,
            severity=Severity.HIGH,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="Error",
            description="Error description",
            code_snippet="bad code",
            suggested_fix="good code",
            auto_fixable=True,
        )

        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=False)

        result = generator.apply_fix_from_suggestion(issue)

        assert result.success is False
        assert "out of range" in result.error


class TestRollbackFix:
    """Test rollback functionality."""

    def test_rollback_success(self, python_file):
        """Test successful rollback."""
        original_content = python_file.read_text()

        fix_result = FixResult(
            success=True,
            file_path=str(python_file),
            original_content=original_content,
            fixed_content="# Modified content",
            applied=True,
            verified=False,
        )

        mock_client = MockM27Client()
        generator = FixGenerator(mock_client)

        result = generator.rollback_fix(fix_result)

        assert result is True
        assert python_file.read_text() == original_content

    def test_rollback_empty_original(self):
        """Test rollback fails with empty original content."""
        fix_result = FixResult(
            success=False,
            file_path="/fake/path.py",
            original_content="",
            fixed_content="modified",
            applied=False,
            verified=False,
        )

        mock_client = MockM27Client()
        generator = FixGenerator(mock_client)

        result = generator.rollback_fix(fix_result)

        assert result is False


class TestVerifyFix:
    """Test fix verification."""

    def test_verify_fix_skips_when_disabled(self):
        """Test verification is skipped when disabled."""
        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=False)

        result = generator.verify_fix("/fake/path.py", "python")

        assert result is True

    def test_verify_fix_placeholder(self):
        """Test verify_fix returns True as placeholder."""
        mock_client = MockM27Client()
        generator = FixGenerator(mock_client, verify_compile=True)

        result = generator.verify_fix("/fake/path.py", "python")

        assert result is True


class TestFixResultDataclass:
    """Test FixResult dataclass."""

    def test_fix_result_success(self):
        """Test FixResult with successful fix."""
        result = FixResult(
            success=True,
            file_path="test.py",
            original_content="old",
            fixed_content="new",
            applied=True,
            verified=True,
        )

        assert result.success is True
        assert result.file_path == "test.py"
        assert result.original_content == "old"
        assert result.fixed_content == "new"
        assert result.applied is True
        assert result.verified is True
        assert result.error is None

    def test_fix_result_failure(self):
        """Test FixResult with failed fix."""
        result = FixResult(
            success=False,
            file_path="test.py",
            original_content="old",
            fixed_content="new",
            applied=False,
            verified=False,
            error="File not found",
        )

        assert result.success is False
        assert result.error == "File not found"
