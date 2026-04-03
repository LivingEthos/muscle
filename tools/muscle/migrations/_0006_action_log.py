"""
Migration 0006: Action log for operator audit trail (v1.5.0).

Creates an action_log table that records key MUSCLE operations:
- publish: when CLAUDE.md is published
- backup/restore: when backups are created/restored
- skill_create/revise/archive: for skills
- agent_create/revise/archive: for agents

Idempotent: Checks if schema_version 1.5.0 is already applied before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def migrate(conn: sqlite3.Connection) -> bool:
    """
    Apply migration 0006.

    Creates the action_log table and indices.

    Returns True if migration was applied, False if it was already applied.
    """
    cursor = conn.cursor()

    # Check if already migrated
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.5.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            action_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            details_json TEXT NOT NULL DEFAULT '{}',
            actor TEXT NOT NULL DEFAULT 'muscle'
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_log_project_path ON action_log(project_path)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_log_action_type ON action_log(action_type)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_action_log_created_at ON action_log(created_at)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_log_entity ON action_log(entity_type, entity_id)"
    )

    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.5.0", datetime.now().isoformat()),
    )

    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0006."""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.5.0",),
    )
    if cursor.fetchone()[0] == 0:
        return

    cursor.execute("DELETE FROM schema_version WHERE version = ?", ("1.5.0",))
    cursor.execute("DROP TABLE IF EXISTS action_log")

    conn.commit()
