"""
Review Artifacts - Structured review workflow evidence persisted to disk.

Architecture Decision Record (ADR):
- Persist structured artifacts for every review run to improve auditability
- Keep artifacts JSON-first so other tools and future workflows can reuse them
- Write summary.md for human-readable diagnosis and handoff
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .types import ReviewIssue


def review_issue_to_dict(issue: ReviewIssue) -> dict[str, Any]:
    """Serialize ReviewIssue to a JSON-friendly dict."""
    return {
        "file_path": issue.file_path,
        "line_number": issue.line_number,
        "severity": issue.severity.name,
        "category": issue.category.value,
        "cwe_id": issue.cwe_id,
        "title": issue.title,
        "description": issue.description,
        "code_snippet": issue.code_snippet,
        "suggested_fix": issue.suggested_fix,
        "auto_fixable": issue.auto_fixable,
        "source_agent": issue.source_agent,
    }


class ReviewArtifactStore:
    """Persist workflow artifacts under `.muscle/review_artifacts/<session_id>/`."""

    def __init__(self, project_path: str, session_id: str):
        self.project_path = Path(project_path)
        self.root = self.project_path / ".muscle" / "review_artifacts" / session_id
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def artifact_dir(self) -> str:
        return str(self.root)

    def write_scope(self, scope: Any) -> Path:
        return self._write_json("scope.json", scope.to_dict() if hasattr(scope, "to_dict") else scope)

    def write_agent_findings(self, agent_findings: dict[str, list[ReviewIssue]]) -> Path:
        payload = {
            agent: [review_issue_to_dict(issue) for issue in issues]
            for agent, issues in agent_findings.items()
        }
        return self._write_json("agent-findings.json", payload)

    def write_synthesis(
        self,
        issues: list[ReviewIssue],
        summary: dict[str, Any] | None = None,
    ) -> Path:
        payload = {
            "issues": [review_issue_to_dict(issue) for issue in issues],
            "summary": summary or {},
        }
        return self._write_json("synthesis.json", payload)

    def write_fixes(self, fixes: dict[str, Any]) -> Path:
        return self._write_json("fixes.json", fixes)

    def write_validation(self, validation: dict[str, Any]) -> Path:
        return self._write_json("validation.json", validation)

    def write_summary(self, markdown: str) -> Path:
        path = self.root / "summary.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def _write_json(self, filename: str, payload: Any) -> Path:
        path = self.root / filename
        if is_dataclass(payload) and not isinstance(payload, type):
            data = asdict(payload)
        else:
            data = payload
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return path
