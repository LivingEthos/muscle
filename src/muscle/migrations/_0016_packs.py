"""
Migration 0016: Add packs table (Phase B.5 distilled context packets).

Stores metadata for content-addressed task-context packs. Pack bodies live
on disk under ``.muscle/packs/<id>.md`` — this table tracks ids and paths so
that a pack can be looked up by id and garbage-collected by age.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

VERSION = "1.9.6"

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS packs (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    task TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_packs_created ON packs(created_at);
"""


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0016 — create packs table."""
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

    cursor.executescript(MIGRATION_SQL)

    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (VERSION, datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0016 — drop packs table and version marker."""
    cursor = conn.cursor()
    cursor.execute("DROP INDEX IF EXISTS idx_packs_created")
    cursor.execute("DROP TABLE IF EXISTS packs")
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        (VERSION,),
    )
    conn.commit()
