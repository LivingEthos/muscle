"""
ProjectMemory - Unified SQLite access layer for the per-project memory database (MUS-010).

Architecture Decision Record (ADR):
- Single SQLite file per project at `.muscle/project_memory.db`
- Tables created and managed via migration framework (MUS-011)
- Typed helpers for inserts, queries
- Supports safe schema upgrades via MigrationRunner
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .migrations import MigrationRunner

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_MEMORY_PATH = ".muscle/project_memory.db"


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
        """Return a connection with row factory enabled."""
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database by running all pending migrations."""
        try:
            runner = MigrationRunner(str(self.project_path), str(self._db_path))
            runner.run()
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
            if action_type:
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
                ON CONFLICT(state_key) DO UPDATE SET
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

    def get_automation_state(self, state_key: str) -> dict | None:
        """Get an automation state by key."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM automation_state WHERE state_key = ?",
                (state_key,),
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
    # Shadow job helpers (project-local background work - W3-A)
    # -------------------------------------------------------------------------

    def insert_shadow_job(
        self,
        project_path: str,
        job_id: str,
        target_path: str,
        mode: str,
        intensity: str,
        changed_files_json: str | None = None,
        timeout_seconds: int = 300,
        token_budget: int | None = None,
    ) -> int:
        """Insert a row into the shadow_jobs table. Returns the row ID."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO shadow_jobs
                (project_path, job_id, target_path, mode, intensity, status, created_at,
                 changed_files_json, timeout_seconds, token_budget)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            if conn:
                conn.close()

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
    ) -> bool:
        """Update status and related fields of a shadow job."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE shadow_jobs
                SET status = ?, started_at = COALESCE(?, started_at),
                    completed_at = COALESCE(?, completed_at),
                    result = COALESCE(?, result),
                    error_message = ?
                WHERE job_id = ?
                """,
                (status, started_at, completed_at, result, error_message, job_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            if conn:
                conn.close()

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

            return stats
        finally:
            if conn:
                conn.close()
