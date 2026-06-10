"""
Review Artifacts - Structured review workflow evidence persisted to disk.

Architecture Decision Record (ADR):
- Persist structured artifacts for every review run to improve auditability
- Keep artifacts JSON-first so other tools and future workflows can reuse them
- Write summary.md for human-readable diagnosis and handoff
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ..io_safety import atomic_write_json, atomic_write_text
from .types import ReviewIssue

TRACE_POLICY_THIN = "thin"
TRACE_POLICY_THICK = "thick"
THICK_TRACE_TRIGGER_REASONS = frozenset(
    {
        "benchmark_run",
        "host_escalation",
        "pressure_review_parse_failure",
        "schema_failure",
        "verification_failure",
    }
)


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


def resolve_trace_policy(*reasons: str | None) -> tuple[str, list[str]]:
    """Resolve a thin/thick trace mode from the active reasons."""
    active_reasons = sorted({reason for reason in reasons if reason})
    if any(reason in THICK_TRACE_TRIGGER_REASONS for reason in active_reasons):
        return TRACE_POLICY_THICK, active_reasons
    return TRACE_POLICY_THIN, active_reasons


class ReviewArtifactStore:
    """Persist workflow artifacts under `.muscle/review_artifacts/<session_id>/`."""

    def __init__(self, project_path: str, session_id: str):
        self.project_path = Path(project_path)
        self.session_id = session_id
        self.root = self.project_path / ".muscle" / "review_artifacts" / session_id
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.root / "manifest.json"
        self._manifest: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session_id,
            "artifact_dir": str(self.root),
            "artifacts": {},
        }
        self._flush_manifest()

    @property
    def artifact_dir(self) -> str:
        return str(self.root)

    def write_scope(self, scope: Any) -> Path:
        return self._write_json(
            "scope.json",
            scope.to_dict() if hasattr(scope, "to_dict") else scope,
            artifact_type="scope",
        )

    def write_agent_findings(self, agent_findings: dict[str, list[ReviewIssue]]) -> Path:
        payload = {
            agent: [review_issue_to_dict(issue) for issue in issues]
            for agent, issues in agent_findings.items()
        }
        return self._write_json("agent-findings.json", payload, artifact_type="agent_findings")

    def write_synthesis(
        self,
        issues: list[ReviewIssue],
        summary: dict[str, Any] | None = None,
    ) -> Path:
        payload = {
            "issues": [review_issue_to_dict(issue) for issue in issues],
            "summary": summary or {},
        }
        return self._write_json("synthesis.json", payload, artifact_type="synthesis")

    def write_fixes(self, fixes: dict[str, Any]) -> Path:
        return self._write_json("fixes.json", fixes, artifact_type="fixes")

    def write_validation(self, validation: dict[str, Any]) -> Path:
        return self._write_json("validation.json", validation, artifact_type="validation")

    def write_summary(self, markdown: str) -> Path:
        path = self.root / "summary.md"
        atomic_write_text(path, markdown)
        self._record_artifact(path, artifact_type="summary")
        return path

    def write_diagnostic(self, name: str, payload: Any) -> Path:
        filename = f"{name}.json"
        return self._write_json(filename, payload, artifact_type="diagnostic")

    def write_raw_response(self, name: str, payload: str) -> Path:
        path = self.root / f"{name}.txt"
        atomic_write_text(path, payload)
        self._record_artifact(path, artifact_type="raw_response")
        return path

    def prepare_llm_trace(
        self,
        *,
        call_id: str,
        stage: str,
        prompt_text: str,
        context_strategy: str,
        context_chars: int,
        prompt_metadata: dict[str, Any] | None = None,
        trace_policy: str = TRACE_POLICY_THIN,
        trace_reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """Write prompt/render/validation placeholders for one LLM call."""
        prompt_payload: dict[str, Any] = {
            "call_id": call_id,
            "stage": stage,
            "context_strategy": context_strategy,
            "context_chars": context_chars,
            "trace_policy": trace_policy,
            "trace_reasons": list(trace_reasons or []),
            "prompt_chars": len(prompt_text),
        }
        if trace_policy == TRACE_POLICY_THICK:
            prompt_payload["prompt"] = prompt_text

        render_payload: dict[str, Any] = {
            "call_id": call_id,
            "stage": stage,
            "context_strategy": context_strategy,
            "trace_policy": trace_policy,
            "trace_reasons": list(trace_reasons or []),
            "prompt_metadata": dict(prompt_metadata or {}),
        }
        if trace_policy == TRACE_POLICY_THICK:
            render_payload["rendered_prompt"] = prompt_text

        validation_payload = {
            "call_id": call_id,
            "stage": stage,
            "status": "pending",
            "trace_policy": trace_policy,
            "trace_reasons": list(trace_reasons or []),
        }

        prompt_path = self._write_trace_json(
            call_id=call_id,
            stage=stage,
            name="prompt",
            payload=prompt_payload,
        )
        render_path = self._write_trace_json(
            call_id=call_id,
            stage=stage,
            name="render",
            payload=render_payload,
        )
        validation_path = self._write_trace_json(
            call_id=call_id,
            stage=stage,
            name="validation",
            payload=validation_payload,
        )
        return {
            "trace_capture_policy": trace_policy,
            "trace_capture_reasons": list(trace_reasons or []),
            "trace_pointers": {
                "prompt": self._relative_path(prompt_path),
                "render": self._relative_path(render_path),
                "validation": self._relative_path(validation_path),
            },
        }

    def finalize_llm_trace(
        self,
        *,
        call_id: str,
        stage: str,
        validation_payload: dict[str, Any],
    ) -> Path:
        """Overwrite the validation trace payload for one LLM call."""
        return self._write_trace_json(
            call_id=call_id,
            stage=stage,
            name="validation",
            payload=validation_payload,
        )

    def _write_json(
        self,
        filename: str,
        payload: Any,
        *,
        artifact_type: str,
    ) -> Path:
        path = self.root / filename
        if is_dataclass(payload) and not isinstance(payload, type):
            data = asdict(payload)
        else:
            data = payload
        atomic_write_json(path, data, indent=2, sort_keys=True)
        self._record_artifact(path, artifact_type=artifact_type)
        return path

    def _write_trace_json(
        self,
        *,
        call_id: str,
        stage: str,
        name: str,
        payload: dict[str, Any],
    ) -> Path:
        trace_root = self.root / "llm_traces" / stage / call_id
        trace_root.mkdir(parents=True, exist_ok=True)
        path = trace_root / f"{name}.json"
        atomic_write_json(path, payload, indent=2, sort_keys=True)
        self._record_artifact(path, artifact_type=f"llm_trace:{name}")
        return path

    def _record_artifact(self, path: Path, *, artifact_type: str) -> None:
        relative_path = self._relative_path(path)
        payload = path.read_bytes()
        self._manifest["artifacts"][relative_path] = {
            "path": relative_path,
            "type": artifact_type,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }
        self._flush_manifest()

    def _flush_manifest(self) -> None:
        artifact_entries = self._manifest.get("artifacts", {})
        manifest_payload = {
            "schema_version": self._manifest["schema_version"],
            "session_id": self._manifest["session_id"],
            "artifact_dir": self._manifest["artifact_dir"],
            "artifact_count": len(artifact_entries),
            "artifacts": {key: artifact_entries[key] for key in sorted(artifact_entries)},
        }
        atomic_write_json(self._manifest_path, manifest_payload, indent=2, sort_keys=True)

    def _relative_path(self, path: Path) -> str:
        return str(path.relative_to(self.root))
