"""
Migration 0012: Add liveness metadata for recoverable shadow jobs.

Adds heartbeat and worker identity fields so stale running jobs can be reaped
instead of remaining permanently stuck in the running state.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

NEW_COLUMNS = [
    ("heartbeat_at", "TEXT"),
    ("worker_pid", "INTEGER"),
    ("worker_host", "TEXT"),
]


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0012."""
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
        ("1.9.2",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    cursor.execute("PRAGMA table_info(shadow_jobs)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    for column_name, column_type in NEW_COLUMNS:
        if column_name in existing_columns:
            continue
        cursor.execute(f"ALTER TABLE shadow_jobs ADD COLUMN {column_name} {column_type}")

    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.9.2", datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0012 by removing the version marker only."""
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.9.2",),
    )
    conn.commit()
