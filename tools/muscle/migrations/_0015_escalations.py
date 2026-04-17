"""
Migration 0015: Add escalations table.

Records escalation events when MUSCLE's M2.7 agents exhaust their retry budget
and problems must be kicked to the host planner model (Claude Code / Codex).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

VERSION = "1.9.5"

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS escalations (
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
);
CREATE INDEX IF NOT EXISTS idx_escalations_session ON escalations(session_id);
CREATE INDEX IF NOT EXISTS idx_escalations_unresolved ON escalations(resolved, created_at);
"""


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0015 — create escalations table."""
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
    """Rollback migration 0015 — drop table and version marker."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS escalations")
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        (VERSION,),
    )
    conn.commit()
