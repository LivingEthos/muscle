"""
Migration 0017: Add metadata_json to delegation_events.

Extends delegation observability without introducing a separate metrics store.
Structured route, verification, and token-savings signals now live alongside
each delegation event.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

VERSION = "1.9.7"


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0017 — add metadata_json to delegation_events."""
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
        (VERSION,),
    )
    if cursor.fetchone()[0] > 0:
        return False

    existing_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(delegation_events)").fetchall()
    }
    if "metadata_json" not in existing_columns:
        cursor.execute(
            "ALTER TABLE delegation_events ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
        )

    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (VERSION, datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0017 marker.

    SQLite cannot drop columns in place; keep the column but remove the version
    marker so older code paths still operate safely on the superset schema.
    """
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        (VERSION,),
    )
    conn.commit()
