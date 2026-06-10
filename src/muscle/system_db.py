"""
Global system database for MUSCLE cross-project metadata and model packs.

Architecture Decision Record (ADR):
- Keep non-project-owned metadata out of per-project databases
- Use a lightweight SQLite file at ``~/.muscle/system.db``
- Store related-project registry, model aliases, installed packs, and
  community submission state in one place
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .model_pack_validation import validate_model_pack_lesson, validate_model_pack_metadata
from .project_memory_types import (
    ModelIdentity,
    ModelPackLesson,
    ModelPackMetadata,
    PackSubmissionRecord,
    ProjectFingerprint,
)

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_DB_PATH = Path("~/.muscle/system.db").expanduser()
CURRENT_SYSTEM_SCHEMA_VERSION = "1.0.0"


class SystemDatabase:
    """SQLite access layer for MUSCLE's global, non-project-owned metadata."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path).expanduser() if db_path else DEFAULT_SYSTEM_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
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
                """
                CREATE TABLE IF NOT EXISTS registered_projects (
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS model_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_label TEXT NOT NULL,
                    endpoint_fingerprint TEXT,
                    canonical_model_key TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.0,
                    source TEXT NOT NULL DEFAULT 'heuristic',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(provider_label, endpoint_fingerprint, canonical_model_key)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS installed_model_packs (
                    canonical_model_key TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    source_repo TEXT,
                    source_repo_commit TEXT,
                    install_status TEXT NOT NULL DEFAULT 'installed',
                    pack_path TEXT,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS model_pack_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_model_key TEXT NOT NULL,
                    lesson_key TEXT NOT NULL,
                    lesson_text TEXT NOT NULL,
                    scope_tags_json TEXT NOT NULL DEFAULT '[]',
                    safety_scope TEXT NOT NULL,
                    portability TEXT NOT NULL DEFAULT 'portable',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    rationale TEXT,
                    source_repo_commit TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(canonical_model_key, lesson_key)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pack_submission_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    export_id TEXT NOT NULL UNIQUE,
                    canonical_model_key TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    pr_url TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

            indexes = [
                (
                    "idx_registered_projects_last_seen",
                    "CREATE INDEX IF NOT EXISTS idx_registered_projects_last_seen "
                    "ON registered_projects(last_seen DESC)",
                ),
                (
                    "idx_model_aliases_lookup",
                    "CREATE INDEX IF NOT EXISTS idx_model_aliases_lookup "
                    "ON model_aliases(provider_label, endpoint_fingerprint, confidence DESC)",
                ),
                (
                    "idx_model_pack_lessons_model",
                    "CREATE INDEX IF NOT EXISTS idx_model_pack_lessons_model "
                    "ON model_pack_lessons(canonical_model_key, portability)",
                ),
                (
                    "idx_pack_submission_history_model",
                    "CREATE INDEX IF NOT EXISTS idx_pack_submission_history_model "
                    "ON pack_submission_history(canonical_model_key, status)",
                ),
            ]
            for _name, statement in indexes:
                cursor.execute(statement)
            cursor.execute(
                """
                INSERT OR IGNORE INTO schema_version (version, applied_at)
                VALUES (?, ?)
                """,
                (CURRENT_SYSTEM_SCHEMA_VERSION, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_current_version(self) -> str | None:
        """Return the newest recorded system DB schema version."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT version FROM schema_version ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return str(row["version"]) if row else None
        finally:
            conn.close()

    def get_applied_versions(self) -> list[str]:
        """Return all recorded system DB schema versions."""
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT version FROM schema_version ORDER BY id").fetchall()
            return [str(row["version"]) for row in rows]
        finally:
            conn.close()

    def verify_integrity(self) -> dict[str, Any]:
        """Run SQLite integrity checks for the system database."""
        conn = self._get_connection()
        try:
            integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            integrity_messages = [str(row[0]) for row in integrity_rows]
            foreign_key_issues = [tuple(row) for row in foreign_key_rows]
            integrity_ok = integrity_messages == ["ok"]
            return {
                "path": str(self.db_path),
                "schema_version": self.get_current_version(),
                "integrity_ok": integrity_ok,
                "integrity_messages": integrity_messages,
                "foreign_key_ok": len(foreign_key_issues) == 0,
                "foreign_key_issues": foreign_key_issues,
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Registered projects
    # ------------------------------------------------------------------

    def register_project(self, fingerprint: ProjectFingerprint) -> None:
        """Register or refresh a project fingerprint in the global catalog."""
        conn = self._get_connection()
        try:
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
                ON CONFLICT(project_path) DO UPDATE SET
                    display_name = excluded.display_name,
                    fingerprint_json = excluded.fingerprint_json,
                    languages_json = excluded.languages_json,
                    frameworks_json = excluded.frameworks_json,
                    dependency_summary_json = excluded.dependency_summary_json,
                    last_seen = excluded.last_seen
                """,
                (
                    fingerprint.project_path,
                    fingerprint.display_name,
                    json.dumps(asdict(fingerprint), sort_keys=True),
                    json.dumps(fingerprint.languages, sort_keys=True),
                    json.dumps(fingerprint.frameworks, sort_keys=True),
                    json.dumps(fingerprint.dependencies[:20], sort_keys=True),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_project_state(
        row: dict[str, Any],
        stale_after_days: int | None,
    ) -> dict[str, Any]:
        project_path = Path(str(row.get("project_path", ""))).expanduser()
        path_exists = project_path.exists()
        last_seen_raw = str(row.get("last_seen", ""))
        age_days: int | None = None
        if last_seen_raw:
            try:
                age_days = max(0, (datetime.now() - datetime.fromisoformat(last_seen_raw)).days)
            except ValueError:
                age_days = None
        stale = (not path_exists) or (
            stale_after_days is not None and age_days is not None and age_days > stale_after_days
        )

        enriched = dict(row)
        enriched["path_exists"] = path_exists
        enriched["age_days"] = age_days
        enriched["stale"] = stale
        return enriched

    def list_registered_projects(
        self,
        exclude_path: str | None = None,
        stale_after_days: int | None = None,
        include_stale: bool = True,
    ) -> list[dict[str, Any]]:
        """Return registered project rows as dictionaries."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM registered_projects"
            params: list[Any] = []
            if exclude_path:
                query += " WHERE project_path != ?"
                params.append(exclude_path)
            query += " ORDER BY last_seen DESC"
            rows = conn.execute(query, params).fetchall()
            hydrated = [
                self._row_project_state(dict(row), stale_after_days=stale_after_days)
                for row in rows
            ]
            if include_stale:
                return hydrated
            return [row for row in hydrated if not bool(row.get("stale"))]
        finally:
            conn.close()

    def prune_registered_projects(
        self,
        stale_after_days: int = 90,
        missing_only: bool = False,
        keep_paths: list[str] | None = None,
    ) -> dict[str, int]:
        """Remove missing or stale registered projects from the global catalog."""
        keep = {str(Path(path).expanduser().resolve()) for path in (keep_paths or [])}
        rows = self.list_registered_projects(stale_after_days=stale_after_days, include_stale=True)
        removable: list[dict[str, Any]] = []
        for row in rows:
            project_path = str(Path(str(row.get("project_path", ""))).expanduser().resolve())
            if project_path in keep:
                continue
            if not bool(row.get("path_exists")):
                removable.append(row)
                continue
            if not missing_only and bool(row.get("stale")):
                removable.append(row)

        if not removable:
            return {"removed": 0, "missing_removed": 0, "stale_removed": 0}

        conn = self._get_connection()
        try:
            conn.executemany(
                "DELETE FROM registered_projects WHERE project_path = ?",
                [(str(row.get("project_path", "")),) for row in removable],
            )
            conn.commit()
        finally:
            conn.close()

        missing_removed = sum(1 for row in removable if not bool(row.get("path_exists")))
        stale_removed = len(removable) - missing_removed
        return {
            "removed": len(removable),
            "missing_removed": missing_removed,
            "stale_removed": stale_removed,
        }

    # ------------------------------------------------------------------
    # Model aliases and packs
    # ------------------------------------------------------------------

    def upsert_model_alias(
        self,
        provider_label: str,
        canonical_model_key: str,
        endpoint_fingerprint: str | None = None,
        confidence: float = 0.8,
        source: str = "heuristic",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a known label -> canonical model mapping."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO model_aliases (
                    provider_label,
                    endpoint_fingerprint,
                    canonical_model_key,
                    confidence,
                    source,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_label, endpoint_fingerprint, canonical_model_key) DO UPDATE SET
                    confidence = excluded.confidence,
                    source = excluded.source,
                    metadata_json = excluded.metadata_json
                """,
                (
                    provider_label,
                    endpoint_fingerprint,
                    canonical_model_key,
                    confidence,
                    source,
                    json.dumps(metadata or {}, sort_keys=True),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def resolve_alias(
        self,
        provider_label: str | None,
        endpoint_fingerprint: str | None = None,
    ) -> ModelIdentity | None:
        """Look up a persisted alias mapping for a requested label."""
        if not provider_label:
            return None
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT *
                FROM model_aliases
                WHERE provider_label = ?
                  AND (
                    endpoint_fingerprint = ?
                    OR endpoint_fingerprint IS NULL
                  )
                ORDER BY
                    CASE WHEN endpoint_fingerprint = ? THEN 1 ELSE 0 END DESC,
                    confidence DESC
                LIMIT 1
                """,
                (provider_label, endpoint_fingerprint, endpoint_fingerprint),
            ).fetchone()
            if row is None:
                return None
            return ModelIdentity(
                requested_label=provider_label,
                provider_endpoint=None,
                provider_fingerprint=endpoint_fingerprint,
                canonical_model_key=row["canonical_model_key"],
                identity_source=row["source"],
                confidence=float(row["confidence"] or 0.0),
                manual_override=False,
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
        finally:
            conn.close()

    def upsert_model_pack(
        self, metadata: ModelPackMetadata, lessons: list[ModelPackLesson]
    ) -> None:
        """Install or refresh a model pack and its lessons."""
        validate_model_pack_metadata(metadata)
        normalized_lessons = [
            validate_model_pack_lesson(
                lesson,
                expected_canonical_model_key=metadata.canonical_model_key,
            )
            for lesson in lessons
        ]
        now = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO installed_model_packs (
                    canonical_model_key,
                    version,
                    source_repo,
                    source_repo_commit,
                    install_status,
                    pack_path,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_model_key) DO UPDATE SET
                    version = excluded.version,
                    source_repo = excluded.source_repo,
                    source_repo_commit = excluded.source_repo_commit,
                    install_status = excluded.install_status,
                    pack_path = excluded.pack_path,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    metadata.canonical_model_key,
                    metadata.version,
                    metadata.source_repo,
                    metadata.source_repo_commit,
                    metadata.install_status,
                    metadata.pack_path,
                    now,
                    json.dumps(metadata.metadata, sort_keys=True),
                ),
            )
            conn.execute(
                "DELETE FROM model_pack_lessons WHERE canonical_model_key = ?",
                (metadata.canonical_model_key,),
            )
            for lesson in normalized_lessons:
                conn.execute(
                    """
                    INSERT INTO model_pack_lessons (
                        canonical_model_key,
                        lesson_key,
                        lesson_text,
                        scope_tags_json,
                        safety_scope,
                        portability,
                        evidence_json,
                        rationale,
                        source_repo_commit,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lesson.canonical_model_key,
                        lesson.lesson_key,
                        lesson.lesson_text,
                        json.dumps(sorted(set(lesson.scope_tags))),
                        lesson.safety_scope,
                        lesson.portability,
                        json.dumps(lesson.evidence, sort_keys=True),
                        lesson.rationale,
                        lesson.source_repo_commit,
                        now,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def list_model_packs(self) -> list[dict[str, Any]]:
        """List installed model pack metadata rows."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM installed_model_packs
                ORDER BY canonical_model_key
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_model_pack_lessons(self, canonical_model_key: str) -> list[dict[str, Any]]:
        """Fetch lessons for one canonical model key."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM model_pack_lessons
                WHERE canonical_model_key = ?
                ORDER BY lesson_key
                """,
                (canonical_model_key,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Submission history
    # ------------------------------------------------------------------

    def get_submission(self, export_id: str) -> dict[str, Any] | None:
        """Return a previously recorded submission by export ID."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM pack_submission_history WHERE export_id = ?",
                (export_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def find_submission_by_fingerprint(
        self,
        *,
        repo: str,
        canonical_model_key: str,
        submission_fingerprint: str,
    ) -> dict[str, Any] | None:
        """Return the most recent submission with one matching content fingerprint."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                """
                SELECT *
                FROM pack_submission_history
                WHERE repo = ? AND canonical_model_key = ?
                ORDER BY updated_at DESC
                """,
                (repo, canonical_model_key),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            record = dict(row)
            try:
                metadata = json.loads(str(record.get("metadata_json") or "{}"))
            except json.JSONDecodeError:
                metadata = {}
            if not isinstance(metadata, dict):
                continue
            if str(metadata.get("submission_fingerprint") or "") == submission_fingerprint:
                return record
        return None

    def upsert_submission(self, record: PackSubmissionRecord) -> None:
        """Create or refresh a submission-history entry."""
        now = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO pack_submission_history (
                    export_id,
                    canonical_model_key,
                    repo,
                    branch,
                    pr_url,
                    status,
                    created_at,
                    updated_at,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(export_id) DO UPDATE SET
                    branch = excluded.branch,
                    pr_url = excluded.pr_url,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    record.export_id,
                    record.canonical_model_key,
                    record.repo,
                    record.branch,
                    record.pr_url,
                    record.status,
                    now,
                    now,
                    json.dumps(record.metadata, sort_keys=True),
                ),
            )
            conn.commit()
        finally:
            conn.close()
