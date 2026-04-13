"""
Migration 0007: Extend shadow_jobs with workflow and worktree metadata.

Adds metadata fields required by the Archon-inspired review workflow v1:
- workflow_name
- worktree_path
- base_branch
- artifact_dir
- scope_json

Idempotent: Checks if schema_version 1.6.0 is already applied before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

NEW_COLUMNS = [
    ("workflow_name", "TEXT"),
    ("worktree_path", "TEXT"),
    ("base_branch", "TEXT"),
    ("artifact_dir", "TEXT"),
    ("scope_json", "TEXT"),
]


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0007."""
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
        ("1.6.0",),
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
        ("1.6.0", datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0007 by removing the version marker only.

    SQLite does not support dropping columns without table rebuild, so rollback is best-effort.
    """
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.6.0",),
    )
    conn.commit()
