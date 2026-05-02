"""
Tests for claude_publisher.py
"""

import tempfile
from pathlib import Path


class TestClaudePublisher:
    """Tests for ClaudePublisher class."""

    def test_publisher_init(self):
        """Test ClaudePublisher initialization."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            publisher = ClaudePublisher(tmpdir)
            assert publisher.project_path == Path(tmpdir)
            assert publisher.claude_md_path == Path(tmpdir) / "CLAUDE.md"

    def test_publish_creates_backup(self):
        """Test that publish creates a backup before writing via shared BackupManager."""
        from tools.muscle.backup_manager import BackupManager
        from tools.muscle.claude_publisher import ClaudePublisher
        from tools.muscle.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n\nSome content")

            # Create shared BackupManager with ProjectMemory
            pm = ProjectMemory(tmpdir)
            bm = BackupManager(pm, tmpdir)
            publisher = ClaudePublisher(tmpdir, backup_manager=bm)

            publisher.publish(
                critical_rules=[{"text": "Use type hints", "score": 0.8, "validated_count": 3}],
            )

            # Verify backup was recorded via shared BackupManager
            backups = bm.list_backups(backup_type="claude_md")
            assert len(backups) >= 1

    def test_publish_inserts_markers(self):
        """Test that publish inserts markers when they don't exist."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n\nSome content\n")

            publisher = ClaudePublisher(tmpdir)
            result = publisher.publish(
                critical_rules=[{"text": "Use type hints", "score": 0.8, "validated_count": 3}],
                tooling_notes=["Ruff configured for linting"],
            )

            assert result is True
            content = claude_md.read_text()
            assert "<!-- MUSCLE_PUBLISHED_START -->" in content
            assert "<!-- MUSCLE_PUBLISHED_END -->" in content
            assert "Use type hints" in content

    def test_publish_updates_existing_markers(self):
        """Test that publish updates content between existing markers."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text(
                "# CLAUDE.md\n\n"
                "<!-- MUSCLE_PUBLISHED_START -->\n"
                "Old content\n"
                "<!-- MUSCLE_PUBLISHED_END -->\n\n"
                "User content here"
            )

            publisher = ClaudePublisher(tmpdir)
            result = publisher.publish(
                critical_rules=[{"text": "New rule", "score": 0.9, "validated_count": 5}],
            )

            assert result is True
            content = claude_md.read_text()
            assert "New rule" in content
            assert "Old content" not in content
            assert "User content here" in content

    def test_publish_preserves_user_content(self):
        """Test that publish preserves user content outside markers."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text(
                "# CLAUDE.md\n\n"
                "This is user content that should be preserved.\n\n"
                "<!-- MUSCLE_PUBLISHED_START -->\n"
                "Published\n"
                "<!-- MUSCLE_PUBLISHED_END -->\n\n"
                "More user content here."
            )

            publisher = ClaudePublisher(tmpdir)
            publisher.publish(
                critical_rules=[{"text": "New rule", "score": 0.9, "validated_count": 5}],
            )

            content = claude_md.read_text()
            assert "This is user content that should be preserved." in content
            assert "More user content here." in content

    def test_publish_enforces_size_cap(self):
        """Test that publish enforces max 50 lines per section."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            # Create 60 rules (should be capped at 50)
            rules = [{"text": f"Rule {i}", "score": 0.5, "validated_count": 1} for i in range(60)]

            publisher = ClaudePublisher(tmpdir)
            publisher.publish(critical_rules=rules)

            content = claude_md.read_text()
            # Count lines in critical rules section
            import re

            match = re.search(
                r"### Critical Rules\n(.*?)(?:\n###|\n<!-- MUSCLE_PUBLISHED_END)",
                content,
                re.DOTALL,
            )
            if match:
                rule_lines = [
                    line for line in match.group(1).split("\n") if line.strip().startswith("-")
                ]
                assert len(rule_lines) <= 50

    def test_publish_deduplicates_entries(self):
        """Test that duplicate entries are suppressed."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            # Publish same rule twice
            publisher = ClaudePublisher(tmpdir)

            publisher.publish(
                critical_rules=[{"text": "Same rule", "score": 0.8, "validated_count": 3}],
            )

            publisher.publish(
                critical_rules=[{"text": "Same rule", "score": 0.9, "validated_count": 4}],
            )

            content = claude_md.read_text()
            # Should still have only one instance of "Same rule"
            count = content.count("Same rule")
            assert count == 1

    def test_publish_empty_sections(self):
        """Test publishing with empty sections."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            publisher = ClaudePublisher(tmpdir)
            result = publisher.publish(
                critical_rules=[],
                tooling_notes=["Note 1"],
            )

            assert result is True
            content = claude_md.read_text()
            assert "Note 1" in content
            assert "### Critical Rules" not in content

    def test_insert_markers_if_missing(self):
        """Test inserting markers when they don't exist."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n\nSome content")

            publisher = ClaudePublisher(tmpdir)
            result = publisher.insert_markers_if_missing()

            assert result is True
            content = claude_md.read_text()
            assert "<!-- MUSCLE_PUBLISHED_START -->" in content
            assert "<!-- MUSCLE_PUBLISHED_END -->" in content

    def test_insert_markers_if_missing_already_exists(self):
        """Test that insert_markers_if_missing returns True if markers exist."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text(
                "# CLAUDE.md\n\n"
                "<!-- MUSCLE_PUBLISHED_START -->\n"
                "Content\n"
                "<!-- MUSCLE_PUBLISHED_END -->"
            )

            publisher = ClaudePublisher(tmpdir)
            result = publisher.insert_markers_if_missing()

            assert result is True

    def test_update_markers(self):
        """Test update_markers fetches rules from DB (source of truth) and publishes."""
        from tools.muscle.claude_publisher import ClaudePublisher
        from tools.muscle.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            muscle_dir = project / ".muscle"
            muscle_dir.mkdir()
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            # Insert rule into DB (source of truth), not internal markdown
            pm = ProjectMemory(tmpdir)
            pm.insert_learned_rule(
                project_path=tmpdir,
                rule_text="Use type hints everywhere",
                trigger_pattern="type_hint",
                status="active",
            )

            publisher = ClaudePublisher(tmpdir)
            result = publisher.update_markers()

            assert result is True
            content = claude_md.read_text()
            assert "Use type hints" in content

    def test_publish_without_claude_md(self):
        """Test that publish fails gracefully when CLAUDE.md doesn't exist."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            publisher = ClaudePublisher(tmpdir)
            result = publisher.publish()

            assert result is False

    def test_publish_sorts_by_score(self):
        """Test that critical rules are sorted by score (highest first)."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            publisher = ClaudePublisher(tmpdir)
            publisher.publish(
                critical_rules=[
                    {"text": "Low score rule", "score": 0.3, "validated_count": 1},
                    {"text": "High score rule", "score": 0.9, "validated_count": 5},
                    {"text": "Medium score rule", "score": 0.6, "validated_count": 2},
                ],
            )

            content = claude_md.read_text()
            high_idx = content.find("High score rule")
            medium_idx = content.find("Medium score rule")
            low_idx = content.find("Low score rule")

            assert high_idx < medium_idx < low_idx

    def test_publish_sections_order(self):
        """Test that sections appear in correct order."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            publisher = ClaudePublisher(tmpdir)
            publisher.publish(
                critical_rules=[{"text": "Rule", "score": 0.8, "validated_count": 3}],
                mistake_corrections=[{"mistake": "Bad", "correction": "Good", "count": 1}],
                agent_calls=[{"agent_name": "test", "path": "agents/test.md", "use_count": 1}],
                skill_calls=[{"skill_name": "test", "path": "skills/test.md", "use_count": 1}],
                tooling_notes=["Note"],
            )

            content = claude_md.read_text()

            # Find positions of section headers
            rules_idx = content.find("### Critical Rules")
            mistakes_idx = content.find("### Frequent Mistakes")
            agents_idx = content.find("### Active Agent Calls")
            skills_idx = content.find("### Active Skill Calls")
            tooling_idx = content.find("### Tooling Notes")

            assert rules_idx < mistakes_idx < agents_idx < skills_idx < tooling_idx


class TestMultiTargetPublish:
    """Tests for multi-target publishing (CLAUDE.md + AGENTS.md) and pinned sections."""

    def test_publish_writes_to_agents_md_when_present(self):
        """Both CLAUDE.md and AGENTS.md should receive identical published content."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            agents_md = project / "AGENTS.md"
            claude_md.write_text("# CLAUDE.md\n")
            agents_md.write_text("# AGENTS.md\n")

            publisher = ClaudePublisher(tmpdir)
            result = publisher.publish(
                critical_rules=[{"text": "Use type hints", "score": 0.8, "validated_count": 3}],
            )

            assert result is True
            claude_content = claude_md.read_text()
            agents_content = agents_md.read_text()
            assert "Use type hints" in claude_content
            assert "Use type hints" in agents_content
            # Both files should carry the pinned Methodology header.
            assert "### Methodology" in claude_content
            assert "### Methodology" in agents_content

    def test_publish_skips_agents_md_when_absent(self):
        """If AGENTS.md is absent, publish() still succeeds for CLAUDE.md only."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            agents_md = project / "AGENTS.md"
            claude_md.write_text("# CLAUDE.md\n")
            # AGENTS.md intentionally absent.

            publisher = ClaudePublisher(tmpdir)
            result = publisher.publish(
                critical_rules=[{"text": "Rule", "score": 0.8, "validated_count": 1}],
            )

            assert result is True
            assert not agents_md.exists()

    def test_pinned_sections_never_consolidated(self):
        """_m27_summarize_entries must NOT invoke the M2.7 client for pinned sections."""
        from unittest.mock import MagicMock

        from tools.muscle.claude_publisher import ClaudePublisher
        from tools.muscle.code_review.host_memory_templates import SECTION_METHODOLOGY

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_m27 = MagicMock()
            publisher = ClaudePublisher(tmpdir, m27_client=mock_m27)

            entries = [{"text": "some pinned content"}]
            result = publisher._m27_summarize_entries(entries, SECTION_METHODOLOGY)

            # Entries returned unchanged.
            assert result == entries
            # M2.7 client must not have been called.
            mock_m27.chat.assert_not_called()

    def test_publish_idempotent(self):
        """Publishing twice with identical inputs yields byte-identical output."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            claude_md = project / "CLAUDE.md"
            claude_md.write_text("# CLAUDE.md\n")

            publisher = ClaudePublisher(tmpdir)
            rules = [{"text": "Stable rule", "score": 0.8, "validated_count": 3}]

            publisher.publish(critical_rules=rules)
            first = claude_md.read_text()

            publisher.publish(critical_rules=rules)
            second = claude_md.read_text()

            assert first == second
            # Pinned section appears exactly once, not duplicated.
            assert first.count("### Methodology") == 1

    def test_render_preview_compacts_host_memory_lines(self):
        """Preview rendering should compact verbose dynamic host-memory prose."""
        from tools.muscle.claude_publisher import ClaudePublisher

        with tempfile.TemporaryDirectory() as tmpdir:
            publisher = ClaudePublisher(tmpdir)
            baseline = publisher.render_preview(
                critical_rules=[
                    {
                        "text": (
                            "Please investigate this thoroughly and provide your findings and "
                            "proposed solutions."
                        ),
                        "score": 0.8,
                        "validated_count": 2,
                    }
                ],
                compact_host_memory=False,
            )
            compacted = publisher.render_preview(
                critical_rules=[
                    {
                        "text": (
                            "Please investigate this thoroughly and provide your findings and "
                            "proposed solutions."
                        ),
                        "score": 0.8,
                        "validated_count": 2,
                    }
                ],
                compact_host_memory=True,
            )

            assert len(compacted) < len(baseline)
            assert "Investigate thoroughly and propose validated fixes." in compacted
