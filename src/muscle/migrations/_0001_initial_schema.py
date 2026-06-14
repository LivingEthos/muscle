"""
Migration 0001: Initial schema for project memory database (v1.0.0).

This migration creates all tables and indexes required for the initial
project memory database schema.

Idempotent: Checks if schema_version 1.0.0 is already applied before running.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def migrate(conn: sqlite3.Connection) -> bool:
    """
    Apply migration 0001.

    Creates all tables and indexes for the initial schema.

    Returns True if migration was applied, False if it was already applied.
    """
    cursor = conn.cursor()

    # Ensure schema_version table exists first (for idempotency check)
    _create_table(
        cursor,
        "schema_version",
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """,
    )

    # Check if already migrated
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.0.0",),
    )
    if cursor.fetchone()[0] > 0:
        return False

    # Create remaining tables in dependency order

    _create_table(
        cursor,
        "tasks",
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            outcome TEXT,
            token_cost INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0
        )
        """,
    )

    _create_table(
        cursor,
        "conversation_events",
        """
        CREATE TABLE IF NOT EXISTS conversation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            task_id INTEGER,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            metadata_json TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
        )
        """,
    )

    _create_table(
        cursor,
        "review_runs",
        """
        CREATE TABLE IF NOT EXISTS review_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            review_mode TEXT NOT NULL,
            target_path TEXT NOT NULL,
            findings_count INTEGER NOT NULL DEFAULT 0,
            token_cost INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
    )

    _create_table(
        cursor,
        "review_findings",
        """
        CREATE TABLE IF NOT EXISTS review_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_run_id INTEGER NOT NULL,
            rule_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            file_path TEXT NOT NULL,
            line_number INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL,
            auto_fixable INTEGER NOT NULL DEFAULT 0,
            fix_applied INTEGER NOT NULL DEFAULT 0,
            outcome TEXT,
            FOREIGN KEY (review_run_id) REFERENCES review_runs(id) ON DELETE CASCADE
        )
        """,
    )

    _create_table(
        cursor,
        "fix_attempts",
        """
        CREATE TABLE IF NOT EXISTS fix_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            finding_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            fix_content TEXT,
            verification_passed INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            FOREIGN KEY (finding_id) REFERENCES review_findings(id) ON DELETE CASCADE
        )
        """,
    )

    _create_table(
        cursor,
        "change_events",
        """
        CREATE TABLE IF NOT EXISTS change_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            changed_files_json TEXT NOT NULL,
            diff_summary TEXT,
            review_run_id INTEGER,
            FOREIGN KEY (review_run_id) REFERENCES review_runs(id) ON DELETE SET NULL
        )
        """,
    )

    _create_table(
        cursor,
        "learned_rules",
        """
        CREATE TABLE IF NOT EXISTS learned_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            rule_text TEXT NOT NULL,
            trigger_pattern TEXT NOT NULL,
            recurrence_count INTEGER NOT NULL DEFAULT 1,
            success_rate REAL NOT NULL DEFAULT 0.0,
            last_triggered TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            promoted_to_claude_md INTEGER NOT NULL DEFAULT 0,
            promoted_at TEXT
        )
        """,
    )

    _create_table(
        cursor,
        "memory_decisions",
        """
        CREATE TABLE IF NOT EXISTS memory_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            decision_type TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            evidence_json TEXT NOT NULL,
            score_json TEXT NOT NULL,
            reasoning TEXT NOT NULL
        )
        """,
    )

    _create_table(
        cursor,
        "skills",
        """
        CREATE TABLE IF NOT EXISTS skills (
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
        """,
    )

    _create_table(
        cursor,
        "agents",
        """
        CREATE TABLE IF NOT EXISTS agents (
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
        """,
    )

    _create_table(
        cursor,
        "backups",
        """
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            backup_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            checksum TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            retention_days INTEGER NOT NULL DEFAULT 30
        )
        """,
    )

    _create_table(
        cursor,
        "project_notes",
        """
        CREATE TABLE IF NOT EXISTS project_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """,
    )

    _create_table(
        cursor,
        "automation_state",
        """
        CREATE TABLE IF NOT EXISTS automation_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state_key TEXT NOT NULL UNIQUE,
            state_value TEXT,
            updated_at TEXT NOT NULL
        )
        """,
    )

    # Create indexes
    _create_index(
        cursor,
        "idx_tasks_project_path",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_path ON tasks(project_path)",
    )
    _create_index(
        cursor,
        "idx_tasks_status",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    )
    _create_index(
        cursor,
        "idx_tasks_created_at",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)",
    )

    _create_index(
        cursor,
        "idx_conversation_events_project_path",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_project_path ON conversation_events(project_path)",
    )
    _create_index(
        cursor,
        "idx_conversation_events_task_id",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_task_id ON conversation_events(task_id)",
    )
    _create_index(
        cursor,
        "idx_conversation_events_event_type",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_event_type ON conversation_events(event_type)",
    )
    _create_index(
        cursor,
        "idx_conversation_events_timestamp",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_timestamp ON conversation_events(timestamp)",
    )

    _create_index(
        cursor,
        "idx_review_runs_project_path",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_project_path ON review_runs(project_path)",
    )
    _create_index(
        cursor,
        "idx_review_runs_review_mode",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_review_mode ON review_runs(review_mode)",
    )
    _create_index(
        cursor,
        "idx_review_runs_created_at",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_created_at ON review_runs(created_at)",
    )

    _create_index(
        cursor,
        "idx_review_findings_review_run_id",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_review_run_id ON review_findings(review_run_id)",
    )
    _create_index(
        cursor,
        "idx_review_findings_rule_id",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_rule_id ON review_findings(rule_id)",
    )
    _create_index(
        cursor,
        "idx_review_findings_severity",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_severity ON review_findings(severity)",
    )
    _create_index(
        cursor,
        "idx_review_findings_file_path",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_file_path ON review_findings(file_path)",
    )
    _create_index(
        cursor,
        "idx_review_findings_auto_fixable",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_auto_fixable ON review_findings(auto_fixable)",
    )

    _create_index(
        cursor,
        "idx_fix_attempts_finding_id",
        "CREATE INDEX IF NOT EXISTS idx_fix_attempts_finding_id ON fix_attempts(finding_id)",
    )
    _create_index(
        cursor,
        "idx_fix_attempts_created_at",
        "CREATE INDEX IF NOT EXISTS idx_fix_attempts_created_at ON fix_attempts(created_at)",
    )

    _create_index(
        cursor,
        "idx_change_events_project_path",
        "CREATE INDEX IF NOT EXISTS idx_change_events_project_path ON change_events(project_path)",
    )
    _create_index(
        cursor,
        "idx_change_events_created_at",
        "CREATE INDEX IF NOT EXISTS idx_change_events_created_at ON change_events(created_at)",
    )
    _create_index(
        cursor,
        "idx_change_events_review_run_id",
        "CREATE INDEX IF NOT EXISTS idx_change_events_review_run_id ON change_events(review_run_id)",
    )

    _create_index(
        cursor,
        "idx_learned_rules_project_path",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_project_path ON learned_rules(project_path)",
    )
    _create_index(
        cursor,
        "idx_learned_rules_trigger_pattern",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_trigger_pattern ON learned_rules(trigger_pattern)",
    )
    _create_index(
        cursor,
        "idx_learned_rules_status",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_status ON learned_rules(status)",
    )
    _create_index(
        cursor,
        "idx_learned_rules_recurrence_count",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_recurrence_count ON learned_rules(recurrence_count)",
    )
    _create_index(
        cursor,
        "idx_learned_rules_last_triggered",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_last_triggered ON learned_rules(last_triggered)",
    )

    _create_index(
        cursor,
        "idx_memory_decisions_project_path",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_project_path ON memory_decisions(project_path)",
    )
    _create_index(
        cursor,
        "idx_memory_decisions_decision_type",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_decision_type ON memory_decisions(decision_type)",
    )
    _create_index(
        cursor,
        "idx_memory_decisions_created_at",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_created_at ON memory_decisions(created_at)",
    )

    _create_index(
        cursor,
        "idx_skills_project_path",
        "CREATE INDEX IF NOT EXISTS idx_skills_project_path ON skills(project_path)",
    )
    _create_index(
        cursor,
        "idx_skills_trigger_pattern",
        "CREATE INDEX IF NOT EXISTS idx_skills_trigger_pattern ON skills(trigger_pattern)",
    )
    _create_index(
        cursor,
        "idx_skills_status",
        "CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)",
    )
    _create_index(
        cursor,
        "idx_skills_last_used",
        "CREATE INDEX IF NOT EXISTS idx_skills_last_used ON skills(last_used)",
    )

    _create_index(
        cursor,
        "idx_agents_project_path",
        "CREATE INDEX IF NOT EXISTS idx_agents_project_path ON agents(project_path)",
    )
    _create_index(
        cursor,
        "idx_agents_trigger_pattern",
        "CREATE INDEX IF NOT EXISTS idx_agents_trigger_pattern ON agents(trigger_pattern)",
    )
    _create_index(
        cursor,
        "idx_agents_status",
        "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)",
    )
    _create_index(
        cursor,
        "idx_agents_last_used",
        "CREATE INDEX IF NOT EXISTS idx_agents_last_used ON agents(last_used)",
    )

    _create_index(
        cursor,
        "idx_backups_project_path",
        "CREATE INDEX IF NOT EXISTS idx_backups_project_path ON backups(project_path)",
    )
    _create_index(
        cursor,
        "idx_backups_backup_type",
        "CREATE INDEX IF NOT EXISTS idx_backups_backup_type ON backups(backup_type)",
    )
    _create_index(
        cursor,
        "idx_backups_created_at",
        "CREATE INDEX IF NOT EXISTS idx_backups_created_at ON backups(created_at)",
    )

    _create_index(
        cursor,
        "idx_project_notes_project_path",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_project_path ON project_notes(project_path)",
    )
    _create_index(
        cursor,
        "idx_project_notes_category",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_category ON project_notes(category)",
    )
    _create_index(
        cursor,
        "idx_project_notes_updated_at",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_updated_at ON project_notes(updated_at)",
    )

    _create_index(
        cursor,
        "idx_automation_state_project_path",
        "CREATE INDEX IF NOT EXISTS idx_automation_state_project_path ON automation_state(project_path)",
    )

    # Record schema version
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        ("1.0.0", datetime.now().isoformat()),
    )

    conn.commit()
    return True


def rollback(conn: sqlite3.Connection) -> None:
    """
    Rollback migration 0001.

    Note: This removes all tables created by this migration. Data will be lost.
    This is a destructive operation and should only be used in emergencies.
    """
    cursor = conn.cursor()

    # Check if this migration was applied
    cursor.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?",
        ("1.0.0",),
    )
    if cursor.fetchone()[0] == 0:
        return  # Migration not applied, nothing to rollback

    # Remove schema version record FIRST (before dropping the table)
    cursor.execute(
        "DELETE FROM schema_version WHERE version = ?",
        ("1.0.0",),
    )

    # Drop tables in reverse dependency order
    cursor.execute("DROP TABLE IF EXISTS automation_state")
    cursor.execute("DROP TABLE IF EXISTS project_notes")
    cursor.execute("DROP TABLE IF EXISTS backups")
    cursor.execute("DROP TABLE IF EXISTS agents")
    cursor.execute("DROP TABLE IF EXISTS skills")
    cursor.execute("DROP TABLE IF EXISTS memory_decisions")
    cursor.execute("DROP TABLE IF EXISTS learned_rules")
    cursor.execute("DROP TABLE IF EXISTS change_events")
    cursor.execute("DROP TABLE IF EXISTS fix_attempts")
    cursor.execute("DROP TABLE IF EXISTS review_findings")
    cursor.execute("DROP TABLE IF EXISTS review_runs")
    cursor.execute("DROP TABLE IF EXISTS conversation_events")
    cursor.execute("DROP TABLE IF EXISTS tasks")
    cursor.execute("DROP TABLE IF EXISTS schema_version")

    conn.commit()


def _create_table(cursor: Any, table_name: str, sql: str) -> None:
    """Execute a CREATE TABLE statement."""
    cursor.execute(sql)


def _create_index(cursor: Any, index_name: str, sql: str) -> None:
    """Execute a CREATE INDEX statement."""
    cursor.execute(sql)
