"""
Handoff Generator - Creates detailed handoff plans for complex issues.

For issues that require human or specialized agent attention, generates
detailed markdown plans that provide full context for completing the work.

Architecture Decision Record (ADR):
- Markdown-first output for human readability
- Complete context (code, issue, suggested approach)
- JSON structure underneath for programmatic consumption
- Includes verification steps so handoff recipient can confirm completion
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..m27_client import M27Client
from .types import HandoffIssue, HandoffPlan, IssueCategory, ReviewIssue, Severity

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert software engineer creating a detailed handoff plan
for complex code issues that require human intervention. You receive:
1. A code issue with full context
2. The surrounding code context
3. The suggested approach

Your task is to create a comprehensive handoff plan that:
1. Clearly explains the issue and its impact
2. Provides exact file locations and line numbers
3. Explains the root cause (not just symptoms)
4. Suggests a concrete fix approach
5. Lists verification steps to confirm the fix
6. Estimates effort (Low < 30min, Medium 1-2h, High > 2h)
7. Identifies related files that might need changes

Output MUST be valid JSON:
{
  "root_cause": "Detailed explanation of why this is a problem...",
  "fix_approach": "Step-by-step fix approach...",
  "verification_steps": [
    "1. Verify the fix compiles",
    "2. Run specific test case",
    "3. Check that related functionality still works"
  ],
  "effort_estimate": "Low/Medium/High",
  "related_files": ["file1.py", "file2.js"],
  "risks": ["Potential breaking change in X", "May affect Y"],
  "context_needed": "Any additional context the reviewer should know"
}
"""


class HandoffGenerator:
    def __init__(self, m27_client: M27Client):
        self.m27_client = m27_client

    def generate_handoff(
        self,
        issue: ReviewIssue,
        all_issues: list[ReviewIssue],
        session_id: str,
        target_path: str,
    ) -> HandoffPlan:
        related_files = self._find_related_files(issue, all_issues)
        code_context = self._get_code_context(issue)

        user_prompt = f"""Create a detailed handoff plan for this code issue:

FILE: {issue.file_path}
LINE: {issue.line_number}
SEVERITY: {issue.severity.name} ({issue.severity.value})
CATEGORY: {issue.category.value}
TITLE: {issue.title}

DESCRIPTION:
{issue.description}

CODE SNIPPET:
```
{issue.code_snippet}
```

SUGGESTED FIX:
{issue.suggested_fix or "No specific fix suggested - needs investigation"}

RELATED FILES:
{json.dumps(related_files, indent=2)}

CODE CONTEXT (surrounding 20 lines):
```
{code_context}
```

Provide the JSON handoff plan."""

        response_text, _ = self.m27_client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )

        try:
            data = json.loads(response_text)
            handoff_issue = HandoffIssue(
                issue=issue,
                root_cause=data.get("root_cause", "See issue description"),
                verification_steps=data.get("verification_steps", []),
                effort_estimate=data.get("effort_estimate", "Medium"),
                related_files=data.get("related_files", related_files),
            )
        except json.JSONDecodeError:
            logger.error("Failed to parse handoff response")
            handoff_issue = HandoffIssue(
                issue=issue,
                root_cause=issue.description,
                verification_steps=[
                    "Verify the issue exists",
                    "Apply suggested fix",
                    "Run tests",
                    "Confirm issue is resolved",
                ],
                effort_estimate="Medium",
                related_files=related_files,
            )

        markdown = self._generate_markdown(session_id, target_path, [handoff_issue])

        return HandoffPlan(
            session_id=session_id,
            target_path=target_path,
            issues=[handoff_issue],
            generated_at=datetime.now(timezone.utc).isoformat(),
            markdown=markdown,
        )

    def generate_handoffs(
        self,
        issues: list[ReviewIssue],
        session_id: str,
        target_path: str,
    ) -> HandoffPlan:
        handoff_issues: list[HandoffIssue] = []

        for issue in issues:
            if (
                issue.severity.value >= Severity.HIGH.value
                or issue.category == IssueCategory.SECURITY
            ):
                related = self._find_related_files(issue, issues)
                context = self._get_code_context(issue)

                try:
                    response_text, _ = self.m27_client.chat(
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": f"""Create handoff plan for:
FILE: {issue.file_path}
LINE: {issue.line_number}
TITLE: {issue.title}
CODE: {issue.code_snippet}

CONTEXT: {context}
""",
                            },
                        ],
                    )
                    data = json.loads(response_text)
                    handoff_issues.append(
                        HandoffIssue(
                            issue=issue,
                            root_cause=data.get("root_cause", issue.description),
                            verification_steps=data.get("verification_steps", []),
                            effort_estimate=data.get("effort_estimate", "Medium"),
                            related_files=data.get("related_files", related),
                        )
                    )
                except json.JSONDecodeError:
                    handoff_issues.append(
                        HandoffIssue(
                            issue=issue,
                            root_cause=issue.description,
                            verification_steps=["Verify fix", "Run tests"],
                            effort_estimate="Medium",
                            related_files=related,
                        )
                    )

        markdown = self._generate_markdown(session_id, target_path, handoff_issues)

        return HandoffPlan(
            session_id=session_id,
            target_path=target_path,
            issues=handoff_issues,
            generated_at=datetime.now(timezone.utc).isoformat(),
            markdown=markdown,
        )

    def _generate_markdown(
        self,
        session_id: str,
        target_path: str,
        issues: list[HandoffIssue],
    ) -> str:
        lines = [
            "# Code Review Handoff Plan",
            "",
            f"**Session:** {session_id}",
            f"**Target:** {target_path}",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            "",
            "---",
            "",
        ]

        for i, hi in enumerate(issues, 1):
            issue = hi.issue
            lines.extend(
                [
                    f"## Issue #{i}: {issue.title}",
                    "",
                    f"**Severity:** {issue.severity.name} ({issue.severity.value})",
                    f"**Category:** {issue.category.value}",
                    f"**Location:** {issue.file_path}:{issue.line_number}",
                    f"**Effort:** {hi.effort_estimate}",
                    "",
                    "### Root Cause",
                    "",
                    hi.root_cause,
                    "",
                    "### Code Context",
                    "",
                    "```",
                    f"File: {issue.file_path}",
                    f"Line: {issue.line_number}",
                    "```",
                    "",
                    "```",
                    issue.code_snippet or "N/A",
                    "```",
                    "",
                ]
            )

            if issue.description:
                lines.extend(
                    [
                        "### Description",
                        "",
                        issue.description,
                        "",
                    ]
                )

            if issue.suggested_fix:
                lines.extend(
                    [
                        "### Suggested Fix",
                        "",
                        "```",
                        issue.suggested_fix,
                        "```",
                        "",
                    ]
                )

            if hi.verification_steps:
                lines.extend(
                    [
                        "### Verification Steps",
                        "",
                    ]
                    + [f"{i}. {step}" for i, step in enumerate(hi.verification_steps, 1)]
                    + [
                        "",
                    ]
                )

            if hi.related_files:
                lines.extend(
                    [
                        "### Related Files",
                        "",
                        ", ".join(f"`{f}`" for f in hi.related_files),
                        "",
                    ]
                )

            lines.extend(["---", ""])

        return "\n".join(lines)

    @staticmethod
    def _find_related_files(issue: ReviewIssue, all_issues: list[ReviewIssue]) -> list[str]:
        related: set[str] = set()
        issue_dir = str(Path(issue.file_path).parent)

        for other in all_issues:
            if other.file_path == issue.file_path:
                continue
            other_dir = str(Path(other.file_path).parent)
            if other_dir == issue_dir or issue_dir in other_dir or other_dir in issue_dir:
                related.add(other.file_path)

        return list(related)[:5]

    @staticmethod
    def _get_code_context(issue: ReviewIssue, context_lines: int = 10) -> str:
        try:
            path = Path(issue.file_path)
            if not path.exists():
                return "N/A (file not accessible)"

            lines = path.read_text(encoding="utf-8").split("\n")
            start = max(0, issue.line_number - context_lines - 1)
            end = min(len(lines), issue.line_number + context_lines)

            return "\n".join(
                f"{i + 1}: {line}" for i, line in enumerate(lines[start:end], start + 1)
            )
        except Exception:
            return "N/A (cannot read file)"
