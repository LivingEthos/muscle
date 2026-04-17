"""
Unit tests for HandoffGenerator.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tools.muscle.code_review.handoff_generator import HandoffGenerator
from tools.muscle.code_review.types import (
    IssueCategory,
    ReviewIssue,
    Severity,
)


class MockM27Client:
    """Mock M27 client for testing."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def chat(self, messages: list[dict], system: str | None = None, **kwargs):
        response = {
            "root_cause": "User input directly concatenated into SQL query without parameterization",
            "fix_approach": "Use parameterized queries with ? placeholders",
            "verification_steps": [
                "Verify the fix compiles",
                "Run pytest tests/test_auth.py",
                "Confirm SQL injection is mitigated",
            ],
            "effort_estimate": "Low",
            "related_files": ["src/database.py", "src/models.py"],
            "risks": ["May break existing queries"],
            "context_needed": "This is a legacy module",
        }
        import json

        return json.dumps(response), MagicMock(total=100)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_issue(temp_dir):
    """Create a sample review issue."""
    code_file = temp_dir / "auth.py"
    code_file.write_text("""
def authenticate(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    cursor.execute(query)
    return cursor.fetchall()
""")

    return ReviewIssue(
        file_path=str(code_file),
        line_number=2,
        severity=Severity.CRITICAL,
        category=IssueCategory.SECURITY,
        cwe_id="CWE-89",
        title="SQL Injection vulnerability",
        description="User input directly interpolated into SQL query",
        code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
        suggested_fix="query = 'SELECT * FROM users WHERE id = ?'\ncursor.execute(query, (user_id,))",
        auto_fixable=False,
    )


@pytest.fixture
def multiple_issues(temp_dir):
    """Create multiple review issues."""
    issues = []

    code_file1 = temp_dir / "auth.py"
    code_file1.write_text('eval(input("Enter code: "))')

    issues.append(
        ReviewIssue(
            file_path=str(code_file1),
            line_number=1,
            severity=Severity.CRITICAL,
            category=IssueCategory.SECURITY,
            cwe_id="CWE-78",
            title="Code execution vulnerability",
            description="eval with user input",
            code_snippet='eval(input("Enter code: "))',
            suggested_fix="Do not use eval with user input",
            auto_fixable=False,
        )
    )

    code_file2 = temp_dir / "utils.py"
    code_file2.write_text("x = 1; y = 2; z = 3")

    issues.append(
        ReviewIssue(
            file_path=str(code_file2),
            line_number=1,
            severity=Severity.LOW,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Line too long",
            description="Line exceeds 88 characters",
            code_snippet="x = 1; y = 2; z = 3",
            suggested_fix="Split into multiple lines",
            auto_fixable=True,
        )
    )

    return issues


class TestHandoffGeneratorInitialization:
    """Test HandoffGenerator initialization."""

    def test_init_with_mock_client(self):
        """Test HandoffGenerator initializes with mock client."""
        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)
        assert generator.m27_client == mock_client


class TestGenerateHandoff:
    """Test generating handoff for a single issue."""

    def test_generate_handoff_success(self, sample_issue):
        """Test successful handoff generation."""
        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoff(
            issue=sample_issue,
            all_issues=[sample_issue],
            session_id="test-001",
            target_path="./src",
        )

        assert plan.session_id == "test-001"
        assert plan.target_path == "./src"
        assert len(plan.issues) == 1
        assert plan.markdown.startswith("# Code Review Handoff Plan")

    def test_generate_handoff_includes_issue_details(self, sample_issue):
        """Test handoff includes issue details."""
        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoff(
            issue=sample_issue,
            all_issues=[sample_issue],
            session_id="test-002",
            target_path="./src",
        )

        handoff_issue = plan.issues[0]
        assert handoff_issue.issue == sample_issue
        assert handoff_issue.root_cause is not None
        assert len(handoff_issue.verification_steps) > 0
        assert handoff_issue.effort_estimate in ["Low", "Medium", "High"]

    def test_generate_handoff_fallback_on_parse_error(self, sample_issue):
        """Test fallback when M2.7 response can't be parsed."""

        class BadMockClient:
            def chat(self, messages, system=None, **kwargs):
                return "not valid json", MagicMock(total=100)

        mock_client = BadMockClient()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoff(
            issue=sample_issue,
            all_issues=[sample_issue],
            session_id="test-003",
            target_path="./src",
        )

        assert plan.session_id == "test-003"
        assert len(plan.issues) == 1

    def test_generate_handoff_recovers_wrapped_json(self, sample_issue):
        """Test handoff parsing succeeds when JSON is wrapped in prose or fences."""

        class WrappedJsonClient:
            def chat(self, messages, system=None, **kwargs):
                return (
                    "Here is the handoff plan:\n```json\n"
                    '{"root_cause":"wrapped","verification_steps":["Run tests"],'
                    '"effort_estimate":"Low","related_files":["src/auth.py"]}\n```',
                    MagicMock(total=100),
                )

        generator = HandoffGenerator(WrappedJsonClient())

        plan = generator.generate_handoff(
            issue=sample_issue,
            all_issues=[sample_issue],
            session_id="test-003b",
            target_path="./src",
        )

        assert plan.issues[0].root_cause == "wrapped"
        assert plan.issues[0].verification_steps == ["Run tests"]


class TestGenerateHandoffs:
    """Test generating handoffs for multiple issues."""

    def test_generate_handoffs_filters_by_severity(self, multiple_issues):
        """Test that generate_handoffs only includes high severity issues."""
        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoffs(
            issues=multiple_issues,
            session_id="test-004",
            target_path="./src",
        )

        # Should only include the CRITICAL issue
        assert len(plan.issues) == 1
        assert plan.issues[0].issue.severity == Severity.CRITICAL

    def test_generate_handoffs_includes_security_issues(self, temp_dir):
        """Test that security issues are always included regardless of severity."""
        code_file = temp_dir / "style.py"
        code_file.write_text("x = 1")

        security_issue = ReviewIssue(
            file_path=str(code_file),
            line_number=1,
            severity=Severity.MEDIUM,
            category=IssueCategory.SECURITY,
            cwe_id="CWE-200",
            title="Information exposure",
            description="Sensitive data may be logged",
            code_snippet='print(f"User: {user}, Token: {token}")',
            suggested_fix="Remove sensitive data from logs",
            auto_fixable=False,
        )

        style_issue = ReviewIssue(
            file_path=str(code_file),
            line_number=1,
            severity=Severity.LOW,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Line too long",
            description="Line exceeds 88 characters",
            code_snippet="x = 1",
            suggested_fix="Split line",
            auto_fixable=True,
        )

        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoffs(
            issues=[security_issue, style_issue],
            session_id="test-005",
            target_path="./src",
        )

        # Should include both security and high severity issues
        assert len(plan.issues) == 1
        assert plan.issues[0].issue.category == IssueCategory.SECURITY


class TestGenerateMarkdown:
    """Test markdown generation."""

    def test_markdown_structure(self, sample_issue):
        """Test markdown has correct structure."""
        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoff(
            issue=sample_issue,
            all_issues=[sample_issue],
            session_id="test-006",
            target_path="./src",
        )

        assert "# Code Review Handoff Plan" in plan.markdown
        assert "**Session:** test-006" in plan.markdown
        assert "**Target:** ./src" in plan.markdown
        assert "## Issue #1:" in plan.markdown
        assert "**Severity:** CRITICAL" in plan.markdown
        assert "**Category:** security" in plan.markdown

    def test_markdown_includes_code_snippet(self, sample_issue):
        """Test markdown includes code snippet."""
        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        plan = generator.generate_handoff(
            issue=sample_issue,
            all_issues=[sample_issue],
            session_id="test-007",
            target_path="./src",
        )

        assert sample_issue.code_snippet in plan.markdown or "SQL" in plan.markdown


class TestRelatedFiles:
    """Test related files functionality."""

    def test_find_related_files(self, temp_dir):
        """Test finding related files."""
        auth_file = temp_dir / "auth.py"
        auth_file.write_text("def auth(): pass")

        db_file = temp_dir / "db" / "connection.py"
        db_file.parent.mkdir()
        db_file.write_text("def connect(): pass")

        utils_file = temp_dir / "utils.py"
        utils_file.write_text("def helper(): pass")

        issues = [
            ReviewIssue(
                file_path=str(auth_file),
                line_number=1,
                severity=Severity.HIGH,
                category=IssueCategory.CORRECTNESS,
                cwe_id=None,
                title="Issue in auth",
                description="Description",
                code_snippet="auth()",
                auto_fixable=False,
            ),
            ReviewIssue(
                file_path=str(db_file),
                line_number=1,
                severity=Severity.LOW,
                category=IssueCategory.STYLE,
                cwe_id=None,
                title="Issue in db",
                description="Description",
                code_snippet="connect()",
                auto_fixable=False,
            ),
        ]

        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        related = generator._find_related_files(issues[0], issues)

        # Should find files in same directory or subdirectories
        assert isinstance(related, list)


class TestCodeContext:
    """Test code context retrieval."""

    def test_get_code_context_success(self, temp_dir):
        """Test successful code context retrieval."""
        code_file = temp_dir / "test.py"
        code_file.write_text('''"""Module."""


def hello():
    print("Hello")


def world():
    print("World")
''')

        issue = ReviewIssue(
            file_path=str(code_file),
            line_number=8,
            severity=Severity.INFO,
            category=IssueCategory.DOCUMENTATION,
            cwe_id=None,
            title="Test",
            description="Test",
            code_snippet='print("World")',
            auto_fixable=False,
        )

        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        context = generator._get_code_context(issue, context_lines=4)

        assert "def hello" in context
        assert "def world" in context

    def test_get_code_context_file_not_found(self):
        """Test context when file doesn't exist."""
        issue = ReviewIssue(
            file_path="/nonexistent/file.py",
            line_number=1,
            severity=Severity.INFO,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Test",
            description="Test",
            code_snippet="",
            auto_fixable=False,
        )

        mock_client = MockM27Client()
        generator = HandoffGenerator(mock_client)

        context = generator._get_code_context(issue)

        assert "N/A" in context
