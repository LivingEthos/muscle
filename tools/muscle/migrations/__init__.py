"""
Migration framework for project memory database (MUS-011).

This module provides:
- MigrationRunner: Executes migrations in order with idempotency
- Schema version tracking via schema_version table
- Rollback support for critical migrations
- Safe upgrade paths for existing projects

Usage:
    from tools.muscle.migrations import MigrationRunner

    runner = MigrationRunner("/path/to/project")
    runner.run()  # Apply all pending migrations
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

logger = logging.getLogger(__name__)

# Migration module type
MigrationFunc = Callable[[sqlite3.Connection], bool]
RollbackFunc = Callable[[sqlite3.Connection], None]

# Current schema version - update when schema changes
CURRENT_SCHEMA_VERSION = "1.7.0"

# Registered migrations in order
# Each entry: (version, migrate_func, rollback_func)
_MIGRATIONS: list[tuple[str, MigrationFunc, RollbackFunc | None]] = []


def _load_migrations() -> list[tuple[str, MigrationFunc, RollbackFunc | None]]:
    """Load all migrations from the migrations directory using importlib."""
    global _MIGRATIONS
    if _MIGRATIONS:
        return _MIGRATIONS

    # Migration modules have numeric prefixes which aren't valid Python identifiers.
    # We must use spec_from_file_location to load them.
    migrations_dir = Path(__file__).parent

    def _load_migration_module(filename: str) -> ModuleType:
        module_name = filename[:-3]  # Remove .py
        module_path = str(migrations_dir / filename)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None:
            msg = f"Could not load module spec for {filename}"
            raise RuntimeError(msg)
        if spec.loader is None:
            msg = f"Could not get loader for {filename}"
            raise RuntimeError(msg)
        module = importlib.util.module_from_spec(spec)
        if module is None:
            msg = f"Could not create module for {filename}"
            raise RuntimeError(msg)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    m1 = _load_migration_module("_0001_initial_schema.py")
    m2 = _load_migration_module("_0002_add_indices.py")
    m3 = _load_migration_module("_0003_skill_lifecycle.py")
    m4 = _load_migration_module("_0004_agent_lifecycle.py")
    m5 = _load_migration_module("_0005_shadow_jobs.py")
    m6 = _load_migration_module("_0006_action_log.py")
    m7 = _load_migration_module("_0007_review_workflow_fields.py")
    m8 = _load_migration_module("_0008_shadow_job_execution_mode.py")

    _MIGRATIONS = [
        ("1.0.0", m1.migrate, m1.rollback),
        ("1.1.0", m2.migrate, m2.rollback),
        ("1.3.0", m3.migrate, m3.rollback),
        ("1.3.1", m4.migrate, m4.rollback),
        ("1.4.0", m5.migrate, m5.rollback),
        ("1.5.0", m6.migrate, m6.rollback),
        ("1.6.0", m7.migrate, m7.rollback),
        ("1.7.0", m8.migrate, m8.rollback),
    ]

    # Sort by version to ensure consistent ordering
    _MIGRATIONS.sort(key=lambda x: x[0])
    return _MIGRATIONS


class MigrationRunner:
    """
    Manages database migrations for project memory.

    Features:
    - Tracks schema version in schema_version table
    - Applies migrations in version order
    - Idempotent: safely re-runs already applied migrations
    - Supports rollback for critical migrations
    - Creates .muscle directory if it doesn't exist
    """

    def __init__(self, project_path: str, db_path: str | None = None):
        """
        Initialize MigrationRunner.

        Args:
            project_path: Absolute path to the project root.
            db_path: Optional path to the DB file.
                     Defaults to <project_path>/.muscle/project_memory.db.
        """
        self.project_path = Path(project_path)
        self._muscle_dir = self.project_path / ".muscle"
        self._muscle_dir.mkdir(parents=True, exist_ok=True)

        if db_path:
            self._db_path = Path(db_path)
        else:
            self._db_path = self._muscle_dir / "project_memory.db"

    def _get_connection(self) -> sqlite3.Connection:
        """Return a connection with row factory enabled."""
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_current_version(self) -> str | None:
        """
        Get the current schema version from the database.

        Returns None if no schema has been applied yet.
        """
        if not self._db_path.exists():
            return None

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT version FROM schema_version ORDER BY id DESC LIMIT 1",
            )
            row = cursor.fetchone()
            conn.close()
            return row["version"] if row else None
        except sqlite3.Error:
            return None

    def get_applied_versions(self) -> list[str]:
        """Get all applied migration versions."""
        if not self._db_path.exists():
            return []

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT version FROM schema_version ORDER BY id")
            rows = cursor.fetchall()
            conn.close()
            return [row["version"] for row in rows]
        except sqlite3.Error:
            return []

    def _ensure_schema_version_table(self, conn: sqlite3.Connection) -> None:
        """Ensure the schema_version table exists (for new databases)."""
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
        conn.commit()

    def run(self) -> list[str]:
        """
        Run all pending migrations.

        Returns a list of versions that were applied.
        """
        migrations = _load_migrations()
        applied: list[str] = []

        conn = self._get_connection()
        try:
            self._ensure_schema_version_table(conn)
            applied_versions = self.get_applied_versions()

            for version, migrate_fn, _ in migrations:
                if version in applied_versions:
                    logger.debug(f"Migration {version} already applied, skipping")
                    continue

                logger.info(f"Applying migration {version}...")
                try:
                    success = migrate_fn(conn)
                    if success:
                        logger.info(f"Migration {version} applied successfully")
                        applied.append(version)
                    else:
                        logger.debug(f"Migration {version} was idempotent (already applied)")
                        applied.append(version)  # Still counts as "processed"
                except Exception as e:
                    logger.error(f"Migration {version} failed: {e}")
                    raise

            return applied
        finally:
            conn.close()

    def rollback_to(self, target_version: str | None = None) -> bool:
        """
        Rollback migrations down to (but not including) target_version.

        If target_version is None, rolls back all migrations.

        Args:
            target_version: Version to rollback to. All migrations after this
                          version will be rolled back.

        Returns:
            True if rollback was successful, False otherwise.
        """
        migrations = _load_migrations()
        migrations_to_rollback: list[tuple[str, RollbackFunc | None]]

        if target_version is None:
            # Rollback all
            migrations_to_rollback = [(v, rb) for v, _, rb in reversed(migrations)]
        else:
            # Rollback only migrations after target_version
            found_target = False
            migrations_to_rollback = []
            for version, _, rollback_fn in reversed(migrations):
                if version == target_version:
                    found_target = True
                    break
                migrations_to_rollback.append((version, rollback_fn))

            if not found_target:
                logger.error(f"Target version {target_version} not found in migrations")
                return False

        conn = self._get_connection()
        try:
            for version, rollback_fn in migrations_to_rollback:
                if rollback_fn is None:
                    logger.warning(f"Migration {version} has no rollback, skipping")
                    continue

                logger.info(f"Rolling back migration {version}...")
                try:
                    rollback_fn(conn)
                    logger.info(f"Migration {version} rolled back successfully")
                except Exception as e:
                    logger.error(f"Rollback of {version} failed: {e}")
                    return False

            return True
        finally:
            conn.close()

    def get_migration_status(self) -> dict:
        """
        Get the status of all migrations.

        Returns:
            Dict with 'current_version', 'applied_versions', 'pending_versions',
            and 'migrations' list with status for each.
        """
        migrations = _load_migrations()
        applied = set(self.get_applied_versions())

        pending = [version for version, _, _ in migrations if version not in applied]

        migration_status = []
        for version, _, rollback_fn in migrations:
            status = "applied" if version in applied else "pending"
            migration_status.append(
                {
                    "version": version,
                    "status": status,
                    "can_rollback": rollback_fn is not None,
                }
            )

        return {
            "current_version": self.get_current_version(),
            "applied_versions": list(applied),
            "pending_versions": pending,
            "migrations": migration_status,
        }
