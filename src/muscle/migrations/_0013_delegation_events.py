"""
Migration 0013: Add delegation_events table for observability.

Records per-delegation cost and outcome data so `muscle cost --delegation-report`
can surface host-model tokens avoided, cache hit rates, and escalation rates.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

VERSION = "1.9.3"

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS delegation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    task_tier TEXT,
    entry_point TEXT NOT NULL,
    m27_tokens_in INTEGER DEFAULT 0,
    m27_tokens_out INTEGER DEFAULT 0,
    m27_usd_cents INTEGER DEFAULT 0,
    verifications_run INTEGER DEFAULT 0,
    verifications_failed INTEGER DEFAULT 0,
    escalations_emitted INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    cache_tokens_saved INTEGER DEFAULT 0,
    pack_id TEXT,
    pack_reused INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_delegation_events_session
    ON delegation_events(session_id);
CREATE INDEX IF NOT EXISTS idx_delegation_events_created
    ON delegation_events(created_at);
"""


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0013 — create delegation_events table."""
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
    """Rollback migration 0013 — drop table and version marker."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS delegation_events")
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        (VERSION,),
    )
    conn.commit()
