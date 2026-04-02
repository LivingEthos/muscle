"""
Shared fixtures for integration tests.

Provides realistic mocked M27Client, sample code files,
and temporary project directories with proper structure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.muscle.code_review.types import (
    IssueCategory,
    ReviewIssue,
    ReviewResult,
    Severity,
)
from tools.muscle.m27_client import TokenUsage

# ---------------------------------------------------------------------------
# Realistic M27 mock that returns structured JSON like the real model
# ---------------------------------------------------------------------------

REVIEW_JSON_RESPONSE = json.dumps(
    {
        "findings": [
            {
                "file_path": "src/api.py",
                "line_number": 12,
                "severity": "CRITICAL",
                "category": "security",
                "cwe_id": "CWE-327",
                "title": "Insecure MD5 password hashing",
                "description": "MD5 is cryptographically broken. Use bcrypt or argon2.",
                "code_snippet": "hashlib.md5(password.encode()).hexdigest()",
                "suggested_fix": "Use bcrypt.hashpw(password.encode(), bcrypt.gensalt())",
                "auto_fixable": False,
            },
            {
                "file_path": "src/api.py",
                "line_number": 17,
                "severity": "CRITICAL",
                "category": "security",
                "cwe_id": "CWE-502",
                "title": "Unsafe deserialization",
                "description": "Deserializing untrusted data allows arbitrary code execution.",
                "code_snippet": "loads(bytes.fromhex(token))",
                "suggested_fix": "Use json.loads() or a safe serialization format.",
                "auto_fixable": True,
            },
            {
                "file_path": "src/utils.py",
                "line_number": 11,
                "severity": "HIGH",
                "category": "security",
                "cwe_id": "CWE-78",
                "title": "Command injection via shell=True",
                "description": "subprocess.run with shell=True and unsanitized input.",
                "code_snippet": "subprocess.run(cmd, shell=True, ...)",
                "suggested_fix": "Use subprocess.run(shlex.split(cmd), shell=False)",
                "auto_fixable": True,
            },
        ],
        "summary": "Found 3 issues: 2 critical, 1 high. Focus on security hardening.",
    }
)

FIX_JSON_RESPONSE = json.dumps(
    {
        "file_path": "src/api.py",
        "original_lines": "17-18",
        "fixed_code": "def verify_token(token: str) -> dict:\n    return json.loads(bytes.fromhex(token).decode())",
        "explanation": "Replaced unsafe deserialization with json.loads.",
    }
)

HANDOFF_JSON_RESPONSE = json.dumps(
    {
        "root_cause": "Using MD5 for password hashing is cryptographically insecure.",
        "verification_steps": [
            "Install bcrypt: pip install bcrypt",
            "Replace hashlib.md5 with bcrypt.hashpw",
            "Run existing auth tests",
            "Verify password verification still works",
        ],
        "effort_estimate": "Medium",
        "related_files": ["src/api.py", "tests/test_auth.py"],
        "risks": ["Migration needed for existing password hashes"],
        "context_needed": "Check if there's a password migration strategy in place.",
    }
)

PATTERN_CLUSTER_JSON = json.dumps(
    [
        {
            "cluster_id": "security_hashing",
            "canonical_pattern": "Insecure hash function usage",
            "category": "security",
            "summary": "Multiple uses of MD5/SHA1 for security-sensitive operations",
            "root_cause": "Legacy code uses weak hash functions",
            "confidence": 0.85,
            "issue_indices": [0, 1, 2, 3],
        }
    ]
)

SKILL_CONTENT_RESPONSE = """---
name: secure-hashing
description: Detects and fixes insecure hash function usage
triggers:
  - "*.py"
  - hashlib
---

# Secure Hashing Skill

## Patterns to Avoid
- hashlib.md5 for passwords
- hashlib.sha1 for tokens

## Recommended Patterns
- bcrypt for passwords
- secrets.token_urlsafe for tokens
"""


class MockM27Client:
    """
    Mock M27Client that returns realistic JSON responses
    based on the prompt content, simulating the real M2.7 model.
    """

    def __init__(self, responses: dict[str, str] | None = None):
        self.model = "MiniMax-M2.7-mock"
        self._call_count = 0
        self._calls: list[dict] = []
        self._responses = responses or {}
        self._default_response = REVIEW_JSON_RESPONSE

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        **kwargs,
    ) -> tuple[str, TokenUsage]:
        self._call_count += 1
        self._calls.append(
            {
                "messages": messages,
                "system": system,
                "max_tokens": max_tokens,
            }
        )

        # Route response based on prompt content
        user_content = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_content += msg.get("content", "")

        response = self._route_response(user_content, system or "")
        usage = TokenUsage(input_tokens=500, output_tokens=300)
        return response, usage

    def _route_response(self, user_content: str, system: str) -> str:
        # Check custom responses first
        for key, response in self._responses.items():
            if key.lower() in user_content.lower():
                return response

        # Route based on content patterns (order matters - more specific first)
        if "fix" in user_content.lower() and "generate" in user_content.lower():
            return FIX_JSON_RESPONSE
        if "handoff" in user_content.lower():
            return HANDOFF_JSON_RESPONSE
        if "skill" in user_content.lower() and "generate" in user_content.lower():
            return SKILL_CONTENT_RESPONSE
        if "cluster" in user_content.lower() and "semantically" in user_content.lower():
            return PATTERN_CLUSTER_JSON
        if "summarize" in user_content.lower():
            return "Concise summary of the finding."
        if "evolve" in user_content.lower() or "improve" in user_content.lower():
            return "Evolved strategy: Focus on security-first review with emphasis on input validation."
        return self._default_response


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def make_review_issue(
    file_path: str = "src/api.py",
    line_number: int = 12,
    severity: Severity = Severity.HIGH,
    category: IssueCategory = IssueCategory.SECURITY,
    title: str = "Insecure password hashing",
    description: str = "MD5 is broken for password hashing.",
    code_snippet: str = "hashlib.md5(password.encode())",
    suggested_fix: str | None = "Use bcrypt instead",
    auto_fixable: bool = False,
    cwe_id: str | None = "CWE-327",
) -> ReviewIssue:
    return ReviewIssue(
        file_path=file_path,
        line_number=line_number,
        severity=severity,
        category=category,
        cwe_id=cwe_id,
        title=title,
        description=description,
        code_snippet=code_snippet,
        suggested_fix=suggested_fix,
        auto_fixable=auto_fixable,
    )


def make_review_result(
    issues: list[ReviewIssue] | None = None,
    session_id: str = "test-session-001",
    target_path: str = "/tmp/test_project",
) -> ReviewResult:
    issues = issues or []
    return ReviewResult(
        session_id=session_id,
        target_path=target_path,
        issues=issues,
        files_reviewed=3,
        lines_reviewed=150,
        critical_count=sum(1 for i in issues if i.severity == Severity.CRITICAL),
        high_count=sum(1 for i in issues if i.severity == Severity.HIGH),
        medium_count=sum(1 for i in issues if i.severity == Severity.MEDIUM),
        low_count=sum(1 for i in issues if i.severity == Severity.LOW),
        info_count=sum(1 for i in issues if i.severity == Severity.INFO),
    )


# ---------------------------------------------------------------------------
# Project directory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_m27() -> MockM27Client:
    return MockM27Client()


@pytest.fixture
def sample_python_project(tmp_path: Path) -> Path:
    """Create a temporary Python project with known issues."""
    src = tmp_path / "src"
    src.mkdir()

    fixtures_base = Path(__file__).parent.parent / "fixtures" / "multi_file_project" / "src"
    for name in ("api.py", "utils.py", "database.py"):
        fixture_file = fixtures_base / name
        if fixture_file.exists():
            (src / name).write_text(fixture_file.read_text())

    # Create .muscle directory
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()

    return tmp_path


@pytest.fixture
def project_with_muscle_dir(tmp_path: Path) -> Path:
    """Create a project dir with .muscle/ already initialized."""
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    (muscle_dir / "skills").mkdir()
    (muscle_dir / "sessions").mkdir()
    (muscle_dir / "review_kb").mkdir()
    (muscle_dir / "fix_tracker").mkdir()

    # Create a sample source file
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        'def main():\n    print("Hello")\n\nif __name__ == "__main__":\n    main()\n'
    )

    return tmp_path
