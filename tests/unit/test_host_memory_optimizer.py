"""Tests for host_memory_optimizer.py — create/idempotent/preserve/skip-agents/only-flag."""

import tempfile
from pathlib import Path

from tools.muscle.code_review.host_memory_optimizer import (
    HostMemoryOptimizer,
    run_optimizer,
)


class TestHostMemoryOptimizer:
    def test_creates_file_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            opt = HostMemoryOptimizer(tmpdir)
            result = opt.plan("CLAUDE.md")
            assert result.changed is True
            assert "### Methodology" in result.diff

    def test_apply_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Need project_memory.db for BackupManager.
            from tools.muscle.project_memory import ProjectMemory

            pm = ProjectMemory(tmpdir)
            pm._init_db()

            opt = HostMemoryOptimizer(tmpdir)
            result = opt.apply("CLAUDE.md")
            assert result.changed is True
            target = Path(tmpdir) / "CLAUDE.md"
            assert target.exists()
            content = target.read_text()
            assert "### Methodology" in content
            assert "### Delegation Protocol" in content

    def test_idempotent_on_optimal_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from tools.muscle.project_memory import ProjectMemory

            pm = ProjectMemory(tmpdir)
            pm._init_db()

            opt = HostMemoryOptimizer(tmpdir)
            opt.apply("CLAUDE.md")
            # Second apply should report no change.
            result = opt.apply("CLAUDE.md")
            assert result.changed is False

    def test_preserves_user_content_outside_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from tools.muscle.project_memory import ProjectMemory

            pm = ProjectMemory(tmpdir)
            pm._init_db()

            user_before = "# My Project\n\nThis is user content.\n"
            user_after = "\n## Extra\n\nMore user content.\n"

            target = Path(tmpdir) / "CLAUDE.md"
            # Create file without markers.
            target.write_text(user_before + user_after)

            opt = HostMemoryOptimizer(tmpdir)
            opt.apply("CLAUDE.md")

            result = target.read_text()
            assert "This is user content." in result
            assert "More user content." in result
            # Markers should now be present.
            assert "<!-- MUSCLE_PUBLISHED_START -->" in result

    def test_preserves_existing_dynamic_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from tools.muscle.project_memory import ProjectMemory

            pm = ProjectMemory(tmpdir)
            pm._init_db()

            content = (
                "# CLAUDE.md\n"
                "<!-- MUSCLE_PUBLISHED_START -->\n"
                "### Critical Rules\n"
                "- Use type hints\n"
                "<!-- MUSCLE_PUBLISHED_END -->\n"
            )
            target = Path(tmpdir) / "CLAUDE.md"
            target.write_text(content)

            opt = HostMemoryOptimizer(tmpdir)
            result = opt.apply("CLAUDE.md")
            assert result.changed is True

            updated = target.read_text()
            # Pinned section added.
            assert "### Methodology" in updated
            # Existing dynamic section preserved.
            assert "- Use type hints" in updated

    def test_skip_agents_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = run_optimizer(tmpdir, skip_agents=True, dry_run=True)
            assert len(results) == 1
            assert results[0].filename == "CLAUDE.md"

    def test_only_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = run_optimizer(tmpdir, only="AGENTS.md", dry_run=True)
            assert len(results) == 1
            assert results[0].filename == "AGENTS.md"

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = run_optimizer(tmpdir, dry_run=True)
            assert len(results) == 2
            # No files should have been created.
            assert not (Path(tmpdir) / "CLAUDE.md").exists()
            assert not (Path(tmpdir) / "AGENTS.md").exists()


class TestHostMemoryOptimizerTwoPhasePublish:
    """Two-phase transactional publish: stage -> atomic swap -> commit."""

    def test_apply_stages_swaps_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            from tools.muscle.project_memory import ProjectMemory

            pm = ProjectMemory(tmpdir)
            pm._init_db()

            opt = HostMemoryOptimizer(tmpdir)
            result = opt.apply("CLAUDE.md")
            assert result.changed is True

            target = Path(tmpdir) / "CLAUDE.md"
            assert target.exists()
            assert "### Methodology" in target.read_text()

            # No pending revisions remain; exactly one committed revision.
            pending = pm.list_pending_published_revisions(tmpdir)
            assert pending == []

            revisions = _all_revisions(tmpdir)
            committed = [r for r in revisions if r["status"] == "committed"]
            assert len(committed) == 1
            assert committed[0]["target_path"] == str(target)
            # Committed content sha matches what landed on disk.
            assert committed[0]["content_sha256"] == pm.published_content_sha256(target.read_text())

    def test_apply_holds_host_doc_lock_around_rmw(self) -> None:
        """apply() serializes its read-modify-write on the shared host-doc sentinel."""
        from contextlib import contextmanager
        from unittest.mock import patch

        from tools.muscle.claude_publisher import host_doc_lock_sentinel

        with tempfile.TemporaryDirectory() as tmpdir:
            from tools.muscle.project_memory import ProjectMemory

            pm = ProjectMemory(tmpdir)
            pm._init_db()

            opt = HostMemoryOptimizer(tmpdir)
            target = Path(tmpdir) / "CLAUDE.md"
            locked_paths: list[Path] = []

            @contextmanager
            def spy_lock(path):
                locked_paths.append(Path(path))
                yield

            with patch(
                "tools.muscle.code_review.host_memory_optimizer.advisory_file_lock",
                spy_lock,
            ):
                result = opt.apply("CLAUDE.md")

            assert result.changed is True
            # Same sentinel ClaudePublisher uses, so the two writers serialize.
            assert locked_paths == [host_doc_lock_sentinel(Path(tmpdir), target)]

    def test_commit_mark_failure_left_pending_then_reconciled(self) -> None:
        """If the commit-mark is lost (crash between swap and commit), a later
        reconcile detects the on-disk content matches the staged content and
        promotes the pending row to committed."""
        from unittest.mock import patch

        from tools.muscle.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            pm = ProjectMemory(tmpdir)
            pm._init_db()

            opt = HostMemoryOptimizer(tmpdir)

            # Simulate a crash right after the atomic swap: commit-mark never runs.
            with patch.object(
                opt._pm,
                "commit_published_revision",
                side_effect=RuntimeError("simulated crash before commit-mark"),
            ):
                try:
                    opt.apply("CLAUDE.md")
                except RuntimeError:
                    pass

            target = Path(tmpdir) / "CLAUDE.md"
            # The atomic swap completed: file is on disk with pinned content.
            assert target.exists()
            assert "### Methodology" in target.read_text()

            # A pending row remains because the commit-mark failed.
            pending = pm.list_pending_published_revisions(tmpdir)
            assert len(pending) == 1

            # A subsequent init reconciles it: on-disk matches staged -> committed.
            HostMemoryOptimizer(tmpdir)
            assert pm.list_pending_published_revisions(tmpdir) == []
            revisions = _all_revisions(tmpdir)
            committed = [r for r in revisions if r["status"] == "committed"]
            assert len(committed) == 1

    def test_write_failure_leaves_file_untouched_and_aborts_revision(self) -> None:
        """If the atomic swap raises, the file is untouched and the staged
        revision is aborted (never left as a false 'pending success')."""
        from unittest.mock import patch

        from tools.muscle.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            pm = ProjectMemory(tmpdir)
            pm._init_db()

            # Pre-existing file with user content + a dynamic section to verify
            # it is byte-preserved on write failure.
            target = Path(tmpdir) / "CLAUDE.md"
            original = (
                "# CLAUDE.md\n"
                "<!-- MUSCLE_PUBLISHED_START -->\n"
                "### Critical Rules\n"
                "- Use type hints\n"
                "<!-- MUSCLE_PUBLISHED_END -->\n"
            )
            target.write_text(original)

            opt = HostMemoryOptimizer(tmpdir)

            with patch(
                "tools.muscle.code_review.host_memory_optimizer.atomic_write_text",
                side_effect=OSError("simulated disk failure"),
            ):
                try:
                    opt.apply("CLAUDE.md")
                except OSError:
                    pass

            # File untouched.
            assert target.read_text() == original

            # No pending row survives (revision aborted in the except block).
            assert pm.list_pending_published_revisions(tmpdir) == []
            revisions = _all_revisions(tmpdir)
            aborted = [r for r in revisions if r["status"] == "aborted"]
            assert len(aborted) == 1


def _all_revisions(project_path: str) -> list[dict]:
    """Read every published_revisions row regardless of status."""
    from tools.muscle.project_memory import ProjectMemory

    pm = ProjectMemory(project_path)
    conn = pm._get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM published_revisions WHERE project_path = ? ORDER BY id ASC",
            (project_path,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
