"""
Migration 0009: Add project-local optimization and telemetry tables.

Adds:
- llm_calls
- workflow_rollups
- optimization_decisions
- external_benchmark_sessions
- external_benchmark_turns
- token_savings_ledger
"""

from __future__ import annotations

import sqlite3
from datetime import datetime


def _migrate_automation_state_scope(cursor: sqlite3.Cursor) -> None:
    """Upgrade automation_state to project-scoped keys."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_state_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state_key TEXT NOT NULL,
            state_value TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(project_path, state_key)
        )
        """
    )
    cursor.execute(
        """
        INSERT OR REPLACE INTO automation_state_new
        (project_path, created_at, state_key, state_value, updated_at)
        SELECT project_path, created_at, state_key, state_value, updated_at
        FROM automation_state
        """
    )
    cursor.execute("DROP TABLE automation_state")
    cursor.execute("ALTER TABLE automation_state_new RENAME TO automation_state")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_automation_state_project_key
        ON automation_state(project_path, state_key)
        """
    )


def _ensure_automation_state_scope(cursor: sqlite3.Cursor) -> None:
    """Ensure automation state uses project-scoped uniqueness."""
    cursor.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'automation_state'
        """
    )
    automation_state_sql_row = cursor.fetchone()
    automation_state_sql = automation_state_sql_row[0] if automation_state_sql_row else ""
    if automation_state_sql and "UNIQUE(project_path, state_key)" not in automation_state_sql:
        _migrate_automation_state_scope(cursor)


def _ensure_project_optimization_tables(cursor: sqlite3.Cursor) -> None:
    """Create optimization tables and indexes if they are missing."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_calls (
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
        CREATE TABLE IF NOT EXISTS workflow_rollups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            workflow_name TEXT NOT NULL,
            stage TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'unknown',
            complexity TEXT NOT NULL DEFAULT 'unknown',
            target_type TEXT NOT NULL DEFAULT 'unknown',
            run_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            total_duration_ms INTEGER NOT NULL DEFAULT 0,
            valid_findings INTEGER NOT NULL DEFAULT 0,
            verified_fixes INTEGER NOT NULL DEFAULT 0,
            one_shot_verified_fixes INTEGER NOT NULL DEFAULT 0,
            high_critical_findings INTEGER NOT NULL DEFAULT 0,
            validation_successes INTEGER NOT NULL DEFAULT 0,
            last_session_id TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(project_path, workflow_name, stage, language, complexity, target_type)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS optimization_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decision_type TEXT NOT NULL,
            decision_scope TEXT NOT NULL,
            comparable_key TEXT NOT NULL,
            recommendation_json TEXT NOT NULL DEFAULT '{}',
            applied INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0.0,
            outcome_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS external_benchmark_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            provider TEXT NOT NULL,
            external_session_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            project_hint TEXT,
            normalized_project_path TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(project_path, provider, external_session_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS external_benchmark_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_session_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            category TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_tokens INTEGER NOT NULL DEFAULT 0,
            reasoning_tokens INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            success_signal INTEGER NOT NULL DEFAULT 0,
            token_cost INTEGER NOT NULL DEFAULT 0,
            tool_names_json TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            dedup_key TEXT NOT NULL UNIQUE,
            FOREIGN KEY (benchmark_session_id) REFERENCES external_benchmark_sessions(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS token_savings_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            workflow_name TEXT,
            comparable_key TEXT NOT NULL,
            baseline_tokens INTEGER,
            actual_tokens INTEGER NOT NULL,
            delta_tokens INTEGER NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            realized INTEGER NOT NULL DEFAULT 0,
            estimation_type TEXT NOT NULL DEFAULT 'estimated',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    index_statements = [
        (
            "idx_llm_calls_project_stage",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_project_stage "
            "ON llm_calls(project_path, stage)",
        ),
        (
            "idx_llm_calls_project_session",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_project_session "
            "ON llm_calls(project_path, session_id)",
        ),
        (
            "idx_workflow_rollups_project",
            "CREATE INDEX IF NOT EXISTS idx_workflow_rollups_project "
            "ON workflow_rollups(project_path, workflow_name)",
        ),
        (
            "idx_optimization_decisions_project",
            "CREATE INDEX IF NOT EXISTS idx_optimization_decisions_project "
            "ON optimization_decisions(project_path, created_at)",
        ),
        (
            "idx_external_benchmark_sessions_project",
            "CREATE INDEX IF NOT EXISTS idx_external_benchmark_sessions_project "
            "ON external_benchmark_sessions(project_path, provider)",
        ),
        (
            "idx_external_benchmark_turns_session",
            "CREATE INDEX IF NOT EXISTS idx_external_benchmark_turns_session "
            "ON external_benchmark_turns(benchmark_session_id, timestamp)",
        ),
        (
            "idx_token_savings_project_stage",
            "CREATE INDEX IF NOT EXISTS idx_token_savings_project_stage "
            "ON token_savings_ledger(project_path, stage, created_at)",
        ),
    ]
    for _index_name, statement in index_statements:
        cursor.execute(statement)


def ensure_project_optimization_schema(conn: sqlite3.Connection) -> None:
    """Repair optimization tables for existing databases when needed."""
    cursor = conn.cursor()
    _ensure_automation_state_scope(cursor)
    _ensure_project_optimization_tables(cursor)
    conn.commit()


def migrate(conn: sqlite3.Connection) -> bool:
    """Apply migration 0009."""
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
        ("1.8.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    _ensure_automation_state_scope(cursor)
    _ensure_project_optimization_tables(cursor)

    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.8.0", datetime.now().isoformat()),
    )
    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """Rollback migration 0009 by dropping optimization tables."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS token_savings_ledger")
    cursor.execute("DROP TABLE IF EXISTS external_benchmark_turns")
    cursor.execute("DROP TABLE IF EXISTS external_benchmark_sessions")
    cursor.execute("DROP TABLE IF EXISTS optimization_decisions")
    cursor.execute("DROP TABLE IF EXISTS workflow_rollups")
    cursor.execute("DROP TABLE IF EXISTS llm_calls")
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.8.0",),
    )
    conn.commit()
