"""
Unit tests for project memory migration framework (MUS-011).

Tests:
- Migration from empty project
- Migration re-run safety (idempotency)
- Migration rollback strategy tests
"""

import importlib
import importlib.machinery
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.migrations import MigrationRunner


def _load_migration_module(filename: str):
    """Load a migration module by filename using importlib machinery."""
    migrations_dir = Path(__file__).parent.parent.parent / "tools" / "muscle" / "migrations"
    module_name = filename[:-3]  # Remove .py
    module_path = str(migrations_dir / filename)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_m1 = _load_migration_module("_0001_initial_schema.py")
migrate_v1 = _m1.migrate
rollback_v1 = _m1.rollback

_m2 = _load_migration_module("_0002_add_indices.py")
migrate_v2 = _m2.migrate
rollback_v2 = _m2.rollback


class TestMigrationRunner:
    """Tests for MigrationRunner class."""

    @pytest.fixture
    def temp_db_path(self):
        """Provide a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test.db"

    @pytest.fixture
    def project_path(self):
        """Provide a temporary project path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_migration_runner_initializes_project_directory(self, project_path):
        """MigrationRunner creates .muscle directory if it doesn't exist."""
        muscle_dir = project_path / ".muscle"
        assert not muscle_dir.exists()

        runner = MigrationRunner(str(project_path))
        assert muscle_dir.exists()
        assert muscle_dir.is_dir()

    def test_run_applies_migrations_from_empty_database(self, temp_db_path, project_path):
        """Running migrations on empty database applies all migrations."""
        # Create a new empty database
        conn = sqlite3.connect(str(temp_db_path))
        conn.close()

        runner = MigrationRunner(str(project_path), str(temp_db_path))
        applied = runner.run()

        assert "1.0.0" in applied
        assert "1.1.0" in applied
        assert "1.3.0" in applied
        assert "1.3.1" in applied
        assert "1.4.0" in applied
        assert "1.5.0" in applied

        # Verify schema_version table has both versions
        versions = runner.get_applied_versions()
        assert "1.0.0" in versions
        assert "1.1.0" in versions
        assert "1.3.0" in versions
        assert "1.3.1" in versions
        assert "1.4.0" in versions
        assert "1.5.0" in versions

        conn = sqlite3.connect(str(temp_db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(agents)")
        agent_columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        assert "archived_at" in agent_columns
        assert "revision_count" in agent_columns
        assert "revision_history_json" in agent_columns

    def test_run_is_idempotent(self, temp_db_path, project_path):
        """Running migrations multiple times is safe (idempotent)."""
        runner = MigrationRunner(str(project_path), str(temp_db_path))

        # Run migrations first time
        applied1 = runner.run()
        assert len(applied1) >= 1

        # Run migrations again - should be no-op
        applied2 = runner.run()
        # All versions should still be marked as applied
        versions = runner.get_applied_versions()
        assert "1.0.0" in versions

    def test_get_current_version_returns_none_for_new_db(self, temp_db_path, project_path):
        """New database has no schema version recorded."""
        conn = sqlite3.connect(str(temp_db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "version TEXT NOT NULL UNIQUE, "
            "applied_at TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        runner = MigrationRunner(str(project_path), str(temp_db_path))
        version = runner.get_current_version()
        # New schema_version table with no versions recorded
        assert version is None

    def test_get_applied_versions(self, temp_db_path, project_path):
        """Returns all applied migration versions."""
        runner = MigrationRunner(str(project_path), str(temp_db_path))
        runner.run()

        versions = runner.get_applied_versions()
        assert "1.0.0" in versions
        assert "1.1.0" in versions
        assert "1.3.1" in versions

    def test_get_migration_status(self, temp_db_path, project_path):
        """Returns detailed status of all migrations."""
        runner = MigrationRunner(str(project_path), str(temp_db_path))
        runner.run()

        status = runner.get_migration_status()

        assert status["current_version"] == "1.5.0"
        assert "1.0.0" in status["applied_versions"]
        assert "1.1.0" in status["applied_versions"]
        assert "1.3.0" in status["applied_versions"]
        assert "1.3.1" in status["applied_versions"]
        assert "1.4.0" in status["applied_versions"]
        assert "1.5.0" in status["applied_versions"]
        assert len(status["pending_versions"]) == 0
        assert len(status["migrations"]) == 6

        for m in status["migrations"]:
            assert m["status"] == "applied"
            assert m["can_rollback"] is True


class TestMigrationV1:
    """Tests for migration 0001 (initial schema)."""

    @pytest.fixture
    def conn(self, tmp_path):
        """Provide a database connection with schema_version table."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        # Create schema_version table manually for testing
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "version TEXT NOT NULL UNIQUE, "
            "applied_at TEXT NOT NULL)"
        )
        yield conn
        conn.close()

    def test_migrate_creates_all_tables(self, conn):
        """Migration v1 creates all required tables."""
        migrate_v1(conn)

        # Verify all expected tables exist
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        expected_tables = [
            "schema_version",
            "tasks",
            "conversation_events",
            "review_runs",
            "review_findings",
            "fix_attempts",
            "change_events",
            "learned_rules",
            "memory_decisions",
            "skills",
            "agents",
            "backups",
            "project_notes",
            "automation_state",
        ]

        for table in expected_tables:
            assert table in tables, f"Table {table} not found"

    def test_migrate_creates_all_indexes(self, conn):
        """Migration v1 creates all required indexes."""
        migrate_v1(conn)

        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
        indexes = [row[0] for row in cursor.fetchall()]

        # Verify some key indexes exist
        assert "idx_tasks_project_path" in indexes
        assert "idx_review_runs_project_path" in indexes
        assert "idx_review_findings_review_run_id" in indexes

    def test_migrate_records_version(self, conn):
        """Migration v1 records version in schema_version table."""
        migrate_v1(conn)

        cursor = conn.cursor()
        cursor.execute("SELECT version, applied_at FROM schema_version")
        rows = cursor.fetchall()

        versions = [row[0] for row in rows]
        assert "1.0.0" in versions

    def test_migrate_is_idempotent(self, conn):
        """Migration v1 can be run multiple times safely."""
        # First run
        result1 = migrate_v1(conn)
        assert result1 is True

        # Second run
        result2 = migrate_v1(conn)
        assert result2 is False

        # Only one version record should exist
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM schema_version WHERE version = '1.0.0'")
        count = cursor.fetchone()[0]
        assert count == 1


class TestMigrationV2:
    """Tests for migration 0002 (additional indices)."""

    @pytest.fixture
    def conn_with_v1(self, tmp_path):
        """Provide a database with v1 already applied."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        # Apply v1 first
        migrate_v1(conn)
        yield conn
        conn.close()

    def test_migrate_adds_composite_indexes(self, conn_with_v1):
        """Migration v2 adds composite indexes for common query patterns."""
        migrate_v2(conn_with_v1)

        cursor = conn_with_v1.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
        indexes = [row[0] for row in cursor.fetchall()]

        # Verify composite indexes from v2
        assert "idx_tasks_project_status" in indexes
        assert "idx_review_findings_severity_auto_fixable" in indexes
        assert "idx_learned_rules_project_status" in indexes

    def test_migrate_records_version(self, conn_with_v1):
        """Migration v2 records version in schema_version table."""
        migrate_v2(conn_with_v1)

        cursor = conn_with_v1.cursor()
        cursor.execute("SELECT version FROM schema_version ORDER BY id")
        versions = [row[0] for row in cursor.fetchall()]

        assert "1.1.0" in versions

    def test_migrate_requires_v1(self, tmp_path):
        """Migration v2 fails if v1 is not applied first."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))

        # Only create schema_version table, not the rest of v1
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "version TEXT NOT NULL UNIQUE, "
            "applied_at TEXT NOT NULL)"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="Migration 0001.*must be applied"):
            migrate_v2(conn)

        conn.close()

    def test_migrate_is_idempotent(self, conn_with_v1):
        """Migration v2 can be run multiple times safely."""
        # First run
        result1 = migrate_v2(conn_with_v1)
        assert result1 is True

        # Second run
        result2 = migrate_v2(conn_with_v1)
        assert result2 is False


class TestMigrationRollback:
    """Tests for migration rollback functionality."""

    @pytest.fixture
    def conn(self, tmp_path):
        """Provide a database with both migrations applied."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        migrate_v1(conn)
        migrate_v2(conn)
        yield conn
        conn.close()

    def test_rollback_v2_removes_v2_indexes(self, conn):
        """Rolling back v2 removes the v2 indexes but keeps v1 tables."""
        from tools.muscle.migrations._0002_add_indices import rollback as rollback_v2

        rollback_v2(conn)

        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
        indexes = [row[0] for row in cursor.fetchall()]

        # V2 indexes should be gone
        assert "idx_tasks_project_status" not in indexes
        # V1 indexes should still exist
        assert "idx_tasks_project_path" in indexes

    def test_rollback_v2_removes_version_record(self, conn):
        """Rolling back v2 removes the version record."""
        from tools.muscle.migrations._0002_add_indices import rollback as rollback_v2

        rollback_v2(conn)

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM schema_version WHERE version = '1.1.0'")
        count = cursor.fetchone()[0]
        assert count == 0

    def test_rollback_all_removes_all_tables(self, tmp_path):
        """Rolling back all migrations removes all tables."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        migrate_v1(conn)
        migrate_v2(conn)

        # Rollback v2 then v1
        from tools.muscle.migrations._0002_add_indices import rollback as rollback_v2
        from tools.muscle.migrations._0001_initial_schema import rollback as rollback_v1

        rollback_v2(conn)
        rollback_v1(conn)

        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        # All project memory tables should be gone
        expected_tables = [
            "tasks",
            "conversation_events",
            "review_runs",
            "review_findings",
            "fix_attempts",
            "change_events",
            "learned_rules",
            "memory_decisions",
            "skills",
            "agents",
            "backups",
            "project_notes",
            "automation_state",
        ]

        for table in expected_tables:
            assert table not in tables

        # schema_version should also be gone
        assert "schema_version" not in tables

        conn.close()


class TestMigrationRunnerRollback:
    """Tests for MigrationRunner rollback functionality."""

    @pytest.fixture
    def temp_db_path(self):
        """Provide a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test.db"

    @pytest.fixture
    def project_path(self):
        """Provide a temporary project path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_rollback_to_version_removes_later_migrations(self, temp_db_path, project_path):
        """Rolling back to a version removes all migrations after that version."""
        # Create and apply migrations
        runner = MigrationRunner(str(project_path), str(temp_db_path))
        runner.run()

        # Verify both versions are applied
        versions = runner.get_applied_versions()
        assert "1.0.0" in versions
        assert "1.1.0" in versions

        # Rollback to 1.0.0
        success = runner.rollback_to("1.0.0")
        assert success is True

        # Verify 1.1.0 is removed but 1.0.0 remains
        versions = runner.get_applied_versions()
        assert "1.0.0" in versions
        assert "1.1.0" not in versions

    def test_rollback_to_nonexistent_version_fails(self, temp_db_path, project_path):
        """Rolling back to a nonexistent version fails."""
        runner = MigrationRunner(str(project_path), str(temp_db_path))
        runner.run()

        success = runner.rollback_to("99.99.99")
        assert success is False


class TestMigrationIntegration:
    """Integration tests for migration framework with ProjectMemory."""

    @pytest.fixture
    def temp_project(self):
        """Provide a temporary project with ProjectMemory database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_project_memory_uses_migration_framework(self, temp_project):
        """ProjectMemory initializes database via migration framework."""
        from tools.muscle.project_memory import ProjectMemory

        pm = ProjectMemory(str(temp_project))

        # Verify database was created
        db_path = temp_project / ".muscle" / "project_memory.db"
        assert db_path.exists()

        # Verify schema version is recorded
        version = pm.get_schema_version()
        assert version == "1.5.0"

    def test_project_memory_creates_all_tables(self, temp_project):
        """ProjectMemory creates all tables via migrations."""
        from tools.muscle.project_memory import ProjectMemory

        pm = ProjectMemory(str(temp_project))

        db_path = temp_project / ".muscle" / "project_memory.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        expected_tables = [
            "schema_version",
            "tasks",
            "conversation_events",
            "review_runs",
            "review_findings",
            "fix_attempts",
            "change_events",
            "learned_rules",
            "memory_decisions",
            "skills",
            "agents",
            "backups",
            "project_notes",
            "automation_state",
        ]

        for table in expected_tables:
            assert table in tables, f"Table {table} not found"

    def test_project_memory_insert_and_query(self, temp_project):
        """ProjectMemory can insert and query data after migration."""
        from tools.muscle.project_memory import ProjectMemory

        pm = ProjectMemory(str(temp_project))

        # Insert a task
        task_id = pm.insert_task(
            project_path=str(temp_project),
            created_at=datetime.now().isoformat(),
            title="Test Task",
            description="Test description",
            status="pending",
        )

        assert task_id > 0

        # Query the task
        task = pm.get_task(task_id)
        assert task is not None
        assert task["title"] == "Test Task"
        assert task["status"] == "pending"

    def test_project_memory_list_tasks(self, temp_project):
        """ProjectMemory can list tasks with filters."""
        from tools.muscle.project_memory import ProjectMemory

        pm = ProjectMemory(str(temp_project))

        # Insert multiple tasks
        for i in range(3):
            pm.insert_task(
                project_path=str(temp_project),
                created_at=datetime.now().isoformat(),
                title=f"Task {i}",
                description=f"Description {i}",
                status="pending" if i % 2 == 0 else "completed",
            )

        # List all tasks
        tasks = pm.list_tasks()
        assert len(tasks) == 3

        # Filter by status
        pending_tasks = pm.list_tasks(status="pending")
        assert len(pending_tasks) == 2

        completed_tasks = pm.list_tasks(status="completed")
        assert len(completed_tasks) == 1

    def test_project_memory_insert_review_run_and_finding(self, temp_project):
        """ProjectMemory can insert review runs and findings."""
        from tools.muscle.project_memory import ProjectMemory

        pm = ProjectMemory(str(temp_project))

        # Insert a review run
        run_id = pm.insert_review_run(
            project_path=str(temp_project),
            review_mode="review",
            target_path=str(temp_project / "src"),
            findings_count=2,
            token_cost=1000,
            duration_ms=5000,
            created_at=datetime.now().isoformat(),
        )

        assert run_id > 0

        # Insert findings
        finding1_id = pm.insert_review_finding(
            review_run_id=run_id,
            rule_id="R001",
            severity="error",
            file_path=str(temp_project / "src" / "main.py"),
            line_number=10,
            message="Unused import",
            auto_fixable=True,
        )

        finding2_id = pm.insert_review_finding(
            review_run_id=run_id,
            rule_id="R002",
            severity="warning",
            file_path=str(temp_project / "src" / "main.py"),
            line_number=25,
            message="Variable not used",
            auto_fixable=False,
        )

        assert finding1_id > 0
        assert finding2_id > 0

        # Query findings
        findings = pm.list_findings_for_run(run_id)
        assert len(findings) == 2
