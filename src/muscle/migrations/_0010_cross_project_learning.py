"""
Migration 0010: Add cross-project learning and model-identity tables.

Adds:
- related_project_links
- transferred_lessons
- model_identity_history
- lesson_usage_events
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def _ensure_cross_project_learning_tables(cursor: sqlite3.Cursor) -> None:
    """Create cross-project learning tables and indexes if they are missing."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS related_project_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            source_project_path TEXT NOT NULL,
            link_mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            relatedness_score REAL NOT NULL DEFAULT 0.0,
            fingerprint_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_synced_at TEXT,
            UNIQUE(project_path, source_project_path, link_mode)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS transferred_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            source_project_path TEXT NOT NULL,
            source_rule_id INTEGER,
            lesson_key TEXT NOT NULL,
            lesson_text TEXT NOT NULL,
            trigger_pattern TEXT NOT NULL,
            link_mode TEXT NOT NULL DEFAULT 'snapshot',
            validation_status TEXT NOT NULL DEFAULT 'provisional',
            validation_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            scope_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            imported_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            promoted_rule_id INTEGER,
            UNIQUE(project_path, lesson_key, source_project_path)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS model_identity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            requested_label TEXT,
            provider_endpoint TEXT,
            provider_fingerprint TEXT,
            canonical_model_key TEXT,
            identity_source TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            manual_override INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS lesson_usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            session_id TEXT,
            call_id TEXT,
            stage TEXT NOT NULL,
            lesson_source TEXT NOT NULL,
            lesson_key TEXT NOT NULL,
            canonical_model_key TEXT,
            source_project_path TEXT,
            outcome TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    index_statements = [
        (
            "idx_related_project_links_project",
            "CREATE INDEX IF NOT EXISTS idx_related_project_links_project "
            "ON related_project_links(project_path, status, relatedness_score DESC)",
        ),
        (
            "idx_transferred_lessons_project",
            "CREATE INDEX IF NOT EXISTS idx_transferred_lessons_project "
            "ON transferred_lessons(project_path, validation_status, link_mode)",
        ),
        (
            "idx_transferred_lessons_source",
            "CREATE INDEX IF NOT EXISTS idx_transferred_lessons_source "
            "ON transferred_lessons(source_project_path, source_rule_id)",
        ),
        (
            "idx_model_identity_history_project",
            "CREATE INDEX IF NOT EXISTS idx_model_identity_history_project "
            "ON model_identity_history(project_path, created_at DESC)",
        ),
        (
            "idx_lesson_usage_events_session",
            "CREATE INDEX IF NOT EXISTS idx_lesson_usage_events_session "
            "ON lesson_usage_events(project_path, session_id, stage)",
        ),
    ]
    for _index_name, statement in index_statements:
        cursor.execute(statement)


def ensure_cross_project_learning_schema(conn: sqlite3.Connection) -> None:
    """Repair cross-project learning tables for drifted databases."""
    cursor = conn.cursor()
    _ensure_cross_project_learning_tables(cursor)
    conn.commit()


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0010."""
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
        ("1.9.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    _ensure_cross_project_learning_tables(cursor)
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.9.0", datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0010."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS lesson_usage_events")
    cursor.execute("DROP TABLE IF EXISTS model_identity_history")
    cursor.execute("DROP TABLE IF EXISTS transferred_lessons")
    cursor.execute("DROP TABLE IF EXISTS related_project_links")
    cursor.execute("DELETE FROM schema_version WHERE version = ?", ("1.9.0",))
    conn.commit()
