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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ..m27_client import M27Client
from ..optimization.prompt_context import build_telemetry_context, compose_prompt_envelope
from .types import HandoffIssue, HandoffPlan, IssueCategory, ReviewIssue, Severity

if TYPE_CHECKING:
    from ..optimization.context_budgeter import ContextBudgeter

logger = logging.getLogger(__name__)


# Fix: HG-01. Tags we actively strip from LLM-generated prose before it is
# written into ``.muscle/handoff_*.md``. We do not attempt to render HTML, so
# any tag is either noise or a potential injection vector when the markdown is
# rendered by a downstream reader (editor preview, web viewer).
_UNSAFE_TAG_RE = re.compile(
    r"</?(?:script|iframe|object|embed|style|link|meta|form|input|button|svg|img)\b[^>]*>",
    re.IGNORECASE,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_JS_URL_RE = re.compile(r"(?i)\bjavascript:\s*")
_DATA_URL_RE = re.compile(r"(?i)\bdata:\s*[^)\s]+", re.IGNORECASE)
_FENCE_RE = re.compile(r"```+")


def _sanitize_markdown_text(text: str | None, *, max_len: int = 8000) -> str:
    """Return a markdown-safe copy of LLM-emitted prose.

    Strips HTML elements that could render as script/image content, removes
    ``javascript:`` / ``data:`` URLs commonly used for exfiltration, and caps
    length so a pathological response cannot produce a multi-megabyte handoff
    file. Fence markers are neutralized to prevent code-block escape when the
    text is interpolated inside a fenced block.
    """
    if not text:
        return ""
    cleaned = _HTML_COMMENT_RE.sub("", str(text))
    cleaned = _UNSAFE_TAG_RE.sub("", cleaned)
    cleaned = _JS_URL_RE.sub("", cleaned)
    cleaned = _DATA_URL_RE.sub("", cleaned)
    # Collapse any ``````-style fence escapes to plain characters.
    cleaned = _FENCE_RE.sub("``\u200b`", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "\n\n<!-- truncated -->"
    return cleaned


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
    def __init__(
        self,
        m27_client: M27Client,
        context_budgeter: ContextBudgeter | None = None,
        project_path: str | None = None,
        lesson_resolver: object | None = None,
    ):
        self.m27_client = m27_client
        self.context_budgeter = context_budgeter
        self.project_path = project_path or str(Path.cwd())
        self.lesson_resolver = lesson_resolver

    def _update_telemetry_call(self, call_id: str | None, *, parse_success: bool) -> None:
        """Best-effort telemetry update for clients that support optimization hooks."""
        if not call_id:
            return

        update_call = getattr(self.m27_client, "update_telemetry_call", None)
        if callable(update_call):
            update_call(call_id, parse_success=parse_success)

    @staticmethod
    def _load_json_response(response_text: str) -> dict[str, object]:
        """Parse a JSON object from raw model output, including fenced or wrapped responses."""
        json_text = response_text.strip()
        if json_text.startswith("```"):
            lines = json_text.splitlines()
            json_lines = [line for line in lines if not line.strip().startswith("```")]
            json_text = "\n".join(json_lines).strip()

        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as first_error:
            start = json_text.find("{")
            end = json_text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise first_error
            payload = json.loads(json_text[start : end + 1])

        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Response is not a JSON object", json_text, 0)
        return payload

    @staticmethod
    def _get_string(payload: dict[str, object], key: str, default: str) -> str:
        """Read a string field from parsed JSON with a safe fallback."""
        value = payload.get(key, default)
        return value if isinstance(value, str) and value.strip() else default

    @staticmethod
    def _get_string_list(
        payload: dict[str, object],
        key: str,
        default: list[str],
    ) -> list[str]:
        """Read a list of strings from parsed JSON with a safe fallback."""
        value = payload.get(key, default)
        if not isinstance(value, list):
            return default
        normalized = [item for item in value if isinstance(item, str) and item.strip()]
        return normalized or default

    def generate_handoff(
        self,
        issue: ReviewIssue,
        all_issues: list[ReviewIssue],
        session_id: str,
        target_path: str,
        workflow_name: str | None = None,
        review_mode: str | None = None,
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
        prompt_envelope = compose_prompt_envelope(
            base_prompt=user_prompt,
            lesson_resolver=self.lesson_resolver,
            query_text=f"{issue.title}\n{issue.description}",
            stage="handoff",
            base_context_strategy="handoff_issue_context",
            session_id=session_id,
        )
        user_prompt = prompt_envelope.prompt

        telemetry_context = build_telemetry_context(
            project_path=self.project_path,
            session_id=session_id,
            stage="handoff",
            prompt_envelope=prompt_envelope,
            workflow_name=workflow_name,
            review_mode=review_mode,
            target_type="file" if Path(target_path).is_file() else "directory",
            metadata={
                "file_path": issue.file_path,
                "line_number": issue.line_number,
            },
        )
        assert telemetry_context is not None

        response_text, _ = self.m27_client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            telemetry_context=telemetry_context,
        )

        try:
            data = self._load_json_response(response_text)
            self._update_telemetry_call(telemetry_context.call_id, parse_success=True)
            handoff_issue = HandoffIssue(
                issue=issue,
                root_cause=self._get_string(data, "root_cause", "See issue description"),
                verification_steps=self._get_string_list(data, "verification_steps", []),
                effort_estimate=self._get_string(data, "effort_estimate", "Medium"),
                related_files=self._get_string_list(data, "related_files", related_files),
            )
        except json.JSONDecodeError:
            logger.error("Failed to parse handoff response")
            self._update_telemetry_call(telemetry_context.call_id, parse_success=False)
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
        workflow_name: str | None = None,
        review_mode: str | None = None,
    ) -> HandoffPlan:
        handoff_issues: list[HandoffIssue] = []

        for issue in issues:
            if (
                issue.severity.value >= Severity.HIGH.value
                or issue.category == IssueCategory.SECURITY
            ):
                related = self._find_related_files(issue, issues)
                context = self._get_code_context(issue)
                user_prompt = f"""Create handoff plan for:
FILE: {issue.file_path}
LINE: {issue.line_number}
TITLE: {issue.title}
CODE: {issue.code_snippet}

CONTEXT: {context}
"""
                prompt_envelope = compose_prompt_envelope(
                    base_prompt=user_prompt,
                    lesson_resolver=self.lesson_resolver,
                    query_text=f"{issue.title}\n{issue.description}",
                    stage="handoff",
                    base_context_strategy="handoff_issue_context",
                    session_id=session_id,
                )
                telemetry_context = None

                try:
                    telemetry_context = build_telemetry_context(
                        project_path=self.project_path,
                        session_id=session_id,
                        stage="handoff",
                        prompt_envelope=prompt_envelope,
                        workflow_name=workflow_name,
                        review_mode=review_mode,
                        target_type="file" if Path(target_path).is_file() else "directory",
                        metadata={"file_path": issue.file_path},
                    )
                    assert telemetry_context is not None
                    response_text, _ = self.m27_client.chat(
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": prompt_envelope.prompt,
                            },
                        ],
                        telemetry_context=telemetry_context,
                    )
                    data = self._load_json_response(response_text)
                    self._update_telemetry_call(telemetry_context.call_id, parse_success=True)
                    handoff_issues.append(
                        HandoffIssue(
                            issue=issue,
                            root_cause=self._get_string(data, "root_cause", issue.description),
                            verification_steps=self._get_string_list(
                                data,
                                "verification_steps",
                                [],
                            ),
                            effort_estimate=self._get_string(data, "effort_estimate", "Medium"),
                            related_files=self._get_string_list(data, "related_files", related),
                        )
                    )
                except json.JSONDecodeError:
                    self._update_telemetry_call(
                        telemetry_context.call_id if telemetry_context is not None else None,
                        parse_success=False,
                    )
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
                    _sanitize_markdown_text(hi.root_cause),
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
                        _sanitize_markdown_text(issue.description),
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
                    + [
                        f"{i}. {_sanitize_markdown_text(step, max_len=500)}"
                        for i, step in enumerate(hi.verification_steps, 1)
                    ]
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
