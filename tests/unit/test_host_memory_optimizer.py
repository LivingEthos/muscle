"""Tests for host_memory_optimizer.py — create/idempotent/preserve/skip-agents/only-flag."""

import tempfile
from pathlib import Path

from tools.muscle.code_review.host_memory_optimizer import (
    HostMemoryOptimizer,
    OptimizeResult,
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
