"""
SQLite schema definition for project memory database (MUS-010).

This module contains all CREATE TABLE statements and index definitions
for the unified project memory database.
"""

from __future__ import annotations

# Current schema version - update when schema changes
SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Table creation statements (in dependency order)
# ---------------------------------------------------------------------------

CREATE_SCHEMA_VERSION = """
    CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT NOT NULL UNIQUE,
        applied_at TEXT NOT NULL
    )
"""

CREATE_TASKS = """
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
"""

CREATE_CONVERSATION_EVENTS = """
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
"""

CREATE_REVIEW_RUNS = """
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
"""

CREATE_REVIEW_FINDINGS = """
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
"""

CREATE_FIX_ATTEMPTS = """
    CREATE TABLE IF NOT EXISTS fix_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        finding_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        fix_content TEXT,
        verification_passed INTEGER NOT NULL DEFAULT 0,
        notes TEXT,
        FOREIGN KEY (finding_id) REFERENCES review_findings(id) ON DELETE CASCADE
    )
"""

CREATE_CHANGE_EVENTS = """
    CREATE TABLE IF NOT EXISTS change_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        changed_files_json TEXT NOT NULL,
        diff_summary TEXT,
        review_run_id INTEGER,
        FOREIGN KEY (review_run_id) REFERENCES review_runs(id) ON DELETE SET NULL
    )
"""

CREATE_LEARNED_RULES = """
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
"""

CREATE_MEMORY_DECISIONS = """
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
"""

CREATE_SKILLS = """
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
"""

CREATE_AGENTS = """
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
"""

CREATE_BACKUPS = """
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
"""

CREATE_PROJECT_NOTES = """
    CREATE TABLE IF NOT EXISTS project_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )
"""

CREATE_AUTOMATION_STATE = """
    CREATE TABLE IF NOT EXISTS automation_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        state_key TEXT NOT NULL UNIQUE,
        state_value TEXT,
        updated_at TEXT NOT NULL
    )
"""

# ---------------------------------------------------------------------------
# Index creation statements
# ---------------------------------------------------------------------------

INDEXES = [
    # Task indexes
    (
        "idx_tasks_project_path",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project_path ON tasks(project_path)",
    ),
    ("idx_tasks_status", "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)"),
    (
        "idx_tasks_created_at",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at)",
    ),
    # Conversation event indexes
    (
        "idx_conversation_events_project_path",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_project_path ON conversation_events(project_path)",
    ),
    (
        "idx_conversation_events_task_id",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_task_id ON conversation_events(task_id)",
    ),
    (
        "idx_conversation_events_event_type",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_event_type ON conversation_events(event_type)",
    ),
    (
        "idx_conversation_events_timestamp",
        "CREATE INDEX IF NOT EXISTS idx_conversation_events_timestamp ON conversation_events(timestamp)",
    ),
    # Review run indexes
    (
        "idx_review_runs_project_path",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_project_path ON review_runs(project_path)",
    ),
    (
        "idx_review_runs_review_mode",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_review_mode ON review_runs(review_mode)",
    ),
    (
        "idx_review_runs_created_at",
        "CREATE INDEX IF NOT EXISTS idx_review_runs_created_at ON review_runs(created_at)",
    ),
    # Review finding indexes
    (
        "idx_review_findings_review_run_id",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_review_run_id ON review_findings(review_run_id)",
    ),
    (
        "idx_review_findings_rule_id",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_rule_id ON review_findings(rule_id)",
    ),
    (
        "idx_review_findings_severity",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_severity ON review_findings(severity)",
    ),
    (
        "idx_review_findings_file_path",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_file_path ON review_findings(file_path)",
    ),
    (
        "idx_review_findings_auto_fixable",
        "CREATE INDEX IF NOT EXISTS idx_review_findings_auto_fixable ON review_findings(auto_fixable)",
    ),
    # Fix attempt indexes
    (
        "idx_fix_attempts_finding_id",
        "CREATE INDEX IF NOT EXISTS idx_fix_attempts_finding_id ON fix_attempts(finding_id)",
    ),
    (
        "idx_fix_attempts_created_at",
        "CREATE INDEX IF NOT EXISTS idx_fix_attempts_created_at ON fix_attempts(created_at)",
    ),
    # Change event indexes
    (
        "idx_change_events_project_path",
        "CREATE INDEX IF NOT EXISTS idx_change_events_project_path ON change_events(project_path)",
    ),
    (
        "idx_change_events_created_at",
        "CREATE INDEX IF NOT EXISTS idx_change_events_created_at ON change_events(created_at)",
    ),
    (
        "idx_change_events_review_run_id",
        "CREATE INDEX IF NOT EXISTS idx_change_events_review_run_id ON change_events(review_run_id)",
    ),
    # Learned rule indexes
    (
        "idx_learned_rules_project_path",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_project_path ON learned_rules(project_path)",
    ),
    (
        "idx_learned_rules_trigger_pattern",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_trigger_pattern ON learned_rules(trigger_pattern)",
    ),
    (
        "idx_learned_rules_status",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_status ON learned_rules(status)",
    ),
    (
        "idx_learned_rules_recurrence_count",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_recurrence_count ON learned_rules(recurrence_count)",
    ),
    (
        "idx_learned_rules_last_triggered",
        "CREATE INDEX IF NOT EXISTS idx_learned_rules_last_triggered ON learned_rules(last_triggered)",
    ),
    # Memory decision indexes
    (
        "idx_memory_decisions_project_path",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_project_path ON memory_decisions(project_path)",
    ),
    (
        "idx_memory_decisions_decision_type",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_decision_type ON memory_decisions(decision_type)",
    ),
    (
        "idx_memory_decisions_created_at",
        "CREATE INDEX IF NOT EXISTS idx_memory_decisions_created_at ON memory_decisions(created_at)",
    ),
    # Skill indexes
    (
        "idx_skills_project_path",
        "CREATE INDEX IF NOT EXISTS idx_skills_project_path ON skills(project_path)",
    ),
    (
        "idx_skills_trigger_pattern",
        "CREATE INDEX IF NOT EXISTS idx_skills_trigger_pattern ON skills(trigger_pattern)",
    ),
    ("idx_skills_status", "CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)"),
    (
        "idx_skills_last_used",
        "CREATE INDEX IF NOT EXISTS idx_skills_last_used ON skills(last_used)",
    ),
    # Agent indexes
    (
        "idx_agents_project_path",
        "CREATE INDEX IF NOT EXISTS idx_agents_project_path ON agents(project_path)",
    ),
    (
        "idx_agents_trigger_pattern",
        "CREATE INDEX IF NOT EXISTS idx_agents_trigger_pattern ON agents(trigger_pattern)",
    ),
    ("idx_agents_status", "CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status)"),
    (
        "idx_agents_last_used",
        "CREATE INDEX IF NOT EXISTS idx_agents_last_used ON agents(last_used)",
    ),
    # Backup indexes
    (
        "idx_backups_project_path",
        "CREATE INDEX IF NOT EXISTS idx_backups_project_path ON backups(project_path)",
    ),
    (
        "idx_backups_backup_type",
        "CREATE INDEX IF NOT EXISTS idx_backups_backup_type ON backups(backup_type)",
    ),
    (
        "idx_backups_created_at",
        "CREATE INDEX IF NOT EXISTS idx_backups_created_at ON backups(created_at)",
    ),
    # Project note indexes
    (
        "idx_project_notes_project_path",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_project_path ON project_notes(project_path)",
    ),
    (
        "idx_project_notes_category",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_category ON project_notes(category)",
    ),
    (
        "idx_project_notes_updated_at",
        "CREATE INDEX IF NOT EXISTS idx_project_notes_updated_at ON project_notes(updated_at)",
    ),
    # Automation state indexes
    (
        "idx_automation_state_project_path",
        "CREATE INDEX IF NOT EXISTS idx_automation_state_project_path ON automation_state(project_path)",
    ),
]

# All tables in creation order (for initial schema setup)
ALL_TABLES = [
    ("schema_version", CREATE_SCHEMA_VERSION),
    ("tasks", CREATE_TASKS),
    ("conversation_events", CREATE_CONVERSATION_EVENTS),
    ("review_runs", CREATE_REVIEW_RUNS),
    ("review_findings", CREATE_REVIEW_FINDINGS),
    ("fix_attempts", CREATE_FIX_ATTEMPTS),
    ("change_events", CREATE_CHANGE_EVENTS),
    ("learned_rules", CREATE_LEARNED_RULES),
    ("memory_decisions", CREATE_MEMORY_DECISIONS),
    ("skills", CREATE_SKILLS),
    ("agents", CREATE_AGENTS),
    ("backups", CREATE_BACKUPS),
    ("project_notes", CREATE_PROJECT_NOTES),
    ("automation_state", CREATE_AUTOMATION_STATE),
]


def get_all_create_statements() -> list[tuple[str, str]]:
    """Return all table creation statements in dependency order."""
    return ALL_TABLES.copy()


def get_create_statement(table_name: str) -> str | None:
    """Get the CREATE statement for a specific table."""
    for name, stmt in ALL_TABLES:
        if name == table_name:
            return stmt
    return None


def get_index_statements() -> list[tuple[str, str]]:
    """Return all index creation statements."""
    return INDEXES.copy()
