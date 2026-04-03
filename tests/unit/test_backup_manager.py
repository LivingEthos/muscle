"""
Tests for backup_manager.py (MUS-030).
"""

import os
import tempfile
import time

from tools.muscle.backup_manager import BackupManager, BackupType


class TestBackupManager:
    """Tests for BackupManager class."""

    def _make_pm_and_bm(self, tmpdir: str):
        """Create a ProjectMemory and BackupManager pair for testing."""
        from tools.muscle.project_memory import ProjectMemory
        pm = ProjectMemory(tmpdir)
        return pm, BackupManager(pm, tmpdir, retention_days=7)

    def test_backup_manager_init(self):
        """BackupManager initializes correctly."""
        from tools.muscle.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            pm = ProjectMemory(tmpdir)
            bm = BackupManager(pm, tmpdir)
            assert bm._project_path.name == os.path.basename(tmpdir)
            assert bm._retention_days == 30  # default

    def test_backup_manager_custom_retention(self):
        """BackupManager respects custom retention_days."""
        from tools.muscle.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            pm = ProjectMemory(tmpdir)
            bm = BackupManager(pm, tmpdir, retention_days=7)
            assert bm._retention_days == 7

    def test_create_full_backup(self):
        """create_backup('full') produces a tar.gz and a DB record."""
        pm, bm = self._make_pm_and_bm(tempfile.mkdtemp())

        # Create some content in .muscle/
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")
        bm._muscle_dir.joinpath("CLAUDE.md").write_text("# CLAUDE\n")

        info = bm.create_backup("full")
        assert info is not None
        assert info.backup_type == "full"
        assert info.checksum is not None
        assert info.size_bytes > 0
        assert info.id > 0

        # Archive should exist on disk
        assert os.path.exists(info.file_path)

    def test_create_claude_md_backup(self):
        """create_backup('claude_md') backs up the root CLAUDE.md."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        # Put a CLAUDE.md in the project root (not in .muscle/)
        root_claude = os.path.join(tmpdir, "CLAUDE.md")
        with open(root_claude, "w") as fh:
            fh.write("# Project CLAUDE\n\nSome content.\n")

        info = bm.create_backup("claude_md")
        assert info is not None
        assert info.backup_type == "claude_md"
        assert "claude_md" in info.file_path

    def test_create_config_backup(self):
        """create_backup('config') backs up .muscle/config.yaml."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        bm._muscle_dir.joinpath("config.yaml").write_text("llm:\n  provider: m27\n")

        info = bm.create_backup("config")
        assert info is not None
        assert info.backup_type == "config"

    def test_create_memory_backup(self):
        """create_backup('memory') backs up the project_memory.db."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        info = bm.create_backup("memory")
        assert info is not None
        assert info.backup_type == "memory"

    def test_create_backup_missing_source_raises(self):
        """create_backup raises FileNotFoundError when source is missing."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        # No CLAUDE.md at root
        try:
            bm.create_backup("claude_md")
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError:
            pass  # expected

    def test_create_backup_invalid_type_raises(self):
        """create_backup raises ValueError for unknown type."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        try:
            bm.create_backup("invalid_type")  # type: ignore[arg-type]
            assert False, "Expected ValueError"
        except ValueError:
            pass  # expected

    def test_list_backups_empty(self):
        """list_backups returns empty list when no backups exist."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        assert bm.list_backups() == []

    def test_list_backups_returns_all(self):
        """list_backups returns all backups sorted by created_at desc."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        # Create content so backups have something to archive
        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")
        root_claude = os.path.join(tmpdir, "CLAUDE.md")
        with open(root_claude, "w") as fh:
            fh.write("# CLAUDE\n")

        bm.create_backup("full")
        bm.create_backup("config")
        bm.create_backup("claude_md")

        backups = bm.list_backups()
        assert len(backups) == 3
        # Verify sorted descending (most recent first)
        timestamps = [b.created_at for b in backups]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_backups_filtered_by_type(self):
        """list_backups with backup_type filter returns only matching rows."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")
        root_claude = os.path.join(tmpdir, "CLAUDE.md")
        with open(root_claude, "w") as fh:
            fh.write("# CLAUDE\n")

        bm.create_backup("full")
        bm.create_backup("config")
        bm.create_backup("claude_md")

        config_backups = bm.list_backups(backup_type="config")
        assert all(b.backup_type == "config" for b in config_backups)
        assert len(config_backups) == 1

    def test_inspect_backup(self):
        """inspect_backup returns metadata plus archive contents."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")

        created = bm.create_backup("config")
        assert created is not None

        result = bm.inspect_backup(created.id)
        assert result is not None
        assert result["id"] == created.id
        assert result["backup_type"] == "config"
        assert result["checksum"] is not None
        assert result["size_bytes"] > 0
        # Contents list may be empty or contain files depending on archive structure
        assert isinstance(result["contents"], list)

    def test_inspect_backup_not_found(self):
        """inspect_backup returns None for unknown ID."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        assert bm.inspect_backup(9999) is None

    def test_prune_preserves_fresh_backups(self):
        """prune does not remove backups newer than retention_days."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)  # retention_days=7

        # Create one backup
        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")
        backup = bm.create_backup("config")
        assert backup is not None

        # Prune with 7-day retention should not remove a fresh backup
        count = bm.prune()
        assert count == 0  # nothing old enough yet

        # Verify backup record still exists
        remaining = bm.list_backups()
        assert len(remaining) == 1

    def test_prune_removes_expired_backups(self):
        """prune removes backups older than retention_days."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)  # retention_days=7

        # Create one backup
        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")
        backup = bm.create_backup("config")
        assert backup is not None

        # Manually set retention to 0 so the fresh backup becomes "expired"
        bm._retention_days = 0
        count = bm.prune()
        # With retention=0 all backups are considered expired
        assert count == 1

        # Verify all backup records are gone
        remaining = bm.list_backups()
        assert len(remaining) == 0

    def test_prune_filtered_by_type(self):
        """prune with backup_type only removes old backups of that type."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)  # retention_days=7

        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")
        root_claude = os.path.join(tmpdir, "CLAUDE.md")
        with open(root_claude, "w") as fh:
            fh.write("# CLAUDE\n")

        b1 = bm.create_backup("full")
        b2 = bm.create_backup("config")
        assert b1 is not None
        assert b2 is not None

        # Set retention to 0 so both are eligible for pruning
        bm._retention_days = 0

        # Prune only "full" type
        count = bm.prune(backup_type="full")
        assert count == 1

        # "config" backup should remain
        remaining = bm.list_backups()
        assert len(remaining) == 1
        assert remaining[0].backup_type == "config"

    def test_restore_backup_dry_run(self):
        """restore_backup with dry_run=True returns what would be restored."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("key: value\n")

        backup = bm.create_backup("config")
        assert backup is not None

        result = bm.restore_backup(backup.id, dry_run=True)
        assert result is not None
        assert result["dry_run"] is True
        assert result["id"] == backup.id
        assert result["files"][0]["destination"].endswith(".muscle/config.yaml")

    def test_restore_config_backup_restores_into_muscle_dir(self):
        """config backups restore `.muscle/config.yaml`, not a repo-root file."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        config_path = bm._muscle_dir / "config.yaml"
        config_path.write_text("version: 1\n")

        backup = bm.create_backup("config")
        assert backup is not None

        config_path.write_text("version: 2\n")
        result = bm.restore_backup(backup.id)

        assert result is not None
        assert result["restored_count"] == 1
        assert config_path.read_text() == "version: 1\n"
        assert not os.path.exists(os.path.join(tmpdir, "config.yaml"))

    def test_restore_memory_backup_restores_project_memory_db(self):
        """memory backups restore `.muscle/project_memory.db` in place."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        backup = bm.create_backup("memory")
        assert backup is not None

        db_path = bm._muscle_dir / "project_memory.db"
        original_size = db_path.stat().st_size
        backup_row = pm.get_backup(backup.id)
        assert backup_row is not None

        db_path.write_bytes(b"not a real sqlite db")
        bm._pm.get_backup = lambda backup_id: backup_row if backup_id == backup.id else None
        result = bm.restore_backup(backup.id)

        assert result is not None
        assert result["restored_count"] == 1
        assert db_path.stat().st_size == original_size
        assert not os.path.exists(os.path.join(tmpdir, "project_memory.db"))

    def test_restore_backup_not_found(self):
        """restore_backup returns None for unknown ID."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        result = bm.restore_backup(9999, dry_run=False)
        assert result is None

    def test_backup_checksum_changes_on_content_change(self):
        """Two backups of same type get different checksums when content differs."""
        tmpdir = tempfile.mkdtemp()
        pm, bm = self._make_pm_and_bm(tmpdir)

        bm._muscle_dir.mkdir(exist_ok=True)
        bm._muscle_dir.joinpath("config.yaml").write_text("v1\n")

        b1 = bm.create_backup("config")
        assert b1 is not None

        # Change content
        bm._muscle_dir.joinpath("config.yaml").write_text("v2\n")
        time.sleep(0.1)  # ensure different timestamp
        b2 = bm.create_backup("config")
        assert b2 is not None

        assert b1.checksum != b2.checksum
