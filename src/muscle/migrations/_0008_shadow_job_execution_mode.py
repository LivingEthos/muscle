"""
Migration 0008: Persist requested execution mode for shadow jobs.

Adds the execution_mode column so queued shadow jobs keep the user's resolved
`local` vs `worktree` preference at submission time.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0008."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.7.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    cursor.execute("PRAGMA table_info(shadow_jobs)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "execution_mode" not in existing_columns:
        cursor.execute(
            "ALTER TABLE shadow_jobs ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'local'"
        )

    cursor.execute(
        """
        UPDATE shadow_jobs
        SET execution_mode = COALESCE(execution_mode, 'local')
        """
    )
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.7.0", datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0008 by removing the version marker only."""
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.7.0",),
    )
    conn.commit()
