"""
BackupManager - Creates and manages timestamped backups of .muscle/ directory (MUS-030).

Architecture:
- Creates timestamped snapshots of .muscle/ directory or specific files
- Stores backup metadata (type, path, checksum, size, retention) in project_memory.db
- Supports full, claude_md, config, and memory backup types
- Prunes backups older than retention_days (default 30)
- Uses SHA256 for checksums
- Backups stored in .muscle/backups/<type>/<timestamp>/
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)

BackupType = Literal["full", "claude_md", "config", "memory"]

# Fix: BK-03. Runtime-checkable allowlist for ``BackupType`` so invalid values
# supplied by older callers or tests are rejected at the boundary rather than
# silently persisted.
VALID_BACKUP_TYPES: frozenset[str] = frozenset({"full", "claude_md", "config", "memory"})


def _assert_backup_type(backup_type: str) -> None:
    if backup_type not in VALID_BACKUP_TYPES:
        raise ValueError(
            f"Unknown backup_type {backup_type!r}; expected one of {sorted(VALID_BACKUP_TYPES)}"
        )


DEFAULT_RETENTION_DAYS = 30


@dataclass
class BackupInfo:
    """Metadata for a single backup, returned by list_backups."""

    id: int
    backup_type: str
    file_path: str
    checksum: str | None
    size_bytes: int
    created_at: str
    retention_days: int


class BackupManager:
    """
    Creates, lists, inspects, and prunes timestamped backups of .muscle/ directory.

    Args:
        project_memory: ProjectMemory instance for DB access.
        project_path: Absolute path to the project root.
        retention_days: How many days to keep backups before pruning (default 30).
    """

    def __init__(
        self,
        project_memory: ProjectMemory,
        project_path: str,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ):
        self._pm = project_memory
        self._project_path = Path(project_path).resolve()
        self._muscle_dir = self._project_path / ".muscle"
        self._backups_dir = self._muscle_dir / "backups"
        self._retention_days = retention_days

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def create_backup(
        self,
        backup_type: BackupType,
        force: bool = False,
    ) -> BackupInfo | None:
        """
        Create a new backup of the specified type.

        Args:
            backup_type: One of "full", "claude_md", "config", "memory".
            force: If True, overwrite existing backup for this type today.
                   If False (default), skip if a backup of this type already
                   exists for today.

        Returns:
            BackupInfo on success, None if skipped (non-force duplicate).
        Raises:
            ValueError: If backup_type is not recognized.
            FileNotFoundError: If the target path to back up does not exist.
        """
        _assert_backup_type(backup_type)  # Fix: BK-03
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        created_at = datetime.now().isoformat()
        source_paths, archive_path = self._resolve_backup_sources(backup_type, timestamp)
        for src in source_paths:
            if not src.exists():
                raise FileNotFoundError(f"Backup source not found: {src}")

        temp_parent = self._backups_dir / backup_type
        temp_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f"{backup_type}-{timestamp}-", dir=temp_parent))
        temp_archive_path = temp_dir / archive_path.name

        checksum = self._create_archive(
            archive_path=temp_archive_path,
            source_paths=source_paths,
            project_root=self._project_path,
        )
        size_bytes = temp_archive_path.stat().st_size

        archive_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_archive_path, archive_path)

        try:
            backup_record = self._pm.insert_backup_with_action(
                project_path=str(self._project_path),
                created_at=created_at,
                backup_type=backup_type,
                file_path=str(archive_path),
                checksum=checksum,
                size_bytes=size_bytes,
                retention_days=self._retention_days,
                action_details_json=(
                    f'{{"backup_type": "{backup_type}", "size_bytes": {size_bytes}}}'
                ),
            )
        except Exception:
            archive_path.unlink(missing_ok=True)
            if archive_path.parent.exists():
                try:
                    archive_path.parent.rmdir()
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return BackupInfo(
            id=backup_record,
            backup_type=backup_type,
            file_path=str(archive_path),
            checksum=checksum,
            size_bytes=size_bytes,
            created_at=created_at,
            retention_days=self._retention_days,
        )

    def create_file_backup(
        self,
        source_path: Path,
        backup_type: BackupType = "claude_md",
    ) -> BackupInfo:
        """Create a backup for an explicit project file."""
        _assert_backup_type(backup_type)
        source = source_path.resolve()
        try:
            source.relative_to(self._project_path)
        except ValueError as exc:
            raise ValueError(f"Backup source is outside project root: {source}") from exc
        if not source.exists():
            raise FileNotFoundError(f"Backup source not found: {source}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        created_at = datetime.now().isoformat()
        safe_name = source.relative_to(self._project_path).as_posix().replace("/", "__")
        archive_path = (
            self._backups_dir / backup_type / timestamp / f"{safe_name}.{backup_type}.tar.gz"
        )
        temp_parent = self._backups_dir / backup_type
        temp_parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f"{backup_type}-{timestamp}-", dir=temp_parent))
        temp_archive_path = temp_dir / archive_path.name

        checksum = self._create_archive(
            archive_path=temp_archive_path,
            source_paths=[source],
            project_root=self._project_path,
        )
        size_bytes = temp_archive_path.stat().st_size
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_archive_path, archive_path)

        try:
            backup_record = self._pm.insert_backup_with_action(
                project_path=str(self._project_path),
                created_at=created_at,
                backup_type=backup_type,
                file_path=str(archive_path),
                checksum=checksum,
                size_bytes=size_bytes,
                retention_days=self._retention_days,
                action_details_json=(
                    f'{{"backup_type": "{backup_type}", '
                    f'"source_path": "{source.relative_to(self._project_path).as_posix()}", '
                    f'"size_bytes": {size_bytes}}}'
                ),
            )
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        return BackupInfo(
            id=backup_record,
            backup_type=backup_type,
            file_path=str(archive_path),
            checksum=checksum,
            size_bytes=size_bytes,
            created_at=created_at,
            retention_days=self._retention_days,
        )

    def list_backups(
        self,
        backup_type: BackupType | None = None,
        limit: int = 100,
    ) -> list[BackupInfo]:
        """
        List backups sorted by created_at descending.

        Args:
            backup_type: Optional filter by backup type.
            limit: Maximum number of results to return.
        """
        rows = self._pm.list_backups(
            project_path=str(self._project_path),
            backup_type=backup_type,
            limit=limit,
        )
        return [
            BackupInfo(
                id=r["id"],
                backup_type=r["backup_type"],
                file_path=r["file_path"],
                checksum=r["checksum"],
                size_bytes=r["size_bytes"],
                created_at=r["created_at"],
                retention_days=r["retention_days"],
            )
            for r in rows
        ]

    def inspect_backup(self, backup_id: int) -> dict | None:
        """
        Return metadata for a backup, including what it contains.

        Args:
            backup_id: The ID of the backup record in the DB.

        Returns:
            A dict with backup metadata plus a `contents` list of files inside
            the archive, or None if the backup record is not found.
        """
        row = self._pm.get_backup(backup_id)
        if not row:
            return None

        archive_path = Path(row["file_path"])
        contents: list[dict] = []

        if archive_path.exists() and archive_path.suffix in (".tar", ".gz", ".tgz"):
            try:
                with tarfile.open(archive_path, "r:*") as tf:
                    contents = [
                        {
                            "name": ti.name,
                            "size": ti.size,
                            "isdir": ti.isdir(),
                        }
                        for ti in tf.getmembers()
                    ]
            except Exception as e:
                logger.warning(f"Could not read archive {archive_path}: {e}")
                contents = []

        return {
            "id": row["id"],
            "project_path": row["project_path"],
            "created_at": row["created_at"],
            "backup_type": row["backup_type"],
            "file_path": row["file_path"],
            "checksum": row["checksum"],
            "size_bytes": row["size_bytes"],
            "retention_days": row["retention_days"],
            "contents": contents,
        }

    def prune(self, backup_type: BackupType | None = None) -> int:
        """
        Remove backups older than retention_days (default 30).

        Also runs a lightweight integrity sweep (Fix: BK-02) that reconciles
        DB rows with archives on disk: DB rows without an archive are dropped,
        and ``.tar.gz`` files in the backups directory that do not appear in
        the DB are logged so an operator can clean them up manually.

        Args:
            backup_type: Optional filter to only prune this type.

        Returns:
            Number of backups pruned.
        """
        orphan_rows_dropped = self._drop_orphan_rows(backup_type)
        self._log_orphan_archives(backup_type)

        cutoff = datetime.now() - timedelta(days=self._retention_days)
        cutoff_iso = cutoff.isoformat()

        backups = self._pm.list_backups(
            project_path=str(self._project_path),
            backup_type=backup_type,
            limit=1000,
        )

        count = 0
        for row in backups:
            if row["created_at"] < cutoff_iso:
                archive_path = Path(row["file_path"])
                if archive_path.exists():
                    try:
                        shutil.rmtree(archive_path.parent)
                    except OSError as e:
                        logger.warning(f"Failed to remove backup archive {archive_path}: {e}")
                self._pm.delete_backup(row["id"])
                count += 1

        logger.info(
            "Pruned %d backup(s) older than %d days (plus %d orphan DB rows)",
            count,
            self._retention_days,
            orphan_rows_dropped,
        )
        return count

    def _drop_orphan_rows(self, backup_type: BackupType | None) -> int:
        """Remove DB rows whose archive no longer exists on disk."""
        rows = self._pm.list_backups(
            project_path=str(self._project_path),
            backup_type=backup_type,
            limit=1000,
        )
        dropped = 0
        for row in rows:
            archive_path = Path(row["file_path"])
            if not archive_path.exists():
                logger.warning(
                    "Dropping orphan backup row id=%s (archive missing: %s)",
                    row["id"],
                    archive_path,
                )
                try:
                    self._pm.delete_backup(row["id"])
                    dropped += 1
                except Exception as exc:
                    logger.error("Failed to delete orphan backup row %s: %s", row["id"], exc)
        return dropped

    def _log_orphan_archives(self, backup_type: BackupType | None) -> None:
        """Warn about archive files on disk that have no matching DB row."""
        if not self._backups_dir.exists():
            return
        known = {
            Path(row["file_path"]).resolve()
            for row in self._pm.list_backups(
                project_path=str(self._project_path),
                backup_type=backup_type,
                limit=10_000,
            )
        }
        roots = (
            [self._backups_dir / backup_type] if backup_type else list(self._backups_dir.iterdir())
        )
        for root in roots:
            if not root.is_dir():
                continue
            for archive in root.rglob("*.tar*"):
                if archive.resolve() not in known:
                    logger.warning("Orphan backup archive on disk (no DB row): %s", archive)

    def restore_backup(
        self,
        backup_id: int,
        dry_run: bool = False,
    ) -> dict | None:
        """
        Restore files from a backup archive.

        Args:
            backup_id: The ID of the backup record in the DB.
            dry_run: If True, return what would be restored without making changes.

        Returns:
            A dict with restoration details (files, sizes, destination), or None
            if the backup record is not found.
        """
        row = self._pm.get_backup(backup_id)
        if not row:
            return None

        archive_path = Path(row["file_path"])
        if not archive_path.exists() or archive_path.suffix not in (".tar", ".gz", ".tgz"):
            return {
                "id": backup_id,
                "error": f"Archive not found or invalid: {archive_path}",
                "files": [],
                "dry_run": dry_run,
            }

        extracted: list[dict] = []
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                members = tf.getmembers()
                restorable_members: list[tuple[tarfile.TarInfo, Path]] = []

                for ti in members:
                    destination = self._resolve_restore_destination(ti.name)
                    info: dict = {
                        "name": ti.name,
                        "size": ti.size,
                        "isdir": ti.isdir(),
                        "destination": str(destination),
                    }
                    extracted.append(info)
                    restorable_members.append((ti, destination))

            if dry_run:
                return {
                    "id": backup_id,
                    "backup_type": row["backup_type"],
                    "archive_path": str(archive_path),
                    "files": extracted,
                    "dry_run": True,
                    "message": f"[dry-run] Would restore {len(extracted)} file(s) from backup #{backup_id}",
                }

            restored_count = self._restore_members_atomically(archive_path, restorable_members)

            self._pm.insert_action_log(
                project_path=str(self._project_path),
                action_type="restore",
                entity_type="backup",
                entity_id=backup_id,
                details_json=f'{{"backup_type": "{row["backup_type"]}", "restored_count": {restored_count}}}',
            )

            return {
                "id": backup_id,
                "backup_type": row["backup_type"],
                "archive_path": str(archive_path),
                "files": extracted,
                "dry_run": False,
                "restored_count": restored_count,
                "message": f"Restored {restored_count} file(s) from backup #{backup_id}",
            }

        except Exception as e:
            logger.warning(f"Failed to restore backup {backup_id}: {e}")
            return {
                "id": backup_id,
                "error": str(e),
                "files": [],
                "dry_run": dry_run,
            }

    def describe_backup_scope(
        self, global_system_db_path: str | Path | None = None
    ) -> dict[str, object]:
        """Describe which MUSCLE storage surfaces are covered by project backups."""
        system_db_path = (
            Path(global_system_db_path).expanduser() if global_system_db_path is not None else None
        )
        included_paths = [
            str(self._muscle_dir),
            str(self._muscle_dir / "project_memory.db"),
            str(self._project_path / "CLAUDE.md"),
        ]
        excluded_paths: list[dict[str, str]] = []
        if system_db_path is not None:
            excluded_paths.append(
                {
                    "path": str(system_db_path),
                    "reason": (
                        "Global MUSCLE system database is shared across projects and is not "
                        "included in project-local backups."
                    ),
                }
            )
        return {
            "project_root": str(self._project_path),
            "backups_dir": str(self._backups_dir),
            "included_paths": included_paths,
            "excluded_paths": excluded_paths,
            "restore_guidance": [
                "Restore the project backup first to recover project-local .muscle state.",
                (
                    f"Back up and restore {system_db_path} separately if you need global "
                    "cross-project, model-pack, or submission metadata."
                    if system_db_path is not None
                    else "Back up and restore the global MUSCLE system database separately if needed."
                ),
            ],
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _resolve_backup_sources(
        self,
        backup_type: BackupType,
        timestamp: str,
    ) -> tuple[list[Path], Path]:
        """Return (source_paths, archive_path) for the given backup_type."""
        archive_path = self._backups_dir / backup_type / timestamp / f"{backup_type}.tar.gz"

        if backup_type == "full":
            return [self._muscle_dir], archive_path
        elif backup_type == "claude_md":
            root_claude = self._project_path / "CLAUDE.md"
            return [root_claude], archive_path
        elif backup_type == "config":
            config = self._muscle_dir / "config.yaml"
            return [config], archive_path
        elif backup_type == "memory":
            db_path = self._muscle_dir / "project_memory.db"
            return [db_path], archive_path
        else:
            raise ValueError(f"Unknown backup type: {backup_type}")

    @staticmethod
    def _create_archive(archive_path: Path, source_paths: list[Path], project_root: Path) -> str:
        """Create a gzip-compressed tar archive and return its SHA256 hexdigest."""
        sha256 = hashlib.sha256()

        with tarfile.open(archive_path, "w:gz") as tf:
            for src in source_paths:
                arcname = BackupManager._archive_name_for_source(project_root, src)
                if src.is_file():
                    tf.add(src, arcname=arcname)
                elif src.is_dir():
                    tf.add(src, arcname=arcname)

        with open(archive_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        return sha256.hexdigest()

    @staticmethod
    def _archive_name_for_source(project_root: Path, source_path: Path) -> str:
        """Return the archive member name relative to the project root."""
        try:
            return str(source_path.resolve().relative_to(project_root.resolve()))
        except ValueError:
            return source_path.name

    def _resolve_restore_destination(self, member_name: str) -> Path:
        """Resolve a tar member to a safe destination within the project root."""
        relative_path = Path(member_name)
        if relative_path.is_absolute():
            raise ValueError(f"Refusing to restore absolute archive path: {member_name}")

        destination = (self._project_path / relative_path).resolve()
        project_root = self._project_path.resolve()
        if destination != project_root and project_root not in destination.parents:
            raise ValueError(
                f"Refusing to restore archive path outside project root: {member_name}"
            )

        return destination

    def _restore_members_atomically(
        self,
        archive_path: Path,
        restorable_members: list[tuple[tarfile.TarInfo, Path]],
    ) -> int:
        """Stage archive members first, then apply them with rollback on failure."""
        project_root = self._project_path.resolve()

        with tempfile.TemporaryDirectory(
            dir=str(self._muscle_dir),
            prefix="restore-staging-",
        ) as staging_dir:
            staging_root = Path(staging_dir)
            staged_members: list[tuple[tarfile.TarInfo, Path, Path]] = []

            with tarfile.open(archive_path, "r:*") as tf:
                for ti, dst in restorable_members:
                    relative_destination = dst.resolve().relative_to(project_root)
                    staged_path = staging_root / relative_destination

                    if ti.isdir():
                        staged_path.mkdir(parents=True, exist_ok=True)
                        staged_members.append((ti, dst, staged_path))
                        continue

                    if not ti.isfile():
                        logger.warning(
                            f"Skipping unsupported archive entry during restore: {ti.name}"
                        )
                        continue

                    extracted_file = tf.extractfile(ti)
                    if extracted_file is None:
                        raise ValueError(f"Could not extract archive member: {ti.name}")

                    staged_path.parent.mkdir(parents=True, exist_ok=True)
                    with extracted_file, open(staged_path, "wb") as out_file:
                        shutil.copyfileobj(extracted_file, out_file)

                    os.chmod(staged_path, ti.mode)
                    os.utime(staged_path, (ti.mtime, ti.mtime))
                    staged_members.append((ti, dst, staged_path))

            with tempfile.TemporaryDirectory(
                dir=str(self._muscle_dir),
                prefix="restore-rollback-",
            ) as rollback_dir:
                rollback_root = Path(rollback_dir)
                backed_up_files: dict[Path, Path] = {}
                created_files: list[Path] = []
                applied_files: list[Path] = []
                restored_count = 0

                try:
                    for ti, dst, staged_path in staged_members:
                        if ti.isdir():
                            dst.mkdir(parents=True, exist_ok=True)
                            continue

                        dst.parent.mkdir(parents=True, exist_ok=True)

                        if dst.exists():
                            rollback_path = rollback_root / dst.relative_to(project_root)
                            rollback_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(dst, rollback_path)
                            backed_up_files[dst] = rollback_path
                        else:
                            created_files.append(dst)

                        os.replace(staged_path, dst)
                        applied_files.append(dst)
                        os.chmod(dst, ti.mode)
                        os.utime(dst, (ti.mtime, ti.mtime))
                        restored_count += 1
                except Exception:
                    self._rollback_restore(backed_up_files, created_files, applied_files)
                    raise

        return restored_count

    @staticmethod
    def _rollback_restore(
        backed_up_files: dict[Path, Path],
        created_files: list[Path],
        applied_files: list[Path],
    ) -> None:
        """Restore pre-restore file contents after a failed apply step."""
        for dst in reversed(applied_files):
            rollback_path = backed_up_files.get(dst)
            if rollback_path is not None and rollback_path.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(rollback_path, dst)
                continue

            if dst in created_files and dst.exists():
                dst.unlink()
