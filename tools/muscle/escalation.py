"""Escalation policy — when to kick a problem to the host planner model."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EscalationPolicy:
    max_m27_retries_per_issue: int = 2
    escalate_on_schema_failure_count: int = 3
    escalate_on_verification_failure_count: int = 2
    escalate_on_route_confidence_below: float = 0.5


@dataclass
class EscalationRecord:
    session_id: str
    reason: str
    source_module: str
    issue_summary: str
    attempt_count: int
    artifact_path: Path | None = None


class EscalationRecorder:
    """Records escalation events to project_memory.db and markdown artifacts."""

    def __init__(self, project_path: str | Path, policy: EscalationPolicy | None = None) -> None:
        self._project_path = Path(project_path)
        self.policy = policy or EscalationPolicy()

    def should_escalate(
        self,
        reason: str,
        attempt_count: int,
        route_confidence: float | None = None,
    ) -> bool:
        if reason == "schema_failure":
            return attempt_count >= self.policy.escalate_on_schema_failure_count
        if reason == "verification_failure":
            return attempt_count >= self.policy.escalate_on_verification_failure_count
        if reason == "low_confidence_route" and route_confidence is not None:
            return route_confidence < self.policy.escalate_on_route_confidence_below
        return False

    def emit(self, record: EscalationRecord) -> Path:
        """Persist to DB + write markdown artifact. Return artifact path."""
        artifact_dir = self._project_path / ".muscle" / "reports" / "escalations"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / f"{record.session_id}.md"
        content = self._format_artifact(record)
        artifact.write_text(content)
        record.artifact_path = artifact

        self._write_to_db(record)
        logger.info(
            "Escalated: %s in %s; artifact at %s", record.reason, record.source_module, artifact
        )
        return artifact

    def _write_to_db(self, record: EscalationRecord) -> None:
        import sqlite3
        from datetime import datetime, timezone

        db_path = self._project_path / ".muscle" / "project_memory.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO escalations
                   (session_id, created_at, reason, source_module,
                    issue_summary, attempt_count, artifact_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.session_id,
                    datetime.now(timezone.utc).isoformat(),
                    record.reason,
                    record.source_module,
                    record.issue_summary,
                    record.attempt_count,
                    str(record.artifact_path) if record.artifact_path else None,
                ),
            )

    def _format_artifact(self, record: EscalationRecord) -> str:
        return (
            f"# MUSCLE Escalation — {record.reason}\n"
            f"\n"
            f"**Session:** {record.session_id}\n"
            f"**Source:** {record.source_module}\n"
            f"**Attempts:** {record.attempt_count}\n"
            f"\n"
            f"## Issue\n"
            f"{record.issue_summary}\n"
            f"\n"
            f"## Next step\n"
            f"The host model (Claude Code / Codex) should review this issue directly; "
            f"MUSCLE's\nM2.7 agents exhausted their retry budget. "
            f"See `.muscle/reports/escalations/`\nfor related attempts.\n"
        )

    @staticmethod
    def list_unresolved(project_path: str | Path) -> list[dict]:
        """List unresolved escalations for CLI display."""
        import sqlite3

        db_path = Path(project_path) / ".muscle" / "project_memory.db"
        if not db_path.exists():
            return []
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, session_id, created_at, reason, source_module, "
                "issue_summary, attempt_count, artifact_path "
                "FROM escalations WHERE resolved = 0 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def resolve(project_path: str | Path, escalation_id: int) -> bool:
        """Mark an escalation as resolved."""
        import sqlite3
        from datetime import datetime, timezone

        db_path = Path(project_path) / ".muscle" / "project_memory.db"
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "UPDATE escalations SET resolved = 1, resolved_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), escalation_id),
            )
            return cur.rowcount > 0
