"""
Migration 0003: Skill lifecycle columns for DB-first skill management (v1.3.0).

Adds evidence_count, archived_at, revision, and reasoning columns to the skills
table to support DB-first skill lifecycle management:

- evidence_count: tracks how many times the skill's pattern was detected
- archived_at: timestamp when skill was archived (NULL = active)
- revision: revision number for version control
- reasoning: why the skill was created (evidence summary from memory_decisions)

Also adds composite indices for skill lifecycle queries.

Idempotent: Checks if schema_version 1.3.0 is already applied before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def migrate(conn: sqlite3.Connection) -> bool:
    """
    Apply migration 0003.

    Adds skill lifecycle columns and indices.

    Returns True if migration was applied, False if it was already applied.
    """
    cursor = conn.cursor()

    # Check if already migrated
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.3.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    # Check if the skills table exists (migration 0001 must be applied first)
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='skills'",
    )
    if cursor.fetchone()[0] == 0:
        raise RuntimeError(
            "Migration 0001 (initial schema) must be applied before 0003. Cannot find skills table."
        )

    # Add evidence_count column
    _add_column_if_not_exists(
        cursor,
        "skills",
        "evidence_count",
        "INTEGER NOT NULL DEFAULT 0",
    )

    # Add archived_at column
    _add_column_if_not_exists(
        cursor,
        "skills",
        "archived_at",
        "TEXT",
    )

    # Add revision column
    _add_column_if_not_exists(
        cursor,
        "skills",
        "revision",
        "INTEGER NOT NULL DEFAULT 1",
    )

    # Add reasoning column
    _add_column_if_not_exists(
        cursor,
        "skills",
        "reasoning",
        "TEXT NOT NULL DEFAULT ''",
    )

    # Add composite index for skill lifecycle queries
    _create_index(
        cursor,
        "idx_skills_evidence_count",
        "CREATE INDEX IF NOT EXISTS idx_skills_evidence_count ON skills(evidence_count)",
    )

    _create_index(
        cursor,
        "idx_skills_archived_at",
        "CREATE INDEX IF NOT EXISTS idx_skills_archived_at ON skills(archived_at)",
    )

    # Index for finding stale skills (active with low evidence)
    _create_index(
        cursor,
        "idx_skills_status_evidence",
        "CREATE INDEX IF NOT EXISTS idx_skills_status_evidence ON skills(status, evidence_count)",
    )

    # Record schema version
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.3.0", datetime.now().isoformat()),
    )

    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """
    Rollback migration 0003.

    Removes the lifecycle columns and indices added by this migration.
    Data in evidence_count, archived_at, revision, reasoning will be lost.
    """
    cursor = conn.cursor()

    # Check if this migration was applied
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.3.0",),
    )
    if cursor.fetchone()[0] == 0:
        return  # Migration not applied, nothing to rollback

    # Drop indices
    cursor.execute("DROP INDEX IF EXISTS idx_skills_status_evidence")
    cursor.execute("DROP INDEX IF EXISTS idx_skills_archived_at")
    cursor.execute("DROP INDEX IF EXISTS idx_skills_evidence_count")

    # Remove columns (SQLite does not support DROP COLUMN directly in older versions,
    # but we use a workaround via table rebuild for compatibility)
    _drop_column_if_exists(cursor, "skills", "reasoning")
    _drop_column_if_exists(cursor, "skills", "revision")
    _drop_column_if_exists(cursor, "skills", "archived_at")
    _drop_column_if_exists(cursor, "skills", "evidence_count")

    # Remove schema version record
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.3.0",),
    )

    conn.commit()


def _add_column_if_not_exists(cursor: Any, table: str, column: str, definition: str) -> None:
    """Add a column only if it does not already exist in the table."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _drop_column_if_exists(cursor: Any, table: str, column: str) -> None:
    """Drop a column if it exists (SQLite 3.35.0+)."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        return

    # SQLite 3.35.0+ supports DROP COLUMN
    try:
        cursor.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    except sqlite3.OperationalError:
        # For older SQLite, use table rebuild approach
        _rebuild_table_without_column(cursor, table, column)


def _rebuild_table_without_column(cursor: Any, table: str, column: str) -> None:
    """Rebuild table without the specified column (fallback for old SQLite)."""
    cursor.execute(f"SELECT * FROM {table} LIMIT 1")
    all_columns = [description[0] for description in cursor.description]
    keep_columns = [c for c in all_columns if c != column]

    col_list = ", ".join(keep_columns)
    temp_table = f"{table}_temp"

    cursor.execute(f"CREATE TABLE {temp_table} AS SELECT {col_list} FROM {table}")
    cursor.execute(f"DROP TABLE {table}")
    cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")


def _create_index(cursor: Any, index_name: str, sql: str) -> None:
    """Execute a CREATE INDEX statement."""
    cursor.execute(sql)
