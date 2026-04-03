"""
Migration 0005: Add shadow_jobs table for project-local background job tracking (W3-A).

Adds background job tracking to project_memory.db so each project has its own
job state instead of sharing a global ~/.muscle/shadow_jobs.json file.

Idempotent: Checks if schema_version 1.4.0 is already applied before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def migrate(conn: sqlite3.Connection) -> bool:
    """
    Apply migration 0005.

    Creates the shadow_jobs table and indexes for project-local background job tracking.

    Returns True if migration was applied, False if it was already applied.
    """
    cursor = conn.cursor()

    # Ensure schema_version table exists first (for idempotency check)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )

    # Check if already migrated
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.4.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    # Create shadow_jobs table
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shadow_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            job_id TEXT NOT NULL UNIQUE,
            target_path TEXT NOT NULL,
            mode TEXT NOT NULL,
            intensity TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            error_message TEXT,
            changed_files_json TEXT,
            timeout_seconds INTEGER NOT NULL DEFAULT 300,
            token_budget INTEGER
        )
        """
    )

    # Create indexes for common queries
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shadow_jobs_project_path
        ON shadow_jobs(project_path)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shadow_jobs_status
        ON shadow_jobs(status)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shadow_jobs_project_status
        ON shadow_jobs(project_path, status)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shadow_jobs_created_at
        ON shadow_jobs(created_at)
        """
    )

    # Record schema version
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.4.0", datetime.now().isoformat()),
    )

    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """
    Rollback migration 0005.
    """
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.4.0",),
    )
    if cursor.fetchone()[0] == 0:
        return

    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.4.0",),
    )
    cursor.execute("DROP TABLE IF EXISTS shadow_jobs")

    conn.commit()
