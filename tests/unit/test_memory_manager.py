"""
Tests for memory_manager.py
"""

import tempfile
from pathlib import Path


class TestMemoryManager:
    """Tests for MemoryManager class."""

    def test_memory_manager_init(self):
        """Test MemoryManager initialization."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            assert manager.project_path == Path(tmpdir)
            assert manager.muscle_dir.exists()

    def test_update_memory_md_creates_file(self):
        """Test that update_memory_md creates file if not exists."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.update_memory_md("Test entry", "test")

            assert result is True
            assert (manager.muscle_dir / "MEMORY.md").exists()

    def test_update_claude_md(self):
        """Test updating CLAUDE.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.update_claude_md("Test claude entry", "test")

            assert result is True
            assert (manager.muscle_dir / "CLAUDE.md").exists()

    def test_update_agent_md(self):
        """Test updating AGENT.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.update_agent_md("Test agent entry", "agent")

            assert result is True
            assert (manager.muscle_dir / "AGENT.md").exists()

    def test_duplicate_entry_skipped(self):
        """Test that duplicate entries are skipped."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.update_memory_md("Same entry", "test")
            result = manager.update_memory_md("Same entry", "test")

            assert result is False

    def test_add_skill_reference(self):
        """Test adding skill reference."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_skill_reference("auth-patterns", ".muscle/skills/auth_patterns.md")

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "auth-patterns" in content
            assert ".muscle/skills/" in content

    def test_add_agent_reference(self):
        """Test adding agent reference."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_agent_reference(
                "security-auditor", ".muscle/agents/security_auditor.md"
            )

            assert result is True
            content = (manager.muscle_dir / "AGENT.md").read_text()
            assert "security-auditor" in content

    def test_add_pattern_learned(self):
        """Test recording learned pattern."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_pattern_learned("sql_injection", "src/db.py", "HIGH")

            assert result is True
            content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "sql_injection" in content
            assert "src/db.py" in content
            assert "HIGH" in content

    def test_add_fix_validated(self):
        """Test recording validated fix."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_fix_validated("sql_injection", "Used parameterized queries", True)

            assert result is True
            content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "sql_injection" in content
            assert "SUCCESS" in content

    def test_prune_old_entries(self):
        """Test pruning old entries."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.update_memory_md("Entry 1", "test")

            result = manager.prune_old_entries("MEMORY.md", max_entries=100)
            assert result == 0

    def test_marker_based_editing(self):
        """Test that edits are bounded by markers."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)

            claude_file = manager.muscle_dir / "CLAUDE.md"
            claude_file.write_text("""# CLAUDE.md

<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE_LEARNED_END -->

User content here
""")

            manager.update_claude_md("New learned entry", "test")
            content = claude_file.read_text()

            assert "<!-- MUSCLE_LEARNED_START -->" in content
            assert "<!-- MUSCLE_LEARNED_END -->" in content
            assert "User content here" in content
            assert "New learned entry" in content
