"""
Tests for memory_manager.py
"""

import re
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


class TestStructuredClaudeMd:
    """Tests for structured CLAUDE.md rules and MEMORY.md sections."""

    def test_write_do_rule(self):
        """Test writing a 'do' rule to CLAUDE.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.write_rule(
                "Use parameterized queries for SQL",
                rule_type="do",
                severity="high",
                confidence="high",
                validated_count=3,
            )

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Do" in content
            assert "Use parameterized queries for SQL" in content
            assert "(confidence: high, validated: 3x)" in content

    def test_write_dont_rule(self):
        """Test writing a 'dont' rule to CLAUDE.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.write_rule(
                "Never use string concatenation for SQL",
                rule_type="dont",
                severity="critical",
                confidence="high",
                validated_count=5,
            )

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Don't" in content
            assert "Never use string concatenation for SQL" in content
            assert "(confidence: high, validated: 5x)" in content

    def test_write_skill_reference(self):
        """Test writing a skill reference to CLAUDE.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.write_skill_ref(
                "Auth Patterns", ".muscle/skills/auth_patterns.md"
            )

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Project Skills" in content
            assert "`.muscle/skills/auth_patterns.md`" in content
            assert "Auth Patterns" in content

    def test_dedup_rules(self):
        """Test that writing the same rule twice only appears once."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use parameterized queries",
                rule_type="do",
                severity="high",
                confidence="high",
                validated_count=1,
            )
            result = manager.write_rule(
                "Use parameterized queries",
                rule_type="do",
                severity="high",
                confidence="high",
                validated_count=2,
            )

            assert result is False
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            count = content.lower().count("use parameterized queries")
            assert count == 1

    def test_read_rules(self):
        """Test reading rules back from CLAUDE.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use type hints",
                rule_type="do",
                severity="medium",
                confidence="medium",
                validated_count=2,
            )
            manager.write_rule(
                "Avoid global state",
                rule_type="dont",
                severity="high",
                confidence="high",
                validated_count=4,
            )

            rules = manager.read_rules()
            assert len(rules) == 2

            do_rules = [r for r in rules if r["type"] == "do"]
            dont_rules = [r for r in rules if r["type"] == "dont"]
            assert len(do_rules) == 1
            assert len(dont_rules) == 1

            assert do_rules[0]["text"] == "Use type hints"
            assert do_rules[0]["confidence"] == "medium"
            assert do_rules[0]["validated_count"] == 2

            assert dont_rules[0]["text"] == "Avoid global state"

    def test_update_rule_validated_count(self):
        """Test updating a rule's validation count in-place."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use type hints",
                rule_type="do",
                severity="medium",
                confidence="medium",
                validated_count=2,
            )

            result = manager.update_rule_validation(
                "Use type hints", validated_count=5, confidence="high"
            )
            assert result is True

            rules = manager.read_rules()
            assert len(rules) == 1
            assert rules[0]["validated_count"] == 5
            assert rules[0]["confidence"] == "high"

    def test_archive_rule(self):
        """Test archiving a rule moves it from CLAUDE.md to MEMORY.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use type hints",
                rule_type="do",
                severity="medium",
                confidence="medium",
                validated_count=2,
            )

            result = manager.archive_rule("Use type hints", reason="Superseded by stricter rule")
            assert result is True

            # Verify removed from CLAUDE.md
            claude_content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "Use type hints" not in claude_content

            # Verify added to MEMORY.md
            memory_content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "Use type hints" in memory_content
            assert "Archived Rules" in memory_content
            assert "Superseded by stricter rule" in memory_content

    def test_log_review_session(self):
        """Test logging a review session to MEMORY.md."""
        from tools.muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.log_review_session(
                critical=1, high=3, medium=5, low=2,
                actions=["Fixed SQL injection", "Added input validation"],
            )

            assert result is True
            memory_content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "Review Sessions" in memory_content
            assert "critical=1" in memory_content
            assert "high=3" in memory_content
            assert "Fixed SQL injection" in memory_content
