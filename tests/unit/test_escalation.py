"""Tests for the escalation policy module."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tools.muscle.escalation import (
    EscalationPolicy,
    EscalationRecord,
    EscalationRecorder,
)


def _setup_db(project_path: Path) -> Path:
    """Create a minimal project_memory.db with the escalations table."""
    db_path = project_path / ".muscle" / "project_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS escalations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                source_module TEXT NOT NULL,
                issue_summary TEXT NOT NULL,
                attempt_count INTEGER NOT NULL,
                artifact_path TEXT,
                resolved INTEGER DEFAULT 0,
                resolved_at TEXT
            )"""
        )
    return db_path


class TestEscalationPolicy:
    def test_policy_threshold_schema_failure(self) -> None:
        policy = EscalationPolicy()
        recorder = EscalationRecorder("/tmp", policy)
        assert not recorder.should_escalate("schema_failure", 2)
        assert recorder.should_escalate("schema_failure", 3)

    def test_policy_threshold_verification_failure(self) -> None:
        policy = EscalationPolicy()
        recorder = EscalationRecorder("/tmp", policy)
        assert not recorder.should_escalate("verification_failure", 1)
        assert recorder.should_escalate("verification_failure", 2)

    def test_policy_low_confidence(self) -> None:
        policy = EscalationPolicy()
        recorder = EscalationRecorder("/tmp", policy)
        assert recorder.should_escalate("low_confidence_route", 0, route_confidence=0.4)
        assert not recorder.should_escalate("low_confidence_route", 0, route_confidence=0.6)

    def test_unknown_reason_never_escalates(self) -> None:
        recorder = EscalationRecorder("/tmp")
        assert not recorder.should_escalate("unknown_reason", 999)

    def test_low_confidence_without_confidence_value(self) -> None:
        recorder = EscalationRecorder("/tmp")
        assert not recorder.should_escalate("low_confidence_route", 0, route_confidence=None)


class TestEscalationRecorder:
    def test_emit_creates_artifact_and_db_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            _setup_db(project_path)

            recorder = EscalationRecorder(project_path)
            record = EscalationRecord(
                session_id="test-session-1",
                reason="schema_failure",
                source_module="code_reviewer",
                issue_summary="M2.7 failed to produce valid JSON",
                attempt_count=3,
            )
            artifact_path = recorder.emit(record)

            assert artifact_path.exists()
            content = artifact_path.read_text()
            assert "schema_failure" in content
            assert "test-session-1" in content
            assert "code_reviewer" in content
            assert record.artifact_path == artifact_path

            db_path = project_path / ".muscle" / "project_memory.db"
            with sqlite3.connect(db_path) as conn:
                row = conn.execute(
                    "SELECT session_id, reason, source_module, attempt_count FROM escalations"
                ).fetchone()
            assert row is not None
            assert row[0] == "test-session-1"
            assert row[1] == "schema_failure"
            assert row[2] == "code_reviewer"
            assert row[3] == 3

    def test_list_unresolved_shows_open_escalations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            _setup_db(project_path)

            recorder = EscalationRecorder(project_path)
            recorder.emit(
                EscalationRecord(
                    session_id="sess-a",
                    reason="verification_failure",
                    source_module="verification_loop",
                    issue_summary="Fix verification failed",
                    attempt_count=2,
                )
            )
            recorder.emit(
                EscalationRecord(
                    session_id="sess-b",
                    reason="schema_failure",
                    source_module="code_reviewer",
                    issue_summary="JSON parse failure",
                    attempt_count=3,
                )
            )

            unresolved = EscalationRecorder.list_unresolved(project_path)
            assert len(unresolved) == 2
            session_ids = {r["session_id"] for r in unresolved}
            assert session_ids == {"sess-a", "sess-b"}

            # Resolve one
            escalation_id = unresolved[0]["id"]
            assert EscalationRecorder.resolve(project_path, escalation_id)

            remaining = EscalationRecorder.list_unresolved(project_path)
            assert len(remaining) == 1

    def test_list_unresolved_no_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = EscalationRecorder.list_unresolved(tmpdir)
            assert result == []

    def test_resolve_nonexistent_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            _setup_db(project_path)
            assert not EscalationRecorder.resolve(project_path, 9999)

    def test_emit_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            _setup_db(project_path)

            recorder = EscalationRecorder(project_path)
            record = EscalationRecord(
                session_id="mkdir-test",
                reason="verification_failure",
                source_module="verification_loop",
                issue_summary="Test directory creation",
                attempt_count=2,
            )
            artifact_path = recorder.emit(record)
            assert (project_path / ".muscle" / "reports" / "escalations").is_dir()
            assert artifact_path.exists()
