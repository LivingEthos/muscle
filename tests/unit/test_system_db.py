"""
Unit tests for the global SystemDatabase safety surface.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tools.muscle.project_memory import ProjectMemory
from tools.muscle.project_memory_types import ProjectFingerprint
from tools.muscle.system_db import CURRENT_SYSTEM_SCHEMA_VERSION, SystemDatabase


def test_system_db_initializes_schema_version_and_integrity(tmp_path: Path) -> None:
    db_path = tmp_path / "system.db"
    system_db = SystemDatabase(db_path)
    system_db.register_project(
        ProjectFingerprint(
            project_path=str(tmp_path / "project-a"),
            display_name="project-a",
            languages=["Python"],
            frameworks=["FastAPI"],
            dependencies=["pydantic"],
            archetypes=["api"],
            fingerprint_hash="abc123",
        )
    )

    reopened = SystemDatabase(db_path)
    integrity = reopened.verify_integrity()
    with sqlite3.connect(str(db_path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert reopened.get_current_version() == CURRENT_SYSTEM_SCHEMA_VERSION
    assert CURRENT_SYSTEM_SCHEMA_VERSION in reopened.get_applied_versions()
    assert integrity["integrity_ok"] is True
    assert "schema_version" in tables
    assert "registered_projects" in tables
    assert len(reopened.list_registered_projects()) == 1


def test_system_db_reopens_versionless_schema_and_preserves_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "system.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE registered_projects (
                project_path TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                fingerprint_json TEXT NOT NULL DEFAULT '{}',
                languages_json TEXT NOT NULL DEFAULT '[]',
                frameworks_json TEXT NOT NULL DEFAULT '[]',
                dependency_summary_json TEXT NOT NULL DEFAULT '[]',
                last_seen TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO registered_projects (
                project_path,
                display_name,
                fingerprint_json,
                languages_json,
                frameworks_json,
                dependency_summary_json,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(tmp_path / "legacy-project"),
                "legacy-project",
                "{}",
                '["Python"]',
                '["FastAPI"]',
                '["pydantic"]',
                "2026-04-16T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    system_db = SystemDatabase(db_path)

    rows = system_db.list_registered_projects()
    assert system_db.get_current_version() == CURRENT_SYSTEM_SCHEMA_VERSION
    assert len(rows) == 1
    assert rows[0]["display_name"] == "legacy-project"


def test_project_memory_and_system_db_remain_path_isolated(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir(parents=True, exist_ok=True)
    pm = ProjectMemory(str(project_path))
    system_db_path = tmp_path / "global" / "system.db"
    system_db = SystemDatabase(system_db_path)

    task_id = pm.insert_task(
        project_path=str(project_path),
        created_at="2026-04-16T00:00:00",
        title="isolated task",
        description="verify storage boundary",
        status="success",
        outcome="ok",
        token_cost=5,
        duration_ms=10,
    )
    system_db.register_project(
        ProjectFingerprint(
            project_path=str(project_path),
            display_name="project",
            languages=["Python"],
            frameworks=["Click"],
            dependencies=["rich"],
            archetypes=["cli"],
            fingerprint_hash="project-hash",
        )
    )

    project_conn = sqlite3.connect(str(project_path / ".muscle" / "project_memory.db"))
    system_conn = sqlite3.connect(str(system_db_path))
    try:
        project_tables = {
            row[0]
            for row in project_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        system_tables = {
            row[0]
            for row in system_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        project_conn.close()
        system_conn.close()

    assert pm.get_task(task_id)["title"] == "isolated task"
    assert len(system_db.list_registered_projects()) == 1
    assert "tasks" in project_tables
    assert "registered_projects" not in project_tables
    assert "registered_projects" in system_tables
    assert "tasks" not in system_tables
