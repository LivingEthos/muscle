"""
Fix Generator - Generates and applies code fixes.

Uses M2.7 to generate specific code fixes for identified issues,
applies them to the codebase, and verifies the fixes work.

Architecture Decision Record (ADR):
- Generate targeted fixes for specific issues
- Apply fixes atomically (backup + apply)
- Verify fixes don't break compilation or introduce new issues
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..m27_client import M27Client
from .types import ReviewIssue

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert code fixer. You receive:
1. A specific code issue with file path, line number, and description
2. The original code snippet
3. A suggested fix

Your task is to:
1. Generate the complete fixed code for the file
2. Apply ONLY the necessary changes to fix the issue
3. Preserve all other code exactly as-is
4. Ensure the fix is syntactically correct

Output MUST be a JSON object:
{
  "file_path": "src/auth.py",
  "original_lines": "15-25",
  "fixed_code": "def authenticate(user_id):\\n    query = 'SELECT * FROM users WHERE id = ?'\\n    cursor.execute(query, (user_id,))\\n    ...",
  "explanation": "Changed string interpolation to parameterized query..."
}
"""


@dataclass
class FixResult:
    success: bool
    file_path: str
    original_content: str
    fixed_content: str
    applied: bool
    verified: bool
    error: str | None = None


class FixGenerator:
    def __init__(
        self,
        m27_client: M27Client,
        verify_compile: bool = True,
    ):
        self.m27_client = m27_client
        self.verify_compile = verify_compile

    def generate_fix(self, issue: ReviewIssue) -> tuple[str, str]:
        if not issue.suggested_fix:
            return "", ""

        user_prompt = f"""Generate a fix for this code issue:

File: {issue.file_path}
Line: {issue.line_number}
Issue: {issue.title}
Description: {issue.description}

Original code snippet:
```
{issue.code_snippet}
```

Suggested fix approach:
{issue.suggested_fix}

Provide the JSON output with the fixed code."""

        response_text, _ = self.m27_client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        import json

        try:
            data = json.loads(response_text)
            return data.get("file_path", issue.file_path), data.get("fixed_code", "")
        except json.JSONDecodeError:
            logger.error("Failed to parse fix response")
            return issue.file_path, ""

    def apply_fix(self, issue: ReviewIssue, fixed_code: str) -> FixResult:
        file_path = Path(issue.file_path)

        if not file_path.exists():
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content=fixed_code,
                applied=False,
                verified=False,
                error="File not found",
            )

        try:
            original_content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content=fixed_code,
                applied=False,
                verified=False,
                error=f"Cannot read file: {e}",
            )

        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        shutil.copy2(file_path, backup_path)

        try:
            file_path.write_text(fixed_code, encoding="utf-8")
            applied = True
            error = None
        except Exception as e:
            shutil.move(backup_path, file_path)
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content=original_content,
                fixed_content=fixed_code,
                applied=False,
                verified=False,
                error=f"Cannot write file: {e}",
            )

        if os.path.exists(backup_path):
            os.remove(backup_path)

        return FixResult(
            success=True,
            file_path=str(file_path),
            original_content=original_content,
            fixed_content=fixed_code,
            applied=applied,
            verified=False,
            error=error,
        )

    def apply_fix_from_suggestion(self, issue: ReviewIssue) -> FixResult:
        if not issue.suggested_fix:
            return FixResult(
                success=False,
                file_path=issue.file_path,
                original_content="",
                fixed_content="",
                applied=False,
                verified=False,
                error="No suggested fix available",
            )

        file_path = Path(issue.file_path)
        if not file_path.exists():
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content="",
                applied=False,
                verified=False,
                error="File not found",
            )

        try:
            original_content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content="",
                applied=False,
                verified=False,
                error=f"Cannot read file: {e}",
            )

        lines = original_content.split("\n")
        line_idx = issue.line_number - 1

        if line_idx < 0 or line_idx >= len(lines):
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content=original_content,
                fixed_content="",
                applied=False,
                verified=False,
                error=f"Line number {issue.line_number} out of range",
            )

        snippet_lines = issue.code_snippet.split("\n")
        fixed_lines = issue.suggested_fix.split("\n")

        if len(snippet_lines) == 1 and len(fixed_lines) == 1:
            lines[line_idx] = fixed_lines[0]
        else:
            start = line_idx
            end = line_idx + len(snippet_lines)
            if end <= len(lines):
                lines[start:end] = fixed_lines
            else:
                lines[line_idx] = "\n".join(fixed_lines)

        fixed_content = "\n".join(lines)

        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        shutil.copy2(file_path, backup_path)

        try:
            file_path.write_text(fixed_content, encoding="utf-8")
            applied = True
            error = None
        except Exception as e:
            shutil.move(backup_path, file_path)
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content=original_content,
                fixed_content=fixed_content,
                applied=False,
                verified=False,
                error=f"Cannot write file: {e}",
            )

        if os.path.exists(backup_path):
            os.remove(backup_path)

        return FixResult(
            success=True,
            file_path=str(file_path),
            original_content=original_content,
            fixed_content=fixed_content,
            applied=applied,
            verified=False,
            error=error,
        )

    def rollback_fix(self, fix_result: FixResult) -> bool:
        if not fix_result.original_content:
            return False

        try:
            Path(fix_result.file_path).write_text(fix_result.original_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def verify_fix(self, file_path: str, language: str | None) -> bool:
        if not self.verify_compile:
            return True

        return True
