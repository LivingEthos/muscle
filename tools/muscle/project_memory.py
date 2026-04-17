"""
ProjectMemory - Unified SQLite access layer for the per-project memory database (MUS-010).

Architecture Decision Record (ADR):
- Single SQLite file per project at `.muscle/project_memory.db`
- Tables created and managed via migration framework (MUS-011)
- Typed helpers for inserts, queries
- Supports safe schema upgrades via MigrationRunner
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .migrations import MigrationRunner
from .migrations._0009_project_optimization import ensure_project_optimization_schema
from .migrations._0010_cross_project_learning import ensure_cross_project_learning_schema
from .migrations._0011_llm_call_model_identity import ensure_llm_call_model_identity_schema
from .transferable_lesson_scrubber import (
    build_transfer_scrub_context,
    scrub_transferable_lesson,
)

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_MEMORY_PATH = ".muscle/project_memory.db"
TRANSFER_VALIDATION_SUCCESS_THRESHOLD = 2
TRANSFER_PROMOTION_VALIDATION_THRESHOLD = 3
TRANSFER_PROMOTION_SUCCESS_THRESHOLD = 2
TRANSFER_PROMOTION_SUCCESS_RATE_THRESHOLD = 0.67
TRANSFER_ARCHIVE_IDLE_DAYS = 14
TRANSFER_ARCHIVE_MIN_VALIDATIONS = 2
TRANSFER_ARCHIVE_MAX_SUCCESS_RATE = 0.34
ACTIVE_TRANSFERRED_LESSON_STATUSES = frozenset({"provisional", "validated"})
SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_LOCK_RETRY_ATTEMPTS = 5
SQLITE_LOCK_RETRY_DELAY_SECONDS = 0.2


class ProjectMemory:
    """
    Unified SQLite access layer for the per-project memory database.

    Provides typed insert/query helpers for all tables managed via
    the migration framework. Initializes database on first access.
    """

    def __init__(self, project_path: str, db_path: str | None = None):
        """
        Initialize ProjectMemory for a project.

        Args:
            project_path: Absolute path to the project root.
            db_path: Optional path to the DB file. Defaults to <project_path>/.muscle/project_memory.db.
        """
        self.project_path = Path(project_path)
        self._muscle_dir = self.project_path / ".muscle"
        self._muscle_dir.mkdir(parents=True, exist_ok=True)

        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = self._muscle_dir / "project_memory.db"

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Return a connection with row factory enabled.

        Note: Prefer :meth:`_conn` / :meth:`connection` (context-managed)
        for new code so the connection is always closed and the transaction
        is committed or rolled back automatically.
        """
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Yield a configured sqlite3 connection with WAL + busy_timeout pragmas.

        Semantics:
        - On clean exit, the transaction is committed and the connection closed.
        - On exception, the transaction is rolled back and the connection closed
          before the exception propagates.

        This is the canonical way to get a DB handle from ``ProjectMemory``; use
        it (via :meth:`connection`) anywhere you would previously have called
        :meth:`_get_connection` and then written a try/finally block.
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn.rollback()
            except sqlite3.Error:
                logger.debug("rollback failed on context exit", exc_info=True)
            raise
        finally:
            conn.close()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Public context manager yielding a configured sqlite3 connection.

        Thin public wrapper around :meth:`_conn` used by B.6 call-sites
        (``delegation_metrics``, ``escalation``, ``response_cache``, tests).
        """
        with self._conn() as conn:
            yield conn

    @staticmethod
    def _is_locked_error(exc: sqlite3.Error) -> bool:
        return "database is locked" in str(exc).lower()

    def _run_write_transaction(self, operation: Any) -> Any:
        last_error: sqlite3.Error | None = None
        for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
            conn = None
            try:
                conn = self._get_connection()
                conn.execute("BEGIN IMMEDIATE")
                result = operation(conn)
                conn.commit()
                return result
            except sqlite3.Error as exc:
                last_error = exc
                if conn is not None:
                    conn.rollback()
                if not self._is_locked_error(exc) or attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                    raise
                time.sleep(SQLITE_LOCK_RETRY_DELAY_SECONDS * (attempt + 1))
            finally:
                if conn is not None:
                    conn.close()
        if last_error is not None:
            raise last_error
        msg = "SQLite write transaction failed unexpectedly"
        raise sqlite3.OperationalError(msg)

    def _init_db(self) -> None:
        """Initialize database by running all pending migrations."""
        try:
            runner = MigrationRunner(str(self.project_path), str(self._db_path))
            runner.run()
            conn = self._get_connection()
            try:
                ensure_project_optimization_schema(conn)
                ensure_cross_project_learning_schema(conn)
                ensure_llm_call_model_identity_schema(conn)
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.error(f"ProjectMemory init error: {e}")
            raise

    # -------------------------------------------------------------------------
    # Task helpers
    # -------------------------------------------------------------------------

    def insert_task(
        self,
        project_path: str,
        created_at: str,
        title: str,
        description: str,
        status: str,
        outcome: str | None = None,
        token_cost: int = 0,
        duration_ms: int = 0,
    ) -> int:
        """Insert a row into the tasks table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tasks
                (project_path, created_at, title, description, status, outcome, token_cost, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    created_at,
                    title,
                    description,
                    status,
                    outcome,
                    token_cost,
                    duration_ms,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def update_task_outcome(self, task_id: int, outcome: str) -> bool:
        """Update the outcome field of a task."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET outcome = ? WHERE id = ?",
                (outcome, task_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def get_task(self, task_id: int) -> dict | None:
        """Get a task by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_tasks(
        self,
        project_path: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List tasks, optionally filtered by project_path and status."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM tasks WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Review run helpers
    # -------------------------------------------------------------------------

    def insert_review_run(
        self,
        project_path: str,
        review_mode: str,
        target_path: str,
        findings_count: int,
        token_cost: int,
        duration_ms: int,
        created_at: str,
    ) -> int:
        """Insert a row into the review_runs table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO review_runs
                (project_path, review_mode, target_path, findings_count, token_cost, duration_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    review_mode,
                    target_path,
                    findings_count,
                    token_cost,
                    duration_ms,
                    created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_review_run(self, review_run_id: int) -> dict | None:
        """Get a review run by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM review_runs WHERE id = ?", (review_run_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_review_runs(
        self,
        project_path: str | None = None,
        review_mode: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List review runs, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM review_runs WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if review_mode:
                query += " AND review_mode = ?"
                params.append(review_mode)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Review finding helpers
    # -------------------------------------------------------------------------

    def insert_review_finding(
        self,
        review_run_id: int,
        rule_id: str,
        severity: str,
        file_path: str,
        line_number: int,
        message: str,
        auto_fixable: bool = False,
        fix_applied: bool = False,
        outcome: str | None = None,
    ) -> int:
        """Insert a row into the review_findings table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO review_findings
                (review_run_id, rule_id, severity, file_path, line_number, message, auto_fixable, fix_applied, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_run_id,
                    rule_id,
                    severity,
                    file_path,
                    line_number,
                    message,
                    int(auto_fixable),
                    int(fix_applied),
                    outcome,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_findings_for_run(self, review_run_id: int) -> list[dict]:
        """Get all findings for a given review run."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY id",
                (review_run_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Fix attempt helpers
    # -------------------------------------------------------------------------

    def insert_fix_attempt(
        self,
        finding_id: int,
        fix_content: str | None = None,
        verification_passed: bool = False,
        notes: str | None = None,
    ) -> int:
        """Insert a row into the fix_attempts table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO fix_attempts
                (finding_id, created_at, fix_content, verification_passed, notes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    datetime.now().isoformat(),
                    fix_content,
                    int(verification_passed),
                    notes,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def insert_change_event(
        self,
        project_path: str,
        changed_files_json: str,
        diff_summary: str | None = None,
        review_run_id: int | None = None,
    ) -> int:
        """Insert a row into the change_events table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO change_events
                (project_path, created_at, changed_files_json, diff_summary, review_run_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    changed_files_json,
                    diff_summary,
                    review_run_id,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Backup helpers
    # -------------------------------------------------------------------------

    def insert_backup(
        self,
        project_path: str,
        created_at: str,
        backup_type: str,
        file_path: str,
        checksum: str | None,
        size_bytes: int,
        retention_days: int,
    ) -> int:
        """Insert a row into the backups table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO backups
                (project_path, created_at, backup_type, file_path, checksum, size_bytes, retention_days)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    created_at,
                    backup_type,
                    file_path,
                    checksum,
                    size_bytes,
                    retention_days,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def insert_backup_with_action(
        self,
        project_path: str,
        created_at: str,
        backup_type: str,
        file_path: str,
        checksum: str | None,
        size_bytes: int,
        retention_days: int,
        action_details_json: str | None = None,
        actor: str = "muscle",
    ) -> int:
        """Insert backup metadata and its action log in one transaction."""

        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO backups
                (project_path, created_at, backup_type, file_path, checksum, size_bytes, retention_days)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    created_at,
                    backup_type,
                    file_path,
                    checksum,
                    size_bytes,
                    retention_days,
                ),
            )
            backup_id = cursor.lastrowid or 0
            cursor.execute(
                """
                INSERT INTO action_log
                (project_path, created_at, action_type, entity_type, entity_id, details_json, actor)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    "backup",
                    "backup",
                    backup_id,
                    action_details_json or "{}",
                    actor,
                ),
            )
            return backup_id

        return int(self._run_write_transaction(operation))

    def get_backup(self, backup_id: int) -> dict | None:
        """Get a backup by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM backups WHERE id = ?", (backup_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_backups(
        self,
        project_path: str | None = None,
        backup_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List backups, optionally filtered by project_path and backup_type."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM backups WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if backup_type:
                query += " AND backup_type = ?"
                params.append(backup_type)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def delete_backup(self, backup_id: int) -> bool:
        """Delete a backup record by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Memory decision helpers
    # -------------------------------------------------------------------------

    def insert_decision(
        self,
        project_path: str,
        decision_type: str,
        source_table: str,
        source_id: int,
        evidence_json: str,
        score_json: str,
        reasoning: str,
    ) -> int:
        """Insert a row into the memory_decisions table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memory_decisions
                (project_path, created_at, decision_type, source_table, source_id, evidence_json, score_json, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    decision_type,
                    source_table,
                    source_id,
                    evidence_json,
                    score_json,
                    reasoning,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_decisions(
        self,
        project_path: str | None = None,
        decision_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List memory decisions, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM memory_decisions WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if decision_type:
                query += " AND decision_type = ?"
                params.append(decision_type)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def insert_action_log(
        self,
        project_path: str,
        action_type: str,
        entity_type: str,
        entity_id: int | None = None,
        details_json: str | None = None,
        actor: str = "muscle",
    ) -> int:
        """Insert a row into the action_log table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO action_log
                (project_path, created_at, action_type, entity_type, entity_id, details_json, actor)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    action_type,
                    entity_type,
                    entity_id,
                    details_json or "{}",
                    actor,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_action_logs(
        self,
        project_path: str | None = None,
        action_type: str | None = None,
        action_types: list[str] | None = None,
        entity_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List action log entries, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM action_log WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if action_types:
                placeholders = ", ".join("?" for _ in action_types)
                query += f" AND action_type IN ({placeholders})"
                params.extend(action_types)
            elif action_type:
                query += " AND action_type = ?"
                params.append(action_type)
            if entity_type:
                query += " AND entity_type = ?"
                params.append(entity_type)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Conversation event helpers
    # -------------------------------------------------------------------------

    def insert_conversation_event(
        self,
        project_path: str,
        event_type: str,
        timestamp: str,
        summary: str,
        task_id: int | None = None,
        metadata_json: str | None = None,
    ) -> int:
        """Insert a row into the conversation_events table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO conversation_events
                (project_path, task_id, event_type, timestamp, summary, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_path, task_id, event_type, timestamp, summary, metadata_json),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_conversation_events(
        self,
        project_path: str | None = None,
        task_id: int | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List conversation events, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM conversation_events WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if task_id is not None:
                query += " AND task_id = ?"
                params.append(task_id)
            if event_type:
                query += " AND event_type = ?"
                params.append(event_type)
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Learned rule helpers
    # -------------------------------------------------------------------------

    def insert_learned_rule(
        self,
        project_path: str,
        rule_text: str,
        trigger_pattern: str,
        status: str = "active",
    ) -> int:
        """Insert a row into the learned_rules table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learned_rules
                (project_path, created_at, rule_text, trigger_pattern, recurrence_count, success_rate, status)
                VALUES (?, ?, ?, ?, 1, 0.0, ?)
                """,
                (project_path, datetime.now().isoformat(), rule_text, trigger_pattern, status),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_learned_rule(self, rule_id: int) -> dict | None:
        """Get a learned rule by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM learned_rules WHERE id = ?", (rule_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_learned_rules(
        self,
        project_path: str | None = None,
        status: str | None = None,
        trigger_pattern: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List learned rules, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM learned_rules WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if status:
                query += " AND status = ?"
                params.append(status)
            if trigger_pattern:
                query += " AND trigger_pattern = ?"
                params.append(trigger_pattern)
            query += " ORDER BY recurrence_count DESC, success_rate DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def increment_rule_recurrence(self, rule_id: int) -> bool:
        """Increment recurrence_count and update last_triggered for a rule."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE learned_rules
                SET recurrence_count = recurrence_count + 1,
                    last_triggered = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), rule_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def update_rule_success_rate(self, rule_id: int, success: bool) -> bool:
        """Update success_rate based on a new outcome."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE learned_rules
                SET success_rate = CASE
                    WHEN recurrence_count = 1 THEN ?
                    ELSE (success_rate * (recurrence_count - 1) + ?) / recurrence_count
                END
                WHERE id = ?
                """,
                (1.0 if success else 0.0, 1.0 if success else 0.0, rule_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def promote_rule(self, rule_id: int) -> bool:
        """Mark a rule as promoted to CLAUDE.md."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE learned_rules
                SET status = 'promoted',
                    promoted_to_claude_md = 1,
                    promoted_at = ?
                WHERE id = ?
                """,
                (now, rule_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Skill helpers
    # -------------------------------------------------------------------------

    def insert_skill(
        self,
        project_path: str,
        name: str,
        description: str,
        trigger_pattern: str,
        file_path: str | None = None,
        status: str = "active",
    ) -> int:
        """Insert a row into the skills table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO skills
                (project_path, created_at, name, description, trigger_pattern, file_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    name,
                    description,
                    trigger_pattern,
                    file_path,
                    status,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_skill(self, skill_id: int) -> dict | None:
        """Get a skill by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_skills(
        self,
        project_path: str | None = None,
        status: str | None = None,
        trigger_pattern: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List skills, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM skills WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if status:
                query += " AND status = ?"
                params.append(status)
            if trigger_pattern:
                query += " AND trigger_pattern = ?"
                params.append(trigger_pattern)
            query += " ORDER BY use_count DESC, last_used DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def increment_skill_usage(self, skill_id: int) -> bool:
        """Increment use_count and update last_used for a skill."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE skills
                SET use_count = use_count + 1,
                    last_used = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), skill_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def skill_similar_exists(
        self,
        project_path: str,
        trigger_pattern: str,
        status: str = "active",
    ) -> dict | None:
        """Check if a skill with a similar trigger_pattern already exists (DB-first duplicate suppression)."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM skills
                WHERE project_path = ?
                  AND trigger_pattern = ?
                  AND status = ?
                LIMIT 1
                """,
                (project_path, trigger_pattern, status),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def update_skill_evidence_count(self, skill_id: int, evidence_count: int) -> bool:
        """Update evidence_count for a skill (set to max of current + new)."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE skills
                SET evidence_count = MAX(evidence_count, ?)
                WHERE id = ?
                """,
                (evidence_count, skill_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def archive_skill(self, skill_id: int, reason: str = "") -> bool:
        """Archive a skill: set status='archived' and archived_at timestamp."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE skills
                SET status = 'archived',
                    archived_at = ?
                WHERE id = ?
                """,
                (now, skill_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def update_skill_revision(self, skill_id: int, revision: int) -> bool:
        """Update revision number for a skill (revisioning, not append-only)."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE skills SET revision = ? WHERE id = ?",
                (revision, skill_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def record_skill_decision(
        self,
        project_path: str,
        skill_id: int,
        reasoning: str,
        evidence_json: str,
    ) -> int:
        """Record a CREATE_SKILL decision in memory_decisions for audit trail."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memory_decisions
                (project_path, created_at, decision_type, source_table, source_id,
                 evidence_json, score_json, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    "create_skill",
                    "skills",
                    skill_id,
                    evidence_json,
                    "{}",
                    reasoning,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_stale_skills(
        self,
        project_path: str,
        evidence_threshold: int = 3,
        lookback_days: int = 30,
    ) -> list[dict]:
        """Return active skills with low evidence_count that may need archiving."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM skills
                WHERE project_path = ?
                  AND status = 'active'
                  AND evidence_count < ?
                  AND created_at < datetime('now', '-' || ? || ' days')
                ORDER BY evidence_count ASC
                LIMIT 20
                """,
                (project_path, evidence_threshold, lookback_days),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Agent helpers
    # -------------------------------------------------------------------------

    def insert_agent(
        self,
        project_path: str,
        name: str,
        description: str,
        trigger_pattern: str,
        file_path: str | None = None,
        status: str = "active",
    ) -> int:
        """Insert a row into the agents table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agents
                (project_path, created_at, name, description, trigger_pattern, file_path, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    name,
                    description,
                    trigger_pattern,
                    file_path,
                    status,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_agent(self, agent_id: int) -> dict | None:
        """Get an agent by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_agents(
        self,
        project_path: str | None = None,
        status: str | None = None,
        trigger_pattern: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List agents, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM agents WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if status:
                query += " AND status = ?"
                params.append(status)
            if trigger_pattern:
                query += " AND trigger_pattern = ?"
                params.append(trigger_pattern)
            query += " ORDER BY use_count DESC, last_used DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def increment_agent_usage(self, agent_id: int) -> bool:
        """Increment use_count and update last_used for an agent."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE agents
                SET use_count = use_count + 1,
                    last_used = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), agent_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def archive_agent(self, agent_id: int) -> bool:
        """Archive an agent by setting archived_at timestamp."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE agents
                SET archived_at = ?,
                    status = 'archived'
                WHERE id = ?
                """,
                (datetime.now().isoformat(), agent_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def update_agent_revision(
        self,
        agent_id: int,
        revision_history_json: str,
    ) -> bool:
        """Update agent revision_count and revision_history_json."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE agents
                SET revision_count = revision_count + 1,
                    revision_history_json = ?
                WHERE id = ?
                """,
                (revision_history_json, agent_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def record_agent_decision(
        self,
        project_path: str,
        agent_id: int,
        decision_type: str,
        reasoning: str,
        evidence_json: str,
    ) -> int:
        """Record an agent lifecycle decision in memory_decisions for audit trail.

        Args:
            project_path: Project root path
            agent_id: ID of the agent in agents table
            decision_type: Type of decision (create_agent, revise_agent, archive_agent, retain_agent)
            reasoning: Human-readable explanation of why this decision was made
            evidence_json: JSON with supporting evidence (occurrences, confidence, etc.)

        Returns:
            ID of the inserted memory_decisions row
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memory_decisions
                (project_path, created_at, decision_type, source_table, source_id,
                 evidence_json, score_json, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    decision_type,
                    "agents",
                    agent_id,
                    evidence_json,
                    "{}",
                    reasoning,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_active_agents_count(self, project_path: str) -> int:
        """Return count of non-archived agents for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM agents
                WHERE project_path = ? AND archived_at IS NULL
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            if conn:
                conn.close()

    def get_least_used_active_agent(self, project_path: str) -> dict | None:
        """Return the least recently used active agent, or None if none exist."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM agents
                WHERE project_path = ? AND archived_at IS NULL
                ORDER BY last_used ASC NULLS FIRST, use_count ASC
                LIMIT 1
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def count_decisions_for_pattern(
        self,
        project_path: str,
        trigger_pattern: str,
        decision_type: str = "agent_candidate",
    ) -> int:
        """Count memory_decisions matching a trigger pattern and decision_type."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM memory_decisions
                WHERE project_path = ?
                  AND decision_type = ?
                  AND evidence_json LIKE ?
                """,
                (project_path, decision_type, f'%"{trigger_pattern}"%'),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Project notes helpers
    # -------------------------------------------------------------------------

    def insert_project_note(
        self,
        project_path: str,
        category: str,
        title: str,
        content: str,
    ) -> int:
        """Insert a row into the project_notes table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO project_notes
                (project_path, created_at, category, title, content, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_path, now, category, title, content, now),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_project_note(self, note_id: int) -> dict | None:
        """Get a project note by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM project_notes WHERE id = ?", (note_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_project_notes(
        self,
        project_path: str | None = None,
        category: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List project notes, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM project_notes WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if category:
                query += " AND category = ?"
                params.append(category)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def update_project_note(self, note_id: int, content: str) -> bool:
        """Update content and updated_at of a project note."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE project_notes
                SET content = ?, updated_at = ?
                WHERE id = ?
                """,
                (content, datetime.now().isoformat(), note_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Automation state helpers
    # -------------------------------------------------------------------------

    def set_automation_state(
        self,
        project_path: str,
        state_key: str,
        state_value: str | None = None,
    ) -> int:
        """
        Set an automation state (insert or update on conflict).
        Returns the row ID.
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO automation_state (project_path, created_at, state_key, state_value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_path, state_key) DO UPDATE SET
                    state_value = excluded.state_value,
                    updated_at = excluded.updated_at
                """,
                (project_path, now, state_key, state_value, now),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_automation_state(self, project_path: str, state_key: str) -> dict | None:
        """Get a project-local automation state by key."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM automation_state
                WHERE project_path = ? AND state_key = ?
                """,
                (project_path, state_key),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_automation_states(
        self,
        project_path: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List automation states, optionally filtered by project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM automation_state WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Cross-project learning helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_lesson_key(trigger_pattern: str, lesson_text: str) -> str:
        normalized = f"{trigger_pattern.strip().lower()}::{lesson_text.strip().lower()}"
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _load_json_object(raw_value: Any) -> dict[str, Any]:
        """Parse a JSON object string into a dictionary."""
        if isinstance(raw_value, dict):
            return dict(raw_value)
        if not raw_value:
            return {}
        try:
            parsed = json.loads(str(raw_value))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_iso_datetime(raw_value: Any) -> datetime | None:
        """Parse an ISO datetime string, returning None on invalid input."""
        if not raw_value:
            return None
        try:
            return datetime.fromisoformat(str(raw_value))
        except ValueError:
            return None

    def _get_transferred_lesson_feedback_summary(self, lesson_key: str) -> dict[str, int]:
        """Return manual confirmation and rejection counts for one transferred lesson."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT outcome, COUNT(*) AS outcome_count
                FROM lesson_usage_events
                WHERE project_path = ?
                  AND lesson_source = 'related'
                  AND lesson_key = ?
                  AND stage = 'manual_feedback'
                GROUP BY outcome
                """,
                (str(self.project_path), lesson_key),
            )
            counts = {"manual_accepts": 0, "manual_rejects": 0}
            for row in cursor.fetchall():
                outcome = str(row["outcome"] or "")
                count = int(row["outcome_count"] or 0)
                if outcome == "positive_user_confirmation":
                    counts["manual_accepts"] = count
                elif outcome == "negative_user_rejection":
                    counts["manual_rejects"] = count
            return counts
        finally:
            if conn:
                conn.close()

    def _evaluate_transferred_lesson_row(
        self,
        lesson_row: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Compute recommendation metadata for one transferred lesson."""
        evaluation_time = now or datetime.now()
        validation_count = int(lesson_row.get("validation_count", 0) or 0)
        success_count = int(lesson_row.get("success_count", 0) or 0)
        success_rate = (success_count / validation_count) if validation_count else 0.0
        imported_at = self._parse_iso_datetime(lesson_row.get("imported_at"))
        updated_at = self._parse_iso_datetime(lesson_row.get("updated_at")) or imported_at
        age_days = max((evaluation_time - imported_at).days, 0) if imported_at is not None else None
        idle_days = max((evaluation_time - updated_at).days, 0) if updated_at is not None else None
        feedback_summary = self._get_transferred_lesson_feedback_summary(
            str(lesson_row.get("lesson_key", ""))
        )
        validation_status = str(lesson_row.get("validation_status", "provisional") or "provisional")

        promotion_candidate = (
            validation_status == "validated"
            and success_count >= TRANSFER_PROMOTION_SUCCESS_THRESHOLD
            and (
                validation_count >= TRANSFER_PROMOTION_VALIDATION_THRESHOLD
                or feedback_summary["manual_accepts"] > 0
            )
            and success_rate >= TRANSFER_PROMOTION_SUCCESS_RATE_THRESHOLD
        )
        archive_candidate = (
            validation_status in ACTIVE_TRANSFERRED_LESSON_STATUSES
            and not promotion_candidate
            and validation_count >= TRANSFER_ARCHIVE_MIN_VALIDATIONS
            and success_rate <= TRANSFER_ARCHIVE_MAX_SUCCESS_RATE
            and (idle_days is None or idle_days >= TRANSFER_ARCHIVE_IDLE_DAYS)
        )

        recommendation = "observe"
        reasons: list[str] = []
        status_explanation = ""
        metadata = self._load_json_object(lesson_row.get("metadata_json"))
        if validation_status == "promoted":
            recommendation = "already_local"
            promoted_rule_id = int(lesson_row.get("promoted_rule_id", 0) or 0)
            status_explanation = "Promoted into project-local learned rules" + (
                f" as rule #{promoted_rule_id}" if promoted_rule_id else ""
            )
            reasons.append("already promoted into project-local learned rules")
        elif validation_status == "archived":
            recommendation = "archived"
            archive_reason = (
                self._load_json_object(metadata.get("archive", {})).get("reason")
                if isinstance(metadata.get("archive"), dict)
                else None
            )
            status_explanation = (
                f"Archived after current-project evaluation: {archive_reason}"
                if archive_reason
                else "Archived after current-project evaluation"
            )
            reasons.append(archive_reason or "archived external lesson")
        elif promotion_candidate:
            recommendation = "promote"
            status_explanation = (
                "Validated in this project and ready for promotion into local memory"
            )
            if feedback_summary["manual_accepts"] > 0:
                reasons.append("manually confirmed in the current project")
            if validation_count >= TRANSFER_PROMOTION_VALIDATION_THRESHOLD:
                reasons.append("met validation-count threshold for promotion")
            reasons.append(
                f"success rate {success_rate:.0%} across {validation_count} validation events"
            )
        elif archive_candidate:
            recommendation = "archive"
            status_explanation = "Failed to prove useful in this project and should be archived"
            reasons.append(
                f"low success rate {success_rate:.0%} across {validation_count} validation events"
            )
            if idle_days is not None:
                reasons.append(f"idle for {idle_days} days")
        else:
            if validation_status == "validated":
                status_explanation = (
                    "Validated in this project; keep observing until promotion threshold is met"
                )
                reasons.append(
                    "validated locally but waiting for one more successful use or explicit promotion"
                )
            else:
                status_explanation = "Still provisional; gathering current-project evidence"
                reasons.append(
                    f"needs more current-project evidence ({success_count}/{validation_count} successes)"
                )
            if feedback_summary["manual_rejects"] > 0:
                reasons.append(f"manual rejections: {feedback_summary['manual_rejects']}")

        return {
            **lesson_row,
            "success_rate": success_rate,
            "age_days": age_days,
            "idle_days": idle_days,
            "manual_accepts": feedback_summary["manual_accepts"],
            "manual_rejects": feedback_summary["manual_rejects"],
            "promotion_candidate": promotion_candidate,
            "archive_candidate": archive_candidate,
            "recommendation": recommendation,
            "status_explanation": status_explanation,
            "recommendation_reason": "; ".join(reasons),
            "metadata": metadata,
        }

    def upsert_related_project_link(
        self,
        project_path: str,
        source_project_path: str,
        link_mode: str,
        relatedness_score: float = 0.0,
        status: str = "active",
        fingerprint_json: str | None = None,
        last_synced_at: str | None = None,
    ) -> int:
        """Insert or refresh a related-project link."""
        conn = None
        now = datetime.now().isoformat()
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO related_project_links (
                    project_path,
                    source_project_path,
                    link_mode,
                    status,
                    relatedness_score,
                    fingerprint_json,
                    created_at,
                    updated_at,
                    last_synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_path, source_project_path, link_mode) DO UPDATE SET
                    status = excluded.status,
                    relatedness_score = excluded.relatedness_score,
                    fingerprint_json = excluded.fingerprint_json,
                    updated_at = excluded.updated_at,
                    last_synced_at = excluded.last_synced_at
                """,
                (
                    project_path,
                    source_project_path,
                    link_mode,
                    status,
                    relatedness_score,
                    fingerprint_json or "{}",
                    now,
                    now,
                    last_synced_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_related_project_links(
        self,
        project_path: str | None = None,
        status: str | None = None,
        link_mode: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List related-project links for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM related_project_links WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if status:
                query += " AND status = ?"
                params.append(status)
            if link_mode:
                query += " AND link_mode = ?"
                params.append(link_mode)
            query += " ORDER BY relatedness_score DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def unlink_related_project(self, project_path: str, source_project_path: str) -> bool:
        """Mark related-project links inactive and remove snapshot-imported lessons."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE related_project_links
                SET status = 'inactive', updated_at = ?
                WHERE project_path = ? AND source_project_path = ?
                """,
                (datetime.now().isoformat(), project_path, source_project_path),
            )
            deactivated_links = cursor.rowcount
            cursor.execute(
                """
                DELETE FROM transferred_lessons
                WHERE project_path = ? AND source_project_path = ? AND link_mode = 'snapshot'
                """,
                (project_path, source_project_path),
            )
            deleted_snapshot_lessons = cursor.rowcount
            conn.commit()
            self.insert_action_log(
                project_path=project_path,
                action_type="related_project_unlinked",
                entity_type="related_project",
                details_json=json.dumps(
                    {
                        "source_project_path": source_project_path,
                        "deactivated_links": deactivated_links,
                        "deleted_snapshot_lessons": deleted_snapshot_lessons,
                    },
                    sort_keys=True,
                ),
            )
            return True
        finally:
            if conn:
                conn.close()

    def upsert_transferred_lesson(
        self,
        project_path: str,
        source_project_path: str,
        lesson_text: str,
        trigger_pattern: str,
        link_mode: str = "snapshot",
        source_rule_id: int | None = None,
        validation_status: str = "provisional",
        scope_json: str | None = None,
        metadata_json: str | None = None,
    ) -> int:
        """Insert or refresh a transferred lesson."""
        conn = None
        now = datetime.now().isoformat()
        lesson_key = self._build_lesson_key(trigger_pattern, lesson_text)
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO transferred_lessons (
                    project_path,
                    source_project_path,
                    source_rule_id,
                    lesson_key,
                    lesson_text,
                    trigger_pattern,
                    link_mode,
                    validation_status,
                    validation_count,
                    success_count,
                    scope_json,
                    metadata_json,
                    imported_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)
                ON CONFLICT(project_path, lesson_key, source_project_path) DO UPDATE SET
                    lesson_text = excluded.lesson_text,
                    trigger_pattern = excluded.trigger_pattern,
                    link_mode = excluded.link_mode,
                    scope_json = excluded.scope_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    project_path,
                    source_project_path,
                    source_rule_id,
                    lesson_key,
                    lesson_text,
                    trigger_pattern,
                    link_mode,
                    validation_status,
                    scope_json or "{}",
                    metadata_json or "{}",
                    now,
                    now,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_transferred_lessons(
        self,
        project_path: str | None = None,
        validation_status: str | None = None,
        validation_statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List transferred lessons for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM transferred_lessons WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if validation_statuses:
                placeholders = ", ".join("?" for _ in validation_statuses)
                query += f" AND validation_status IN ({placeholders})"
                params.extend(validation_statuses)
            elif validation_status:
                query += " AND validation_status = ?"
                params.append(validation_status)
            query += " ORDER BY success_count DESC, validation_count DESC, updated_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def get_transferred_lesson(self, lesson_id: int) -> dict | None:
        """Return one transferred lesson by ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transferred_lessons WHERE id = ?", (lesson_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_transferred_lesson_recommendations(
        self,
        *,
        project_path: str | None = None,
        include_inactive: bool = False,
        only_candidates: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return transferred lessons enriched with promotion and archive recommendations."""
        statuses = None if include_inactive else list(ACTIVE_TRANSFERRED_LESSON_STATUSES)
        lessons = self.list_transferred_lessons(
            project_path=project_path,
            validation_statuses=statuses,
            limit=limit,
        )
        evaluated = [self._evaluate_transferred_lesson_row(row) for row in lessons]
        if only_candidates:
            evaluated = [
                row for row in evaluated if row["promotion_candidate"] or row["archive_candidate"]
            ]

        priority = {
            "promote": 0,
            "archive": 1,
            "observe": 2,
            "already_local": 3,
            "archived": 4,
        }
        evaluated.sort(
            key=lambda row: (
                priority.get(str(row.get("recommendation", "observe")), 9),
                -float(row.get("success_rate", 0.0) or 0.0),
                -int(row.get("validation_count", 0) or 0),
                str(row.get("updated_at", "")),
            )
        )
        return evaluated

    def get_transferred_lesson_recommendation(self, lesson_id: int) -> dict[str, Any] | None:
        """Return recommendation metadata for one transferred lesson."""
        lesson = self.get_transferred_lesson(lesson_id)
        if lesson is None:
            return None
        return self._evaluate_transferred_lesson_row(lesson)

    def import_project_lessons(
        self,
        project_path: str,
        source_project_path: str,
        link_mode: str = "snapshot",
        relatedness_score: float = 0.0,
    ) -> dict[str, Any]:
        """Import learned rules from another project as provisional lessons."""
        source_pm = ProjectMemory(source_project_path)
        link_id = self.upsert_related_project_link(
            project_path=project_path,
            source_project_path=source_project_path,
            link_mode=link_mode,
            relatedness_score=relatedness_score,
            last_synced_at=datetime.now().isoformat(),
        )

        if link_mode == "attach":
            self.insert_action_log(
                project_path=project_path,
                action_type="related_project_attached",
                entity_type="related_project",
                entity_id=link_id or None,
                details_json=json.dumps(
                    {
                        "source_project_path": source_project_path,
                        "link_mode": link_mode,
                        "relatedness_score": relatedness_score,
                    },
                    sort_keys=True,
                ),
            )
            return {"imported": 0, "attached": 1}

        imported = 0
        rejected: list[dict[str, Any]] = []
        scrub_context = build_transfer_scrub_context(source_project_path)
        for row in source_pm.list_learned_rules(project_path=source_project_path, limit=200):
            scrubbed = scrub_transferable_lesson(str(row.get("rule_text", "")), scrub_context)
            if not scrubbed.accepted:
                rejected.append(
                    {
                        "source_rule_id": int(row.get("id", 0) or 0),
                        "content_hash": scrubbed.content_hash,
                        "reason_codes": list(scrubbed.reason_codes),
                    }
                )
                continue
            self.upsert_transferred_lesson(
                project_path=project_path,
                source_project_path=source_project_path,
                source_rule_id=int(row.get("id", 0) or 0),
                lesson_text=scrubbed.normalized_text,
                trigger_pattern=str(row.get("trigger_pattern", "")),
                link_mode="snapshot",
                validation_status="provisional",
                metadata_json=json.dumps(
                    {
                        "source_status": row.get("status", "active"),
                        "source_success_rate": row.get("success_rate", 0.0),
                        "scrubber": scrubbed.metadata(),
                    },
                    sort_keys=True,
                ),
            )
            imported += 1
        self.insert_action_log(
            project_path=project_path,
            action_type="related_import_scrub",
            entity_type="related_project",
            details_json=json.dumps(
                {
                    "source_project_path": source_project_path,
                    "link_mode": link_mode,
                    "imported": imported,
                    "rejected": rejected,
                    "scrubber_version": "1",
                },
                sort_keys=True,
            ),
        )
        self.insert_action_log(
            project_path=project_path,
            action_type="related_project_imported",
            entity_type="related_project",
            entity_id=link_id or None,
            details_json=json.dumps(
                {
                    "source_project_path": source_project_path,
                    "link_mode": link_mode,
                    "relatedness_score": relatedness_score,
                    "imported": imported,
                    "rejected": len(rejected),
                },
                sort_keys=True,
            ),
        )
        return {
            "imported": imported,
            "attached": 0,
            "rejected": len(rejected),
            "rejections": rejected,
        }

    def record_transferred_lesson_outcome(self, lesson_key: str, success: bool) -> bool:
        """Increment validation counters for a transferred lesson."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT validation_count, success_count, validation_status
                FROM transferred_lessons
                WHERE lesson_key = ? AND project_path = ?
                """,
                (lesson_key, str(self.project_path)),
            )
            row = cursor.fetchone()
            if row is None:
                return False

            validation_count = int(row["validation_count"] or 0) + 1
            success_count = int(row["success_count"] or 0) + (1 if success else 0)
            current_status = str(row["validation_status"] or "provisional")
            cursor.execute(
                """
                SELECT id, source_project_path
                FROM transferred_lessons
                WHERE lesson_key = ? AND project_path = ?
                """,
                (lesson_key, str(self.project_path)),
            )
            lesson_row = cursor.fetchone()
            next_status = current_status
            if current_status in ACTIVE_TRANSFERRED_LESSON_STATUSES:
                if success_count >= TRANSFER_VALIDATION_SUCCESS_THRESHOLD:
                    next_status = "validated"
                else:
                    next_status = "provisional"
            cursor.execute(
                """
                UPDATE transferred_lessons
                SET validation_count = ?,
                    success_count = ?,
                    validation_status = ?,
                    updated_at = ?
                WHERE lesson_key = ? AND project_path = ?
                """,
                (
                    validation_count,
                    success_count,
                    next_status,
                    datetime.now().isoformat(),
                    lesson_key,
                    str(self.project_path),
                ),
            )
            conn.commit()
            if current_status != next_status and next_status == "validated":
                lesson_id = int(lesson_row["id"] or 0) if lesson_row else 0
                source_project_path = (
                    str(lesson_row["source_project_path"] or "") if lesson_row else ""
                )
                reasoning = (
                    "Transferred lesson validated in the current project after "
                    f"{success_count}/{validation_count} successful validation events"
                )
                self.insert_decision(
                    project_path=str(self.project_path),
                    decision_type="validate_transferred_lesson",
                    source_table="transferred_lessons",
                    source_id=lesson_id,
                    evidence_json=json.dumps(
                        {
                            "lesson_key": lesson_key,
                            "validation_count": validation_count,
                            "success_count": success_count,
                            "source_project_path": source_project_path,
                        },
                        sort_keys=True,
                    ),
                    score_json=json.dumps(
                        {
                            "success_rate": success_count / validation_count
                            if validation_count
                            else 0.0,
                            "status": next_status,
                        },
                        sort_keys=True,
                    ),
                    reasoning=reasoning,
                )
                self.insert_action_log(
                    project_path=str(self.project_path),
                    action_type="transferred_lesson_validated",
                    entity_type="transferred_lesson",
                    entity_id=lesson_id or None,
                    details_json=json.dumps(
                        {
                            "lesson_key": lesson_key,
                            "validation_count": validation_count,
                            "success_count": success_count,
                            "source_project_path": source_project_path,
                            "reason": reasoning,
                        },
                        sort_keys=True,
                    ),
                )
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def promote_transferred_lesson(self, lesson_id: int, force: bool = False) -> int:
        """Promote a validated transferred lesson into project-local learned rules."""
        lesson = self.get_transferred_lesson(lesson_id)
        if lesson is None:
            return 0
        evaluation = self._evaluate_transferred_lesson_row(lesson)
        if not force and not evaluation["promotion_candidate"]:
            return 0
        if lesson.get("validation_status") == "promoted":
            return int(lesson.get("promoted_rule_id", 0) or 0)
        if lesson.get("validation_status") == "archived" and not force:
            return 0

        existing_rule = None
        for row in self.list_learned_rules(
            project_path=str(self.project_path),
            trigger_pattern=str(lesson.get("trigger_pattern", "")),
            limit=200,
        ):
            if str(row.get("rule_text", "")) == str(lesson.get("lesson_text", "")) and str(
                row.get("status", "")
            ) in {"active", "promoted"}:
                existing_rule = row
                break

        if existing_rule is not None:
            local_rule_id = int(existing_rule.get("id", 0) or 0)
        else:
            local_rule_id = self.insert_learned_rule(
                project_path=str(self.project_path),
                rule_text=str(lesson.get("lesson_text", "")),
                trigger_pattern=str(lesson.get("trigger_pattern", "")),
                status="active",
            )
        conn = None
        try:
            conn = self._get_connection()
            conn.execute(
                """
                UPDATE transferred_lessons
                SET validation_status = 'promoted',
                    promoted_rule_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (local_rule_id, datetime.now().isoformat(), lesson_id),
            )
            conn.commit()
        finally:
            if conn:
                conn.close()

        self.insert_decision(
            project_path=str(self.project_path),
            decision_type="promote_transferred_lesson",
            source_table="transferred_lessons",
            source_id=lesson_id,
            evidence_json=json.dumps(
                {
                    "lesson_key": lesson.get("lesson_key"),
                    "validation_count": evaluation["validation_count"],
                    "success_count": evaluation["success_count"],
                    "success_rate": evaluation["success_rate"],
                    "manual_accepts": evaluation["manual_accepts"],
                    "manual_rejects": evaluation["manual_rejects"],
                    "source_project_path": lesson.get("source_project_path"),
                },
                sort_keys=True,
            ),
            score_json=json.dumps(
                {
                    "recommendation": evaluation["recommendation"],
                    "promotion_candidate": evaluation["promotion_candidate"],
                    "archive_candidate": evaluation["archive_candidate"],
                },
                sort_keys=True,
            ),
            reasoning=(
                "Promoted transferred lesson into project-local learned rules after "
                f"{evaluation['recommendation_reason']}"
            ),
        )
        self.insert_action_log(
            project_path=str(self.project_path),
            action_type="transferred_lesson_promoted",
            entity_type="transferred_lesson",
            entity_id=lesson_id,
            details_json=json.dumps(
                {
                    "lesson_key": lesson.get("lesson_key"),
                    "source_project_path": lesson.get("source_project_path"),
                    "promoted_rule_id": local_rule_id,
                    "force": force,
                    "recommendation_reason": evaluation["recommendation_reason"],
                    "used_existing_rule": existing_rule is not None,
                },
                sort_keys=True,
            ),
        )
        return local_rule_id

    def archive_transferred_lesson(
        self,
        lesson_id: int,
        *,
        reason: str,
        force: bool = False,
    ) -> bool:
        """Archive a transferred lesson that has aged out or failed to prove useful."""
        lesson = self.get_transferred_lesson(lesson_id)
        if lesson is None:
            return False
        evaluation = self._evaluate_transferred_lesson_row(lesson)
        if not force and not evaluation["archive_candidate"]:
            return False
        if lesson.get("validation_status") == "promoted" and not force:
            return False
        if lesson.get("validation_status") == "archived":
            return True

        metadata = self._load_json_object(lesson.get("metadata_json"))
        metadata["archive"] = {
            "reason": reason,
            "archived_at": datetime.now().isoformat(),
            "previous_status": lesson.get("validation_status", "provisional"),
        }

        conn = None
        try:
            conn = self._get_connection()
            conn.execute(
                """
                UPDATE transferred_lessons
                SET validation_status = 'archived',
                    metadata_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(metadata, sort_keys=True), datetime.now().isoformat(), lesson_id),
            )
            conn.commit()
        finally:
            if conn:
                conn.close()

        self.insert_decision(
            project_path=str(self.project_path),
            decision_type="archive_transferred_lesson",
            source_table="transferred_lessons",
            source_id=lesson_id,
            evidence_json=json.dumps(
                {
                    "lesson_key": lesson.get("lesson_key"),
                    "validation_count": evaluation["validation_count"],
                    "success_count": evaluation["success_count"],
                    "success_rate": evaluation["success_rate"],
                    "idle_days": evaluation["idle_days"],
                    "source_project_path": lesson.get("source_project_path"),
                },
                sort_keys=True,
            ),
            score_json=json.dumps(
                {
                    "recommendation": evaluation["recommendation"],
                    "archive_candidate": evaluation["archive_candidate"],
                },
                sort_keys=True,
            ),
            reasoning=reason,
        )
        self.insert_action_log(
            project_path=str(self.project_path),
            action_type="transferred_lesson_archived",
            entity_type="transferred_lesson",
            entity_id=lesson_id,
            details_json=json.dumps(
                {
                    "lesson_key": lesson.get("lesson_key"),
                    "reason": reason,
                    "force": force,
                    "source_project_path": lesson.get("source_project_path"),
                },
                sort_keys=True,
            ),
        )
        return True

    def insert_model_identity_history(
        self,
        project_path: str,
        identity: dict[str, Any],
    ) -> int:
        """Persist one model identity resolution event."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO model_identity_history (
                    project_path,
                    created_at,
                    requested_label,
                    provider_endpoint,
                    provider_fingerprint,
                    canonical_model_key,
                    identity_source,
                    confidence,
                    manual_override,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    identity.get("requested_label"),
                    identity.get("provider_endpoint"),
                    identity.get("provider_fingerprint"),
                    identity.get("canonical_model_key"),
                    identity.get("identity_source", "unresolved"),
                    float(identity.get("confidence", 0.0) or 0.0),
                    int(bool(identity.get("manual_override"))),
                    json.dumps(identity.get("metadata", {}), sort_keys=True),
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def get_latest_model_identity(self, project_path: str) -> dict | None:
        """Return the most recent model identity history row."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM model_identity_history
                WHERE project_path = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_model_identity_history(
        self,
        project_path: str,
        limit: int = 20,
    ) -> list[dict]:
        """List recent model identity resolution events for one project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM model_identity_history
                WHERE project_path = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (project_path, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def insert_lesson_usage_event(
        self,
        project_path: str,
        stage: str,
        lesson_source: str,
        lesson_key: str,
        session_id: str | None = None,
        call_id: str | None = None,
        canonical_model_key: str | None = None,
        source_project_path: str | None = None,
        outcome: str | None = None,
        metadata_json: str | None = None,
    ) -> int:
        """Persist a lesson-usage event for prompt context tracing."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO lesson_usage_events (
                    project_path,
                    created_at,
                    session_id,
                    call_id,
                    stage,
                    lesson_source,
                    lesson_key,
                    canonical_model_key,
                    source_project_path,
                    outcome,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    session_id,
                    call_id,
                    stage,
                    lesson_source,
                    lesson_key,
                    canonical_model_key,
                    source_project_path,
                    outcome,
                    metadata_json or "{}",
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_lesson_usage_events(
        self,
        project_path: str | None = None,
        session_id: str | None = None,
        stages: list[str] | None = None,
        lesson_source: str | None = None,
        only_pending: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        """List lesson-usage events, optionally filtered by project or session."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM lesson_usage_events WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if stages:
                placeholders = ", ".join("?" for _ in stages)
                query += f" AND stage IN ({placeholders})"
                params.extend(stages)
            if lesson_source:
                query += " AND lesson_source = ?"
                params.append(lesson_source)
            if only_pending:
                query += " AND (outcome IS NULL OR outcome = '')"
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def update_lesson_usage_outcomes(
        self,
        *,
        project_path: str,
        outcome: str,
        session_id: str | None = None,
        stages: list[str] | None = None,
        lesson_source: str | None = None,
        only_pending: bool = True,
    ) -> list[dict]:
        """Update matching lesson-usage events with an outcome and return the affected rows."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM lesson_usage_events WHERE project_path = ?"
            params: list[Any] = [project_path]
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if stages:
                placeholders = ", ".join("?" for _ in stages)
                query += f" AND stage IN ({placeholders})"
                params.extend(stages)
            if lesson_source:
                query += " AND lesson_source = ?"
                params.append(lesson_source)
            if only_pending:
                query += " AND (outcome IS NULL OR outcome = '')"

            rows = [dict(row) for row in cursor.execute(query, params).fetchall()]
            if not rows:
                return []

            placeholders = ", ".join("?" for _ in rows)
            cursor.execute(
                f"UPDATE lesson_usage_events SET outcome = ? WHERE id IN ({placeholders})",
                [outcome, *[int(row["id"]) for row in rows]],
            )
            conn.commit()
            for row in rows:
                row["outcome"] = outcome
            return rows
        finally:
            if conn:
                conn.close()

    def apply_transferred_lesson_outcomes(
        self,
        *,
        project_path: str,
        outcome: str,
        success: bool,
        session_id: str | None = None,
        stages: list[str] | None = None,
        only_pending: bool = True,
    ) -> dict[str, int]:
        """Apply an outcome to related-lesson usage events and update validation counters."""
        updated_rows = self.update_lesson_usage_outcomes(
            project_path=project_path,
            outcome=outcome,
            session_id=session_id,
            stages=stages,
            lesson_source="related",
            only_pending=only_pending,
        )
        lesson_keys = sorted(
            {str(row.get("lesson_key", "")) for row in updated_rows if row.get("lesson_key")}
        )
        for lesson_key in lesson_keys:
            self.record_transferred_lesson_outcome(lesson_key, success=success)
        return {
            "events_updated": len(updated_rows),
            "lessons_updated": len(lesson_keys),
        }

    def record_manual_transferred_lesson_feedback(
        self,
        lesson_key: str,
        *,
        success: bool,
        note: str | None = None,
    ) -> bool:
        """Record explicit user feedback for one transferred lesson."""
        lesson = None
        for row in self.list_transferred_lessons(project_path=str(self.project_path), limit=500):
            if str(row.get("lesson_key", "")) == lesson_key:
                lesson = row
                break
        if lesson is None:
            return False

        outcome = "positive_user_confirmation" if success else "negative_user_rejection"
        self.insert_lesson_usage_event(
            project_path=str(self.project_path),
            stage="manual_feedback",
            lesson_source="related",
            lesson_key=lesson_key,
            source_project_path=str(lesson.get("source_project_path", "") or ""),
            outcome=outcome,
            metadata_json=json.dumps({"note": note or ""}, sort_keys=True),
        )
        self.record_transferred_lesson_outcome(lesson_key, success=success)
        return True

    # -------------------------------------------------------------------------
    # Optimization and telemetry helpers
    # -------------------------------------------------------------------------

    def insert_llm_call(
        self,
        project_path: str,
        call_id: str,
        session_id: str,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int,
        success: bool,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        parse_success: bool | None = None,
        validation_success: bool | None = None,
        context_chars: int = 0,
        context_strategy: str = "default",
        requested_label: str | None = None,
        provider_endpoint: str | None = None,
        provider_fingerprint: str | None = None,
        canonical_model_key: str | None = None,
        identity_source: str = "unresolved",
        identity_confidence: float = 0.0,
        manual_override: bool = False,
        metadata_json: str | None = None,
        created_at: str | None = None,
    ) -> int:
        """Insert or replace an LLM call telemetry row."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO llm_calls
                (
                    project_path, created_at, call_id, session_id, stage, workflow_name,
                    review_mode, model, input_tokens, output_tokens, duration_ms, success,
                    parse_success, validation_success, context_chars, context_strategy,
                    requested_label, provider_endpoint, provider_fingerprint,
                    canonical_model_key, identity_source, identity_confidence,
                    manual_override, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    created_at or datetime.now().isoformat(),
                    call_id,
                    session_id,
                    stage,
                    workflow_name,
                    review_mode,
                    model,
                    input_tokens,
                    output_tokens,
                    duration_ms,
                    int(success),
                    None if parse_success is None else int(parse_success),
                    None if validation_success is None else int(validation_success),
                    context_chars,
                    context_strategy,
                    requested_label,
                    provider_endpoint,
                    provider_fingerprint,
                    canonical_model_key,
                    identity_source,
                    float(identity_confidence or 0.0),
                    int(bool(manual_override)),
                    metadata_json or "{}",
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def update_llm_call(
        self,
        call_id: str,
        parse_success: bool | None = None,
        validation_success: bool | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> bool:
        """Update parse/validation outcomes for an existing LLM call."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT metadata_json FROM llm_calls WHERE call_id = ?",
                (call_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False

            metadata: dict[str, Any] = {}
            raw_metadata = row["metadata_json"] if row else None
            if raw_metadata:
                try:
                    metadata = json.loads(raw_metadata)
                except json.JSONDecodeError:
                    metadata = {}
            if metadata_updates:
                metadata.update(metadata_updates)

            cursor.execute(
                """
                UPDATE llm_calls
                SET parse_success = COALESCE(?, parse_success),
                    validation_success = COALESCE(?, validation_success),
                    metadata_json = ?
                WHERE call_id = ?
                """,
                (
                    None if parse_success is None else int(parse_success),
                    None if validation_success is None else int(validation_success),
                    json.dumps(metadata),
                    call_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def list_llm_calls(
        self,
        project_path: str | None = None,
        session_id: str | None = None,
        stage: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """List recorded LLM calls, optionally filtered."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM llm_calls WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if session_id:
                query += " AND session_id = ?"
                params.append(session_id)
            if stage:
                query += " AND stage = ?"
                params.append(stage)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def get_llm_stage_summary(self, project_path: str, limit: int = 10) -> list[dict]:
        """Aggregate LLM telemetry by stage for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    stage,
                    COUNT(*) AS call_count,
                    SUM(input_tokens + output_tokens) AS total_tokens,
                    AVG(context_chars) AS avg_context_chars,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count
                FROM llm_calls
                WHERE project_path = ?
                GROUP BY stage
                ORDER BY total_tokens DESC, call_count DESC
                LIMIT ?
                """,
                (project_path, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def upsert_workflow_rollup(
        self,
        project_path: str,
        workflow_name: str,
        stage: str,
        language: str,
        complexity: str,
        target_type: str,
        success_count: int = 0,
        total_tokens: int = 0,
        total_duration_ms: int = 0,
        valid_findings: int = 0,
        verified_fixes: int = 0,
        one_shot_verified_fixes: int = 0,
        high_critical_findings: int = 0,
        validation_successes: int = 0,
        last_session_id: str | None = None,
        run_increment: int = 1,
    ) -> int:
        """Incrementally update a workflow rollup bucket."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO workflow_rollups
                (
                    project_path, workflow_name, stage, language, complexity, target_type,
                    run_count, success_count, total_tokens, total_duration_ms, valid_findings,
                    verified_fixes, one_shot_verified_fixes, high_critical_findings,
                    validation_successes, last_session_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_path, workflow_name, stage, language, complexity, target_type)
                DO UPDATE SET
                    run_count = workflow_rollups.run_count + excluded.run_count,
                    success_count = workflow_rollups.success_count + excluded.success_count,
                    total_tokens = workflow_rollups.total_tokens + excluded.total_tokens,
                    total_duration_ms = workflow_rollups.total_duration_ms + excluded.total_duration_ms,
                    valid_findings = workflow_rollups.valid_findings + excluded.valid_findings,
                    verified_fixes = workflow_rollups.verified_fixes + excluded.verified_fixes,
                    one_shot_verified_fixes =
                        workflow_rollups.one_shot_verified_fixes + excluded.one_shot_verified_fixes,
                    high_critical_findings =
                        workflow_rollups.high_critical_findings + excluded.high_critical_findings,
                    validation_successes =
                        workflow_rollups.validation_successes + excluded.validation_successes,
                    last_session_id = excluded.last_session_id,
                    updated_at = excluded.updated_at
                """,
                (
                    project_path,
                    workflow_name,
                    stage,
                    language,
                    complexity,
                    target_type,
                    run_increment,
                    success_count,
                    total_tokens,
                    total_duration_ms,
                    valid_findings,
                    verified_fixes,
                    one_shot_verified_fixes,
                    high_critical_findings,
                    validation_successes,
                    last_session_id,
                    now,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_workflow_rollups(
        self,
        project_path: str,
        stage: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List workflow rollup buckets for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM workflow_rollups WHERE project_path = ?"
            params: list[Any] = [project_path]
            if stage:
                query += " AND stage = ?"
                params.append(stage)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def insert_optimization_decision(
        self,
        project_path: str,
        decision_type: str,
        decision_scope: str,
        comparable_key: str,
        recommendation_json: str,
        applied: bool = False,
        confidence: float = 0.0,
        outcome_json: str | None = None,
    ) -> int:
        """Insert an optimization recommendation or applied decision."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO optimization_decisions
                (
                    project_path, created_at, decision_type, decision_scope, comparable_key,
                    recommendation_json, applied, confidence, outcome_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    decision_type,
                    decision_scope,
                    comparable_key,
                    recommendation_json,
                    int(applied),
                    confidence,
                    outcome_json or "{}",
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_optimization_decisions(
        self,
        project_path: str,
        decision_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List optimization decisions for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM optimization_decisions WHERE project_path = ?"
            params: list[Any] = [project_path]
            if decision_type:
                query += " AND decision_type = ?"
                params.append(decision_type)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def upsert_external_benchmark_session(
        self,
        project_path: str,
        provider: str,
        external_session_id: str,
        source_path: str,
        normalized_project_path: str,
        project_hint: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        metadata_json: str | None = None,
    ) -> int:
        """Insert or update an external benchmark session and return its id."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO external_benchmark_sessions
                (
                    project_path, provider, external_session_id, source_path, project_hint,
                    normalized_project_path, started_at, ended_at, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_path, provider, external_session_id)
                DO UPDATE SET
                    source_path = excluded.source_path,
                    project_hint = excluded.project_hint,
                    normalized_project_path = excluded.normalized_project_path,
                    started_at = excluded.started_at,
                    ended_at = excluded.ended_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    project_path,
                    provider,
                    external_session_id,
                    source_path,
                    project_hint,
                    normalized_project_path,
                    started_at,
                    ended_at,
                    metadata_json or "{}",
                    now,
                ),
            )
            cursor.execute(
                """
                SELECT id FROM external_benchmark_sessions
                WHERE project_path = ? AND provider = ? AND external_session_id = ?
                """,
                (project_path, provider, external_session_id),
            )
            row = cursor.fetchone()
            conn.commit()
            return int(row["id"]) if row else 0
        finally:
            if conn:
                conn.close()

    def insert_external_benchmark_turn(
        self,
        benchmark_session_id: int,
        timestamp: str,
        category: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_tokens: int,
        reasoning_tokens: int,
        retry_count: int,
        success_signal: bool,
        token_cost: int,
        tool_names_json: str,
        metadata_json: str,
        dedup_key: str,
    ) -> int:
        """Insert an external benchmark turn if it has not been imported yet."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO external_benchmark_turns
                (
                    benchmark_session_id, timestamp, category, model, input_tokens,
                    output_tokens, cache_tokens, reasoning_tokens, retry_count,
                    success_signal, token_cost, tool_names_json, metadata_json, dedup_key
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    benchmark_session_id,
                    timestamp,
                    category,
                    model,
                    input_tokens,
                    output_tokens,
                    cache_tokens,
                    reasoning_tokens,
                    retry_count,
                    int(success_signal),
                    token_cost,
                    tool_names_json,
                    metadata_json,
                    dedup_key,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_external_benchmark_sessions(
        self,
        project_path: str,
        provider: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List imported benchmark sessions for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM external_benchmark_sessions WHERE project_path = ?"
            params: list[Any] = [project_path]
            if provider:
                query += " AND provider = ?"
                params.append(provider)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def insert_token_savings_entry(
        self,
        project_path: str,
        session_id: str,
        stage: str,
        workflow_name: str | None,
        comparable_key: str,
        actual_tokens: int,
        delta_tokens: int,
        confidence: float,
        realized: bool,
        estimation_type: str,
        baseline_tokens: int | None = None,
        metadata_json: str | None = None,
    ) -> int:
        """Insert an observed or estimated token savings row."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO token_savings_ledger
                (
                    project_path, created_at, session_id, stage, workflow_name,
                    comparable_key, baseline_tokens, actual_tokens, delta_tokens,
                    confidence, realized, estimation_type, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    datetime.now().isoformat(),
                    session_id,
                    stage,
                    workflow_name,
                    comparable_key,
                    baseline_tokens,
                    actual_tokens,
                    delta_tokens,
                    confidence,
                    int(realized),
                    estimation_type,
                    metadata_json or "{}",
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

    def list_token_savings_entries(
        self,
        project_path: str,
        stage: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List token savings entries for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM token_savings_ledger WHERE project_path = ?"
            params: list[Any] = [project_path]
            if stage:
                query += " AND stage = ?"
                params.append(stage)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def get_token_savings_summary(self, project_path: str) -> dict[str, Any]:
        """Summarize token savings for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN delta_tokens > 0 THEN delta_tokens ELSE 0 END), 0) AS gross_saved,
                    COALESCE(SUM(CASE WHEN delta_tokens < 0 THEN ABS(delta_tokens) ELSE 0 END), 0) AS overspend,
                    COALESCE(SUM(delta_tokens), 0) AS net_saved,
                    COALESCE(AVG(confidence), 0.0) AS avg_confidence,
                    COUNT(*) AS entries,
                    COALESCE(
                        SUM(CASE WHEN estimation_type = 'observed' THEN 1 ELSE 0 END),
                        0
                    ) AS observed_entries
                FROM token_savings_ledger
                WHERE project_path = ?
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            return {
                "gross_tokens_saved": int(row["gross_saved"]) if row else 0,
                "overspend_tokens": int(row["overspend"]) if row else 0,
                "net_tokens_saved": int(row["net_saved"]) if row else 0,
                "confidence": float(row["avg_confidence"]) if row else 0.0,
                "entries": int(row["entries"]) if row else 0,
                "observed_entries": int(row["observed_entries"]) if row else 0,
            }
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Shadow job helpers (project-local background work - W3-A)
    # -------------------------------------------------------------------------

    def insert_shadow_job(
        self,
        project_path: str,
        job_id: str,
        target_path: str,
        mode: str,
        intensity: str,
        execution_mode: str = "local",
        changed_files_json: str | None = None,
        timeout_seconds: int = 300,
        token_budget: int | None = None,
        workflow_name: str | None = None,
        worktree_path: str | None = None,
        base_branch: str | None = None,
        artifact_dir: str | None = None,
        scope_json: str | None = None,
        heartbeat_at: str | None = None,
        worker_pid: int | None = None,
        worker_host: str | None = None,
    ) -> int:
        """Insert a row into the shadow_jobs table. Returns the row ID."""

        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO shadow_jobs
                (project_path, job_id, target_path, mode, intensity, status, created_at,
                 changed_files_json, timeout_seconds, token_budget, execution_mode, workflow_name,
                 worktree_path, base_branch, artifact_dir, scope_json, heartbeat_at, worker_pid,
                 worker_host)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_path,
                    job_id,
                    target_path,
                    mode,
                    intensity,
                    "pending",
                    datetime.now().isoformat(),
                    changed_files_json,
                    timeout_seconds,
                    token_budget,
                    execution_mode,
                    workflow_name,
                    worktree_path,
                    base_branch,
                    artifact_dir,
                    scope_json,
                    heartbeat_at,
                    worker_pid,
                    worker_host,
                ),
            )
            return cursor.lastrowid or 0

        return int(self._run_write_transaction(operation))

    def get_shadow_job(self, job_id: str) -> dict | None:
        """Get a shadow job by job_id."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM shadow_jobs WHERE job_id = ?", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            if conn:
                conn.close()

    def list_shadow_jobs(
        self,
        project_path: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List shadow jobs, optionally filtered by project_path and status."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM shadow_jobs WHERE 1=1"
            params: list[Any] = []
            if project_path:
                query += " AND project_path = ?"
                params.append(project_path)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def get_pending_shadow_jobs(self, project_path: str) -> list[dict]:
        """Get all pending shadow jobs for a project."""
        return self.list_shadow_jobs(project_path=project_path, status="pending")

    def get_active_shadow_jobs(self, project_path: str) -> list[dict]:
        """Get all active (pending or running) shadow jobs for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM shadow_jobs
                WHERE project_path = ? AND status IN ('pending', 'running')
                ORDER BY created_at ASC
                """,
                (project_path,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if conn:
                conn.close()

    def update_shadow_job_status(
        self,
        job_id: str,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        result: str | None = None,
        error_message: str | None = None,
        execution_mode: str | None = None,
        workflow_name: str | None = None,
        worktree_path: str | None = None,
        base_branch: str | None = None,
        artifact_dir: str | None = None,
        scope_json: str | None = None,
        heartbeat_at: str | None = None,
        worker_pid: int | None = None,
        worker_host: str | None = None,
    ) -> bool:
        """Update status and related fields of a shadow job."""

        def operation(conn: sqlite3.Connection) -> bool:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE shadow_jobs
                SET status = ?, started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at),
                    result = COALESCE(?, result),
                    error_message = ?,
                    execution_mode = COALESCE(?, execution_mode),
                    workflow_name = COALESCE(?, workflow_name),
                    worktree_path = COALESCE(?, worktree_path),
                    base_branch = COALESCE(?, base_branch),
                    artifact_dir = COALESCE(?, artifact_dir),
                    scope_json = COALESCE(?, scope_json),
                    heartbeat_at = COALESCE(?, heartbeat_at),
                    worker_pid = COALESCE(?, worker_pid),
                    worker_host = COALESCE(?, worker_host)
                WHERE job_id = ?
                """,
                (
                    status,
                    started_at,
                    completed_at,
                    result,
                    error_message,
                    execution_mode,
                    workflow_name,
                    worktree_path,
                    base_branch,
                    artifact_dir,
                    scope_json,
                    heartbeat_at,
                    worker_pid,
                    worker_host,
                    job_id,
                ),
            )
            return cursor.rowcount > 0

        return bool(self._run_write_transaction(operation))

    def reap_stale_shadow_jobs(
        self,
        project_path: str,
        stale_before: str,
        *,
        worker_host: str | None = None,
    ) -> int:
        """Mark stale running jobs failed so workers can recover cleanly."""

        def operation(conn: sqlite3.Connection) -> int:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE shadow_jobs
                SET status = 'failed',
                    completed_at = ?,
                    error_message = COALESCE(error_message, ?)
                WHERE project_path = ?
                  AND status = 'running'
                  AND COALESCE(heartbeat_at, started_at, created_at) < ?
                  AND (? IS NULL OR worker_host = ?)
                """,
                (
                    datetime.now().isoformat(),
                    "Worker heartbeat expired; job marked orphaned for recovery",
                    project_path,
                    stale_before,
                    worker_host,
                    worker_host,
                ),
            )
            return cursor.rowcount

        return int(self._run_write_transaction(operation))

    def remove_shadow_job(self, job_id: str) -> bool:
        """Delete a shadow job by job_id."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM shadow_jobs WHERE job_id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

    def clear_completed_shadow_jobs(self, project_path: str) -> int:
        """Delete all completed/failed/cancelled shadow jobs for a project. Returns count deleted."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM shadow_jobs
                WHERE project_path = ? AND status IN ('completed', 'failed', 'cancelled')
                """,
                (project_path,),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Schema info
    # -------------------------------------------------------------------------

    def get_schema_version(self) -> str | None:
        """Return the current schema version, or None if not set."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT version FROM schema_version ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            return row["version"] if row else None
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Statistics helpers
    # -------------------------------------------------------------------------

    def get_statistics(self, project_path: str) -> dict:
        """Get overall statistics for a project."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            stats = {}

            # Task stats
            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(token_cost) as total_tokens,
                       SUM(duration_ms) as total_duration
                FROM tasks WHERE project_path = ?
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            stats["total_tasks"] = row["total"] if row else 0
            stats["total_tokens"] = row["total_tokens"] if row else 0
            stats["total_duration_ms"] = row["total_duration"] if row else 0

            # Review stats
            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(findings_count) as total_findings,
                       SUM(token_cost) as total_tokens
                FROM review_runs WHERE project_path = ?
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            stats["total_reviews"] = row["total"] if row else 0
            stats["total_findings"] = row["total_findings"] if row else 0
            stats["review_tokens"] = row["total_tokens"] if row else 0

            # Learned rules stats
            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(recurrence_count) as total_triggers,
                       AVG(success_rate) as avg_success
                FROM learned_rules WHERE project_path = ?
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            stats["total_learned_rules"] = row["total"] if row else 0
            stats["total_rule_triggers"] = row["total_triggers"] if row else 0
            stats["avg_rule_success_rate"] = row["avg_success"] if row else 0.0

            # Skills and agents
            cursor.execute(
                "SELECT COUNT(*) FROM skills WHERE project_path = ?",
                (project_path,),
            )
            row = cursor.fetchone()
            stats["total_skills"] = row[0] if row else 0

            cursor.execute(
                "SELECT COUNT(*) FROM agents WHERE project_path = ?",
                (project_path,),
            )
            row = cursor.fetchone()
            stats["total_agents"] = row[0] if row else 0

            cursor.execute(
                "SELECT COUNT(*) FROM related_project_links WHERE project_path = ? AND status = 'active'",
                (project_path,),
            )
            row = cursor.fetchone()
            stats["related_projects"] = row[0] if row else 0

            cursor.execute(
                "SELECT COUNT(*) FROM related_project_links WHERE project_path = ? AND status = 'active' AND link_mode = 'attach'",
                (project_path,),
            )
            row = cursor.fetchone()
            stats["attached_projects"] = row[0] if row else 0

            cursor.execute(
                "SELECT COUNT(*) FROM transferred_lessons WHERE project_path = ?",
                (project_path,),
            )
            row = cursor.fetchone()
            stats["transferred_lessons"] = row[0] if row else 0

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM transferred_lessons
                WHERE project_path = ? AND validation_status = 'validated'
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            stats["validated_transferred_lessons"] = row[0] if row else 0

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM transferred_lessons
                WHERE project_path = ? AND validation_status = 'promoted'
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            stats["promoted_transferred_lessons"] = row[0] if row else 0

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM transferred_lessons
                WHERE project_path = ? AND validation_status = 'archived'
                """,
                (project_path,),
            )
            row = cursor.fetchone()
            stats["archived_transferred_lessons"] = row[0] if row else 0

            cursor.execute(
                "SELECT COUNT(*) FROM lesson_usage_events WHERE project_path = ?",
                (project_path,),
            )
            row = cursor.fetchone()
            stats["lesson_usage_events"] = row[0] if row else 0

            return stats
        finally:
            if conn:
                conn.close()
