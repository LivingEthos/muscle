"""
Migration 0011: Add canonical model identity fields to llm call telemetry.

Adds first-class columns to llm_calls so requested and resolved model identity
can be queried without unpacking metadata JSON.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

LLM_CALL_IDENTITY_COLUMNS: dict[str, str] = {
    "requested_label": "TEXT",
    "provider_endpoint": "TEXT",
    "provider_fingerprint": "TEXT",
    "canonical_model_key": "TEXT",
    "identity_source": "TEXT NOT NULL DEFAULT 'unresolved'",
    "identity_confidence": "REAL NOT NULL DEFAULT 0.0",
    "manual_override": "INTEGER NOT NULL DEFAULT 0",
}


def _llm_calls_exists(cursor: sqlite3.Cursor) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'llm_calls' LIMIT 1"
    )
    return cursor.fetchone() is not None


def _existing_columns(cursor: sqlite3.Cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]) for row in cursor.fetchall()}


def _rebuild_llm_calls_without_identity_columns(cursor: sqlite3.Cursor) -> None:
    cursor.execute("ALTER TABLE llm_calls RENAME TO llm_calls_with_identity")
    cursor.execute(
        """
        CREATE TABLE llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            call_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            workflow_name TEXT,
            review_mode TEXT,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            parse_success INTEGER,
            validation_success INTEGER,
            context_chars INTEGER NOT NULL DEFAULT 0,
            context_strategy TEXT NOT NULL DEFAULT 'default',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO llm_calls (
            id,
            project_path,
            created_at,
            call_id,
            session_id,
            stage,
            workflow_name,
            review_mode,
            model,
            input_tokens,
            output_tokens,
            duration_ms,
            success,
            parse_success,
            validation_success,
            context_chars,
            context_strategy,
            metadata_json
        )
        SELECT
            id,
            project_path,
            created_at,
            call_id,
            session_id,
            stage,
            workflow_name,
            review_mode,
            model,
            input_tokens,
            output_tokens,
            duration_ms,
            success,
            parse_success,
            validation_success,
            context_chars,
            context_strategy,
            metadata_json
        FROM llm_calls_with_identity
        """
    )
    cursor.execute("DROP TABLE llm_calls_with_identity")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_project_stage ON llm_calls(project_path, stage)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_project_session "
        "ON llm_calls(project_path, session_id)"
    )


def ensure_llm_call_model_identity_schema(conn: sqlite3.Connection) -> None:
    """Repair llm_calls to include canonical model identity columns and indexes."""
    cursor = conn.cursor()
    if not _llm_calls_exists(cursor):
        conn.commit()
        return

    existing_columns = _existing_columns(cursor, "llm_calls")
    for column_name, column_sql in LLM_CALL_IDENTITY_COLUMNS.items():
        if column_name in existing_columns:
            continue
        cursor.execute(f"ALTER TABLE llm_calls ADD COLUMN {column_name} {column_sql}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_calls_project_canonical_model "
        "ON llm_calls(project_path, canonical_model_key, stage)"
    )
    conn.commit()


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0011."""
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
        ("1.9.1",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    ensure_llm_call_model_identity_schema(conn)
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.9.1", datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0011."""
    cursor = conn.cursor()
    if _llm_calls_exists(cursor):
        existing_columns = _existing_columns(cursor, "llm_calls")
        if any(column in existing_columns for column in LLM_CALL_IDENTITY_COLUMNS):
            cursor.execute("DROP INDEX IF EXISTS idx_llm_calls_project_canonical_model")
            _rebuild_llm_calls_without_identity_columns(cursor)
    cursor.execute("DELETE FROM schema_version WHERE version = ?", ("1.9.1",))
    conn.commit()
