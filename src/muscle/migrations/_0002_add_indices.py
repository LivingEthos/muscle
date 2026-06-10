"""
Migration 0002: Add additional performance indices and enhance existing tables (v1.1.0).

This migration adds composite indices for common query patterns and
introduces any schema enhancements identified after initial deployment.

Idempotent: Checks if schema_version 1.1.0 is already applied before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def migrate(conn: sqlite3.Connection) -> bool:
    """
    Apply migration 0002.

    Adds composite indices for common query patterns and
    any schema enhancements.

    Returns True if migration was applied, False if it was already applied.
    """
    cursor = conn.cursor()

    # Check if already migrated
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.1.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    # Check if the source tables exist (migration 0001 must be applied first)
    # We check for 'tasks' table since it should exist after v1 is applied
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='tasks'",
    )
    if cursor.fetchone()[0] == 0:
        raise RuntimeError(
            "Migration 0001 (initial schema) must be applied before 0002. Cannot find tasks table."
        )

    # Add composite index for task lookups by project and status
    _create_index(
        cursor,
        "idx_tasks_project_status",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_path, status)",
    )

    # Add composite index for review findings by severity and auto_fixable
    _create_index(
        cursor,
        "idx_review_findings_severity_auto_fixable",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_severity_auto_fixable "
        "ON review_findings(severity, auto_fixable)",
    )

    # Add composite index for learned_rules by project and status
    _create_index(
        cursor,
        "idx_learned_rules_project_status",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_project_status "
        "ON learned_rules(project_path, status)",
    )

    # Add composite index for skills by project and status
    _create_index(
        cursor,
        "idx_skills_project_status",
        "CREATE INDEX IF NOT EXISTS idx_skills_project_status ON skills(project_path, status)",
    )

    # Add composite index for agents by project and status
    _create_index(
        cursor,
        "idx_agents_project_status",
        "CREATE INDEX IF NOT EXISTS idx_agents_project_status ON agents(project_path, status)",
    )

    # Add composite index for project_notes by project and category
    _create_index(
        cursor,
        "idx_project_notes_project_category",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_project_category "
        "ON project_notes(project_path, category)",
    )

    # Add composite index for memory_decisions by project and decision_type
    _create_index(
        cursor,
        "idx_memory_decisions_project_decision_type",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_project_decision_type "
        "ON memory_decisions(project_path, decision_type)",
    )

    # Add index for conversation_events by project and event_type
    _create_index(
        cursor,
        "idx_conversation_events_project_event_type",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_project_event_type "
        "ON conversation_events(project_path, event_type)",
    )

    # Add index for change_events by project and created_at for time-range queries
    _create_index(
        cursor,
        "idx_change_events_project_created",
        "CREATE INDEX IF NOT EXISTS idx_change_events_project_created "
        "ON change_events(project_path, created_at)",
    )

    # Add composite index for review_runs by project, mode, and created_at
    _create_index(
        cursor,
        "idx_review_runs_project_mode_created",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_project_mode_created "
        "ON review_runs(project_path, review_mode, created_at)",
    )

    # Add index for backups by project and created_at for retention queries
    _create_index(
        cursor,
        "idx_backups_project_created",
        "CREATE INDEX IF NOT EXISTS idx_backups_project_created "
        "ON backups(project_path, created_at)",
    )

    # Record schema version
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.1.0", datetime.now().isoformat()),
    )

    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """
    Rollback migration 0002.

    Removes the composite indices added by this migration.
    Data is preserved - only indices are dropped.
    """
    cursor = conn.cursor()

    # Check if this migration was applied
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.1.0",),
    )
    if cursor.fetchone()[0] == 0:
        return  # Migration not applied, nothing to rollback

    # Drop indices in reverse order of creation
    cursor.execute("DROP INDEX IF EXISTS idx_backups_project_created")
    cursor.execute("DROP INDEX IF EXISTS idx_review_runs_project_mode_created")
    cursor.execute("DROP INDEX IF EXISTS idx_change_events_project_created")
    cursor.execute("DROP INDEX IF EXISTS idx_conversation_events_project_event_type")
    cursor.execute("DROP INDEX IF EXISTS idx_memory_decisions_project_decision_type")
    cursor.execute("DROP INDEX IF EXISTS idx_project_notes_project_category")
    cursor.execute("DROP INDEX IF EXISTS idx_agents_project_status")
    cursor.execute("DROP INDEX IF EXISTS idx_skills_project_status")
    cursor.execute("DROP INDEX IF EXISTS idx_learned_rules_project_status")
    cursor.execute("DROP INDEX IF EXISTS idx_review_findings_severity_auto_fixable")
    cursor.execute("DROP INDEX IF EXISTS idx_tasks_project_status")

    # Remove schema version record
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.1.0",),
    )

    conn.commit()


def _create_index(cursor: Any, index_name: str, sql: str) -> None:
    """Execute a CREATE INDEX statement."""
    cursor.execute(sql)
