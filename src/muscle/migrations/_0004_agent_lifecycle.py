"""
Migration 0004: Agent lifecycle management (v1.3.1).

Adds columns to the agents table for revision tracking and archival:
- revision_count: tracks how many times an agent has been revised
- archived_at: timestamp when agent was archived (NULL if active)
- revision_history_json: JSON array of past revisions with metadata

Also adds indexes for efficient querying of archived vs active agents.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def migrate(conn: sqlite3.Connection) -> bool:
    """
    Apply migration 0004.

    Adds agent lifecycle columns to the agents table.

    Returns True if migration was applied, False if it was already applied.
    """
    cursor = conn.cursor()

    # Check if already migrated
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.3.1",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='agents'",
    )
    if cursor.fetchone()[0] == 0:
        raise RuntimeError(
            "Migration 0001 (initial schema) must be applied before 0004. Cannot find agents table."
        )

    _add_column_if_not_exists(
        cursor,
        "agents",
        "revision_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_not_exists(cursor, "agents", "archived_at", "TEXT")
    _add_column_if_not_exists(cursor, "agents", "revision_history_json", "TEXT")

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agents_archived_at
        ON agents(archived_at)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agents_revision_count
        ON agents(revision_count)
        """
    )

    # Record schema version
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.3.1", datetime.now().isoformat()),
    )

    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """
    Rollback migration 0004.

    Removes the lifecycle columns from the agents table.
    Note: This drops data in those columns.
    """
    cursor = conn.cursor()

    # Check if this migration was applied
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.3.1",),
    )
    if cursor.fetchone()[0] == 0:
        return  # Migration not applied, nothing to rollback

    # Remove schema version record FIRST
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.3.1",),
    )

    # Drop indexes first
    cursor.execute("DROP INDEX IF EXISTS idx_agents_archived_at")
    cursor.execute("DROP INDEX IF EXISTS idx_agents_revision_count")

    # Recreate table without the new columns (SQLite doesn't support DROP COLUMN)
    # We need to: create temp table, copy data, drop old, rename temp
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agents_backup AS
        SELECT id, project_path, created_at, name, description, trigger_pattern,
               file_path, status, last_used, use_count
        FROM agents
    """)

    cursor.execute("DROP TABLE agents")

    cursor.execute("""
        CREATE TABLE agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            trigger_pattern TEXT NOT NULL,
            file_path TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            last_used TEXT,
            use_count INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        INSERT INTO agents
        (id, project_path, created_at, name, description, trigger_pattern,
         file_path, status, last_used, use_count)
        SELECT id, project_path, created_at, name, description, trigger_pattern,
               file_path, status, last_used, use_count
        FROM agents_backup
    """)

    cursor.execute("DROP TABLE agents_backup")

    conn.commit()


def _add_column_if_not_exists(cursor: Any, table: str, column: str, definition: str) -> None:
    """Add a column only if it does not already exist in the table."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
