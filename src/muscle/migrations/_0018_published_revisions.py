"""
Migration 0018: Published-revision staging for two-phase CLAUDE.md/AGENTS.md publish.

Adds a published_revisions table that records the staged content of a host-doc
publish *before* the file is swapped on disk. The publish flow is:

  1. stage a row with status 'pending' (content + sha256 + target path)
  2. atomically swap the file (temp + fsync + os.replace)
  3. mark the row 'committed'

If a crash occurs between (2) and (3), the next publish detects the pending row,
compares the on-disk file hash to the staged hash, and either marks it
'committed' (swap happened) or 'aborted' (swap never happened, new publish
supersedes it). This keeps project_memory.db and the published file consistent.

Idempotent: checks schema_version before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

VERSION = "1.9.8"


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0018 — create published_revisions table and indices."""
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

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS published_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            target_path TEXT NOT NULL,
            content TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            committed_at TEXT
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_published_revisions_project_path "
        "ON published_revisions(project_path)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_published_revisions_status ON published_revisions(status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_published_revisions_target "
        "ON published_revisions(target_path)"
    )

    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (VERSION, datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0018 — drop published_revisions and remove the marker."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        (VERSION,),
    )
    if cursor.fetchone()[0] == 0:
        return

    cursor.execute("DELETE FROM schema_version WHERE version = ?", (VERSION,))
    cursor.execute("DROP TABLE IF EXISTS published_revisions")
    conn.commit()
