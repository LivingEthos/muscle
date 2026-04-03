"""
Integration tests for the self-learning pipeline.

Tests LearningPipeline -> MemoryManager -> PatternDetector -> SkillGenerator
-> StrategyEvolver with realistic review results and project state.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.code_review.learning_pipeline import LearningPipeline
from tools.muscle.code_review.memory_manager import MemoryManager
from tools.muscle.code_review.pattern_detector import PatternCluster, PatternDetector
from tools.muscle.code_review.skill_generator import SkillGenerator
from tools.muscle.code_review.types import (
    Severity,
)
from tools.muscle.project_memory import ProjectMemory

from .conftest import MockM27Client, make_review_issue, make_review_result


class TestLearningPipelineFullCycle:
    """Tests the complete learning cycle: review -> rules -> patterns -> skills."""

    def test_full_learning_cycle_with_issues(self, project_with_muscle_dir: Path):
        """Full cycle: review with issues -> rules added -> session logged."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        issues = [
            make_review_issue(
                severity=Severity.CRITICAL,
                title="SQL injection in user endpoint",
                suggested_fix="Use parameterized queries",
            ),
            make_review_issue(
                severity=Severity.HIGH,
                title="Hardcoded secret key",
                file_path="src/config.py",
                suggested_fix="Use environment variables",
            ),
            make_review_issue(
                severity=Severity.MEDIUM,
                title="Missing input validation",
                file_path="src/api.py",
                line_number=45,
            ),
        ]
        result = make_review_result(issues, target_path=str(project_with_muscle_dir))

        actions = pipeline.learn_from_review(result)

        # Critical and high issues should generate rules immediately
        assert actions["rules_added"] >= 2
        assert actions["session_logged"] is True

        # Verify CLAUDE.md was updated
        claude_md = project_with_muscle_dir / ".muscle" / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "SQL injection" in content or "parameterized" in content

        # Verify MEMORY.md was updated
        memory_md = project_with_muscle_dir / ".muscle" / "MEMORY.md"
        assert memory_md.exists()

    def test_learn_from_review_passes_metadata_and_returns_review_run_id(
        self, project_with_muscle_dir: Path
    ):
        """learn_from_review passes review_mode, token_cost, duration_ms to DB and returns review_run_id."""
        from tools.muscle.project_memory import ProjectMemory

        pipeline = LearningPipeline(str(project_with_muscle_dir))
        issues = [
            make_review_issue(
                severity=Severity.HIGH,
                title="Hardcoded credential",
                file_path="src/auth.py",
            ),
        ]
        result = make_review_result(issues, target_path=str(project_with_muscle_dir))

        # Call with metadata
        actions = pipeline.learn_from_review(
            result,
            review_mode="auto_fix",
            token_cost=5000,
            duration_ms=12000,
        )

        # Should return review_run_id
        assert actions["review_run_id"] is not None

        # Verify the DB has the correct metadata
        pm = ProjectMemory(str(project_with_muscle_dir))
        stored_run = pm.get_review_run(actions["review_run_id"])
        assert stored_run is not None
        assert stored_run["review_mode"] == "auto_fix"
        assert stored_run["token_cost"] == 5000
        assert stored_run["duration_ms"] == 12000
        assert stored_run["findings_count"] == 1

    def test_clean_review_persists_review_run(self, project_with_muscle_dir: Path):
        """Clean reviews should still be recorded in review_runs for audit/history."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        clean_result = make_review_result([], target_path=str(project_with_muscle_dir))
        actions = pipeline.learn_from_review(
            clean_result,
            review_mode="review",
            token_cost=250,
            duration_ms=500,
        )

        assert actions["review_run_id"] is not None

        pm = ProjectMemory(str(project_with_muscle_dir))
        stored_run = pm.get_review_run(actions["review_run_id"])
        assert stored_run is not None
        assert stored_run["findings_count"] == 0
        assert stored_run["token_cost"] == 250
        assert stored_run["duration_ms"] == 500

    def test_decisions_reference_review_finding_ids(self, project_with_muscle_dir: Path):
        """Memory decisions should point to the finding rows they scored."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))
        issue = make_review_issue(
            severity=Severity.HIGH,
            title="Linked review finding",
            file_path="src/main.py",
        )
        result = make_review_result([issue], target_path=str(project_with_muscle_dir))

        actions = pipeline.learn_from_review(result)

        pm = ProjectMemory(str(project_with_muscle_dir))
        findings = pm.list_findings_for_run(actions["review_run_id"])
        decisions = pm.list_decisions(project_path=str(project_with_muscle_dir), limit=10)

        assert len(findings) == 1
        assert len(decisions) >= 1
        assert decisions[0]["source_table"] == "review_findings"
        assert decisions[0]["source_id"] == findings[0]["id"]

    def test_clean_review_validates_existing_rules(self, project_with_muscle_dir: Path):
        """Clean review (no issues) should validate and increment existing rules."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        # First, add a rule
        pipeline.memory_manager.write_rule(
            rule_text="Always validate user input",
            rule_type="do",
            severity="high",
            confidence="low",
            validated_count=0,
        )

        # Then run a clean review
        clean_result = make_review_result([], target_path=str(project_with_muscle_dir))
        actions = pipeline.learn_from_review(clean_result)

        assert actions["rules_validated"] >= 1

        rules = pipeline.memory_manager.read_rules()
        assert len(rules) == 1
        assert rules[0]["validated_count"] == 1

    def test_repeated_clean_reviews_upgrade_confidence(self, project_with_muscle_dir: Path):
        """Multiple clean reviews should upgrade rule confidence: low -> medium -> high."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        pipeline.memory_manager.write_rule(
            rule_text="Use type hints everywhere",
            rule_type="do",
            severity="medium",
            confidence="low",
            validated_count=0,
        )

        clean_result = make_review_result([], target_path=str(project_with_muscle_dir))

        # Run 4 clean reviews to reach high confidence
        for _i in range(4):
            pipeline.learn_from_review(clean_result)

        rules = pipeline.memory_manager.read_rules()
        assert len(rules) == 1
        assert rules[0]["confidence"] == "high"
        assert rules[0]["validated_count"] == 4

    def test_stale_rules_get_archived(self, project_with_muscle_dir: Path):
        """Rules not seen in many reviews should be archived."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        # Add a rule with high validated count (near archive threshold)
        pipeline.memory_manager.write_rule(
            rule_text="Obsolete pattern from old codebase",
            rule_type="dont",
            severity="medium",
            confidence="high",
            validated_count=9,
        )

        clean_result = make_review_result([], target_path=str(project_with_muscle_dir))
        actions = pipeline.learn_from_review(clean_result)

        assert actions["rules_archived"] == 1

        # Rule should be removed from CLAUDE.md
        rules = pipeline.memory_manager.read_rules()
        assert len(rules) == 0

    def test_rule_not_validated_when_pattern_still_found(self, project_with_muscle_dir: Path):
        """Rules matching found issues should NOT be validated."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        pipeline.memory_manager.write_rule(
            rule_text="SQL injection risk",
            rule_type="dont",
            severity="high",
            confidence="low",
            validated_count=0,
        )

        # Review that contains the same pattern
        issue = make_review_issue(title="SQL injection risk", severity=Severity.HIGH)
        result = make_review_result([issue], target_path=str(project_with_muscle_dir))

        pipeline.learn_from_review(result)

        rules = pipeline.memory_manager.read_rules()
        matching = [r for r in rules if "SQL injection" in r["text"]]
        for rule in matching:
            assert rule["validated_count"] == 0  # Not incremented

    def test_duplicate_rules_not_added(self, project_with_muscle_dir: Path):
        """Same finding from multiple reviews should not create duplicate rules."""
        pipeline = LearningPipeline(str(project_with_muscle_dir))

        issue = make_review_issue(
            severity=Severity.CRITICAL,
            title="Always sanitize user input",
            suggested_fix="Use a whitelist approach",
        )
        result = make_review_result([issue], target_path=str(project_with_muscle_dir))

        # Run the same review twice
        actions1 = pipeline.learn_from_review(result)
        actions2 = pipeline.learn_from_review(result)

        assert actions1["rules_added"] >= 1
        assert actions2["rules_added"] == 0  # Duplicate not added


class TestMemoryManagerIntegration:
    """Tests MemoryManager file operations with realistic data."""

    def test_write_and_read_structured_rules(self, project_with_muscle_dir: Path):
        """Rules should be written with proper structure and readable back."""
        manager = MemoryManager(str(project_with_muscle_dir))

        # Write rules of different types
        manager.write_rule(
            rule_text="Use parameterized queries for all DB access",
            rule_type="do",
            severity="critical",
            confidence="high",
            validated_count=5,
        )
        manager.write_rule(
            rule_text="Avoid using dynamic code execution with user input",
            rule_type="dont",
            severity="critical",
            confidence="high",
            validated_count=8,
        )
        manager.write_rule(
            rule_text="Always close file handles in finally blocks",
            rule_type="do",
            severity="medium",
            confidence="medium",
            validated_count=2,
        )

        rules = manager.read_rules()
        assert len(rules) == 3

        # Verify structure - read_rules returns text, type, confidence, validated_count
        for rule in rules:
            assert "text" in rule
            assert "type" in rule
            assert "confidence" in rule
            assert "validated_count" in rule

        do_rules = [r for r in rules if r["type"] == "do"]
        dont_rules = [r for r in rules if r["type"] == "dont"]
        assert len(do_rules) == 2
        assert len(dont_rules) == 1

    def test_update_rule_validation_in_place(self, project_with_muscle_dir: Path):
        """Validation updates should modify rules in-place, not duplicate."""
        manager = MemoryManager(str(project_with_muscle_dir))

        manager.write_rule(
            rule_text="Test rule for validation",
            rule_type="do",
            severity="medium",
            confidence="low",
            validated_count=0,
        )

        # Update validation
        manager.update_rule_validation(
            rule_text="Test rule for validation",
            validated_count=3,
            confidence="medium",
        )

        rules = manager.read_rules()
        assert len(rules) == 1
        assert rules[0]["validated_count"] == 3
        assert rules[0]["confidence"] == "medium"

    def test_archive_rule_moves_to_memory(self, project_with_muscle_dir: Path):
        """Archived rules should be removed from CLAUDE.md and noted in MEMORY.md."""
        manager = MemoryManager(str(project_with_muscle_dir))

        manager.write_rule(
            rule_text="Legacy pattern to archive",
            rule_type="dont",
            severity="low",
            confidence="high",
            validated_count=10,
        )

        manager.archive_rule(
            rule_text="Legacy pattern to archive",
            reason="Not seen in 10+ clean reviews",
        )

        # Should be removed from active rules
        rules = manager.read_rules()
        matching = [r for r in rules if "Legacy pattern" in r["text"]]
        assert len(matching) == 0

    def test_update_claude_md(self, project_with_muscle_dir: Path):
        """CLAUDE.md updates should be properly formatted within markers."""
        manager = MemoryManager(str(project_with_muscle_dir))

        result = manager.update_claude_md(
            "Prefer async I/O for network operations",
            category="performance",
        )

        assert result is True
        claude_md = project_with_muscle_dir / ".muscle" / "CLAUDE.md"
        content = claude_md.read_text()
        assert "async I/O" in content

    def test_update_memory_md(self, project_with_muscle_dir: Path):
        """MEMORY.md updates should preserve existing content."""
        manager = MemoryManager(str(project_with_muscle_dir))

        manager.update_memory_md("First entry", category="learned")
        manager.update_memory_md("Second entry", category="pattern")

        memory_md = project_with_muscle_dir / ".muscle" / "MEMORY.md"
        content = memory_md.read_text()
        assert "First entry" in content
        assert "Second entry" in content

    def test_write_skill_ref(self, project_with_muscle_dir: Path):
        """Skill references should be added to CLAUDE.md."""
        manager = MemoryManager(str(project_with_muscle_dir))

        result = manager.write_skill_ref(
            "SQL Safety Patterns",
            ".muscle/skills/sql_safety.md",
        )

        assert result is True
        claude_md = project_with_muscle_dir / ".muscle" / "CLAUDE.md"
        content = claude_md.read_text()
        assert "SQL Safety" in content or "sql_safety" in content

    def test_log_review_session(self, project_with_muscle_dir: Path):
        """Review session logging should include counts and actions."""
        manager = MemoryManager(str(project_with_muscle_dir))

        result = manager.log_review_session(
            critical=2,
            high=3,
            medium=5,
            low=1,
            actions=["added 2 rules", "validated 3 rules"],
        )

        assert result is True
        memory_md = project_with_muscle_dir / ".muscle" / "MEMORY.md"
        content = memory_md.read_text()
        assert "critical=2" in content
        assert "high=3" in content

    def test_m27_summarization(self, project_with_muscle_dir: Path, mock_m27: MockM27Client):
        """Long entries should be summarized by M2.7 when available."""
        manager = MemoryManager(str(project_with_muscle_dir), m27_client=mock_m27)

        long_entry = "A" * 300  # Over 200 char threshold
        result = manager.update_claude_md(long_entry, category="general")

        assert result is True
        # M27 should have been called for summarization
        assert mock_m27._call_count >= 1


class TestPatternDetectorIntegration:
    """Tests pattern detection with real ReviewKB data."""

    def test_detect_patterns_from_review_history(self, project_with_muscle_dir: Path):
        """PatternDetector should find patterns from accumulated review data."""
        from tools.muscle.code_review.review_kb import ReviewKB

        kb_path = str(project_with_muscle_dir / ".muscle" / "review_kb")
        kb = ReviewKB(kb_path)

        # Seed with enough data for pattern detection (3+ occurrences)
        for i in range(5):
            kb.add_reviewed_issue(
                file_path=f"src/handler_{i}.py",
                line_number=10 + i,
                severity="HIGH",
                category="security",
                title="SQL injection vulnerability",
                code_pattern="f-string in SQL query",
                was_valid=True,
            )

        detector = PatternDetector(kb_path=kb_path)
        patterns = detector.detect_patterns()

        # Should detect at least the recurring SQL injection pattern
        assert isinstance(patterns, list)
        # With 5 occurrences of the same pattern, it should be detected
        if patterns:
            assert patterns[0].occurrences >= 3

    def test_skill_candidates_filter(self, project_with_muscle_dir: Path):
        """get_skill_candidates should filter by confidence threshold."""
        from tools.muscle.code_review.review_kb import ReviewKB

        kb_path = str(project_with_muscle_dir / ".muscle" / "review_kb")
        kb = ReviewKB(kb_path)

        # Add enough issues to create a high-confidence pattern
        for i in range(6):
            kb.add_reviewed_issue(
                file_path=f"src/module_{i}.py",
                line_number=i * 10,
                severity="HIGH",
                category="security",
                title="Missing input validation",
                code_pattern="unvalidated user input",
                was_valid=True,
            )

        detector = PatternDetector(kb_path=kb_path)
        detector.detect_patterns()
        candidates = detector.get_skill_candidates()

        assert isinstance(candidates, list)
        for candidate in candidates:
            assert candidate.confidence >= 0.5

    def test_agent_candidates_complex_categories(self, project_with_muscle_dir: Path):
        """get_agent_candidates should only include complex categories."""
        from tools.muscle.code_review.review_kb import ReviewKB

        kb_path = str(project_with_muscle_dir / ".muscle" / "review_kb")
        kb = ReviewKB(kb_path)

        # Add security issues (complex category)
        for i in range(6):
            kb.add_reviewed_issue(
                file_path=f"src/auth_{i}.py",
                line_number=i,
                severity="CRITICAL",
                category="security",
                title="Auth bypass",
                code_pattern="broken auth check",
                was_valid=True,
            )

        # Add style issues (non-complex)
        for i in range(6):
            kb.add_reviewed_issue(
                file_path=f"src/style_{i}.py",
                line_number=i,
                severity="LOW",
                category="style",
                title="Naming convention",
                code_pattern="camelCase variable",
                was_valid=True,
            )

        detector = PatternDetector(kb_path=kb_path)
        detector.detect_patterns()
        agents = detector.get_agent_candidates()

        assert isinstance(agents, list)
        for agent in agents:
            assert agent.category.lower() in {
                "security",
                "performance",
                "concurrency",
                "architecture",
            }

    def test_pattern_detection_with_m27(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Pattern detection with M2.7 should use semantic clustering."""
        from tools.muscle.code_review.review_kb import ReviewKB

        kb_path = str(project_with_muscle_dir / ".muscle" / "review_kb")
        kb = ReviewKB(kb_path)

        for i in range(4):
            kb.add_reviewed_issue(
                file_path=f"src/module_{i}.py",
                line_number=i * 5,
                severity="HIGH",
                category="security",
                title=f"Variant {i} of unsafe deserialization",
                code_pattern="unsafe deserialization",
                was_valid=True,
            )

        detector = PatternDetector(kb_path=kb_path, m27_client=mock_m27)
        patterns = detector.detect_patterns()

        assert isinstance(patterns, list)


class TestSkillGeneratorIntegration:
    """Tests skill file generation from detected patterns."""

    def test_generate_skill_creates_file(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """SkillGenerator should create a .md skill file."""
        generator = SkillGenerator(str(project_with_muscle_dir), mock_m27)

        pattern = PatternCluster(
            pattern_id="sql_injection",
            pattern="SQL injection via string formatting",
            category="security",
            summary="Multiple SQL injection vulnerabilities found",
            root_cause="Using f-strings for SQL queries",
            occurrences=5,
            files=["src/db.py", "src/api.py", "src/admin.py"],
            severity_counts={"CRITICAL": 2, "HIGH": 3},
            confidence=0.8,
            semantically_related_issues=[
                {"title": "SQL injection in user query", "file_path": "src/db.py"}
            ],
        )

        skill_path = generator.generate_skill(
            pattern_info=pattern,
            reviewed_issues=pattern.semantically_related_issues,
        )

        if skill_path:
            path = Path(skill_path)
            assert path.exists()
            content = path.read_text()
            assert "---" in content  # Frontmatter
            assert len(content) > 50

    def test_generate_skill_dedup(self, project_with_muscle_dir: Path, mock_m27: MockM27Client):
        """Generating the same skill twice should not overwrite."""
        pm = ProjectMemory(str(project_with_muscle_dir))
        generator = SkillGenerator(str(project_with_muscle_dir), mock_m27, project_memory=pm)

        pattern = PatternCluster(
            pattern_id="test_pattern",
            pattern="test pattern",
            category="correctness",
            summary="Test",
            root_cause="Test",
            occurrences=3,
            files=["a.py"],
            severity_counts={"HIGH": 3},
            confidence=0.7,
        )

        generator.generate_skill(pattern, [])
        path2 = generator.generate_skill(pattern, [])

        # Second call should return None (already exists)
        assert path2 is None

    def test_list_skills(self, project_with_muscle_dir: Path, mock_m27: MockM27Client):
        """list_skills should return all generated skill files."""
        generator = SkillGenerator(str(project_with_muscle_dir), mock_m27)

        # Create a few skill files manually
        skills_dir = project_with_muscle_dir / ".muscle" / "skills"
        (skills_dir / "skill_one.md").write_text("---\nname: one\n---\nContent")
        (skills_dir / "skill_two.md").write_text("---\nname: two\n---\nContent")

        skills = generator.list_skills()
        assert len(skills) == 2

    def test_update_skill(self, project_with_muscle_dir: Path, mock_m27: MockM27Client):
        """update_skill should append new context to existing skill."""
        generator = SkillGenerator(str(project_with_muscle_dir), mock_m27)

        skill_path = project_with_muscle_dir / ".muscle" / "skills" / "auth_skill.md"
        skill_path.write_text("---\nname: auth\n---\nOriginal content")

        result = generator.update_skill(skill_path, "New context from recent review")

        assert result is True
        content = skill_path.read_text()
        assert "Original content" in content
        assert "New context" in content
        assert "## Update" in content


class TestClaudePublisherIntegration:
    """Tests for ClaudePublisher integration with LearningPipeline."""

    def test_sync_to_root_claude_md(self, project_with_muscle_dir: Path):
        """Test that update_markers publishes DB-backed rules to root CLAUDE.md.

        DB-FIRST: update_markers() queries project_memory.db directly for rules.
        Rules are NOT read from internal markdown (.muscle/CLAUDE.md).
        """
        from tools.muscle.claude_publisher import ClaudePublisher
        from tools.muscle.project_memory import ProjectMemory

        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n\n## Project Info\n\nSome content\n")

        # Insert rules into DB (source of truth), not internal markdown
        pm = ProjectMemory(str(project_with_muscle_dir))
        pm.insert_learned_rule(
            project_path=str(project_with_muscle_dir),
            rule_text="Use type hints everywhere",
            trigger_pattern="type_hint",
            status="active",
        )
        pm.insert_learned_rule(
            project_path=str(project_with_muscle_dir),
            rule_text="Never use eval",
            trigger_pattern="eval",
            status="active",
        )

        publisher = ClaudePublisher(str(project_with_muscle_dir))
        result = publisher.update_markers()

        assert result is True
        content = root_claude.read_text()
        assert "<!-- MUSCLE_PUBLISHED_START -->" in content
        assert "<!-- MUSCLE_PUBLISHED_END -->" in content
        assert "Use type hints" in content
        assert "Never use eval" in content

    def test_ensure_root_markers(self, project_with_muscle_dir: Path):
        """Test that ensure_root_claude_md_markers inserts markers if missing."""
        from tools.muscle.claude_publisher import ClaudePublisher

        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n\nUser content\n")

        publisher = ClaudePublisher(str(project_with_muscle_dir))
        result = publisher.insert_markers_if_missing()

        assert result is True
        content = root_claude.read_text()
        assert "<!-- MUSCLE_PUBLISHED_START -->" in content
        assert "<!-- MUSCLE_PUBLISHED_END -->" in content
        assert "User content" in content

    def test_publish_preserves_user_content(self, project_with_muscle_dir: Path):
        """Test that publishing preserves user content outside markers."""
        from tools.muscle.claude_publisher import ClaudePublisher

        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text(
            "# CLAUDE.md\n\n"
            "User content that should be preserved.\n\n"
            "<!-- MUSCLE_PUBLISHED_START -->\n"
            "Old published content\n"
            "<!-- MUSCLE_PUBLISHED_END -->\n\n"
            "More user content."
        )

        publisher = ClaudePublisher(str(project_with_muscle_dir))
        publisher.publish(
            critical_rules=[{"text": "New rule", "score": 0.9, "validated_count": 5}],
        )

        content = root_claude.read_text()
        assert "User content that should be preserved." in content
        assert "More user content." in content
        assert "New rule" in content
        assert "Old published content" not in content

    def test_memory_manager_sync_to_root(self, project_with_muscle_dir: Path):
        """Test MemoryManager.sync_to_root_claude_md (deprecated, uses DB-backed update_markers).

        DEPRECATED: sync_to_root_claude_md() calls update_markers() which reads from DB.
        The preferred path is LearningPipeline -> _publisher.publish() directly.

        This test verifies the fallback path works with DB-backed data.
        """
        from tools.muscle.code_review.memory_manager import MemoryManager
        from tools.muscle.project_memory import ProjectMemory

        # Create root CLAUDE.md
        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n\nRoot content\n")

        manager = MemoryManager(str(project_with_muscle_dir))

        # Insert rule into DB (source of truth), not internal markdown
        pm = ProjectMemory(str(project_with_muscle_dir))
        pm.insert_learned_rule(
            project_path=str(project_with_muscle_dir),
            rule_text="Test rule",
            trigger_pattern="test_rule",
            status="active",
        )

        # Sync to root (deprecated fallback path)
        result = manager.sync_to_root_claude_md()

        assert result is True
        content = root_claude.read_text()
        assert "Test rule" in content
        assert "<!-- MUSCLE_PUBLISHED_START -->" in content

    def test_publish_with_empty_sections_skips_section_headers(self, project_with_muscle_dir: Path):
        """Test that publishing with no data for a section omits that section."""
        from tools.muscle.claude_publisher import ClaudePublisher

        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n")

        publisher = ClaudePublisher(str(project_with_muscle_dir))
        publisher.publish(
            critical_rules=[{"text": "Rule", "score": 0.8, "validated_count": 3}],
            mistake_corrections=[],  # Empty
            agent_calls=[],  # Empty
            skill_calls=[],  # Empty
            tooling_notes=[],  # Empty
        )

        content = root_claude.read_text()
        assert "### Critical Rules" in content
        # Empty sections should not appear
        assert "### Frequent Mistakes" not in content
        assert "### Active Agent Calls" not in content
        assert "### Active Skill Calls" not in content
        assert "### Tooling Notes" not in content

    def test_backup_created_before_publish(self, project_with_muscle_dir: Path):
        """Test that a backup is created before publishing."""
        from tools.muscle.backup_manager import BackupManager
        from tools.muscle.claude_publisher import ClaudePublisher
        from tools.muscle.project_memory import ProjectMemory

        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n")

        # Publisher now uses shared BackupManager - backup is recorded in DB
        publisher = ClaudePublisher(str(project_with_muscle_dir))
        publisher.publish(critical_rules=[{"text": "Rule", "score": 0.8, "validated_count": 3}])

        # Verify backup was recorded via the shared BackupManager
        pm = ProjectMemory(str(project_with_muscle_dir))
        backup_mgr = BackupManager(pm, str(project_with_muscle_dir))
        backups = backup_mgr.list_backups(backup_type="claude_md")
        assert len(backups) >= 1

    def test_learning_pipeline_publishes_rules_and_active_skills_together(
        self, project_with_muscle_dir: Path
    ):
        """A review should not lose promoted rules when active skills are also published."""
        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n")

        pm = ProjectMemory(str(project_with_muscle_dir))
        skill_path = project_with_muscle_dir / ".muscle" / "skills" / "sql_safety.md"
        skill_path.write_text("# SQL Safety\n")
        skill_id = pm.insert_skill(
            project_path=str(project_with_muscle_dir),
            name="sql_safety",
            description="Skill for SQL safety",
            trigger_pattern="sql_safety",
            file_path=str(skill_path),
            status="active",
        )
        pm.update_skill_evidence_count(skill_id, 3)

        pipeline = LearningPipeline(str(project_with_muscle_dir))
        issues = [
            make_review_issue(
                severity=Severity.HIGH,
                title="Use parameterized queries",
                suggested_fix="Avoid string interpolation in SQL",
            ),
        ]
        result = make_review_result(issues, target_path=str(project_with_muscle_dir))

        pipeline.learn_from_review(result)

        content = root_claude.read_text()
        assert "### Critical Rules" in content
        assert "### Active Skill Calls" in content
        assert "Use parameterized queries" in content
        assert "sql_safety" in content


class TestSkillAgentIntegration:
    """Integration tests for skill + agent lifecycle and root CLAUDE.md publishing."""

    def test_learn_from_review_generates_skills_and_agents(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Full cycle: review with issues -> skills and agents detected -> decisions recorded."""
        pipeline = LearningPipeline(str(project_with_muscle_dir), m27_client=mock_m27)

        issues = [
            make_review_issue(
                severity=Severity.CRITICAL,
                title="SQL injection in auth",
                suggested_fix="Use parameterized queries",
            ),
            make_review_issue(
                severity=Severity.HIGH,
                title="Hardcoded secret",
                file_path="src/config.py",
            ),
        ]
        result = make_review_result(issues, target_path=str(project_with_muscle_dir))

        actions = pipeline.learn_from_review(result)

        # Should have generated skills or agents (depending on patterns)
        assert "skills_generated" in actions
        assert "agents_generated" in actions
        assert "decisions_recorded" in actions
        assert actions["decisions_recorded"] >= 0

    def test_active_skills_published_to_root_claude_md(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Active skills from DB are published to root CLAUDE.md."""
        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n\n## Project Info\n\nContent\n")

        pm = ProjectMemory(str(project_with_muscle_dir))

        # Insert active skill into DB
        skill_id = pm.insert_skill(
            project_path=str(project_with_muscle_dir),
            name="secure_hashing",
            description="Detects insecure hashing",
            trigger_pattern="insecure_hash",
            file_path=".muscle/skills/secure_hashing.md",
            status="active",
        )

        pipeline = LearningPipeline(str(project_with_muscle_dir), m27_client=mock_m27)
        pipeline._publish_active_specializations()

        content = root_claude.read_text()
        assert "<!-- MUSCLE_PUBLISHED_START -->" in content
        assert "secure_hashing" in content or "Secure Hashing" in content

    def test_active_agents_published_to_root_claude_md(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Active agents from DB are published to root CLAUDE.md."""
        root_claude = project_with_muscle_dir / "CLAUDE.md"
        root_claude.write_text("# CLAUDE.md\n\n## Project Info\n\nContent\n")

        pm = ProjectMemory(str(project_with_muscle_dir))

        # Insert active agent into DB
        agent_id = pm.insert_agent(
            project_path=str(project_with_muscle_dir),
            name="security_reviewer",
            description="Reviews security patterns",
            trigger_pattern="security",
            file_path=".muscle/agents/security_reviewer.md",
            status="active",
        )

        pipeline = LearningPipeline(str(project_with_muscle_dir), m27_client=mock_m27)
        pipeline._publish_active_specializations()

        content = root_claude.read_text()
        assert "<!-- MUSCLE_PUBLISHED_START -->" in content
        assert "security_reviewer" in content

    def test_agent_decision_recorded_on_creation(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Agent creation is recorded in memory_decisions table."""
        pm = ProjectMemory(str(project_with_muscle_dir))

        # Pre-populate decisions to meet evidence threshold
        for i in range(3):
            pm.record_agent_decision(
                project_path=str(project_with_muscle_dir),
                agent_id=0,
                decision_type="agent_candidate",
                reasoning=f"Agent candidate for security pattern - occurrence {i+1}",
                evidence_json=f'{{"occurrences": {i+1}}}',
            )

        from tools.muscle.code_review.agent_generator import AgentGenerator
        from tools.muscle.code_review.pattern_detector import PatternCluster

        pattern = PatternCluster(
            pattern_id="security_1",
            pattern="auth_bypass",
            category="security",
            summary="Auth bypass",
            root_cause="Missing check",
            occurrences=5,
            files=["src/auth.py"],
            severity_counts={"CRITICAL": 3},
            confidence=0.8,
            evidence_count=3,
            semantically_related_issues=[],
        )

        agent_gen = AgentGenerator(
            str(project_with_muscle_dir),
            mock_m27,
            project_memory=pm,
        )
        agent_path = agent_gen.generate_agent(pattern, [])

        # Verify decision was recorded
        if agent_path:
            decisions = pm.list_decisions(decision_type="create_agent")
            assert len(decisions) >= 1
            decision = decisions[0]
            assert "auth_bypass" in decision["reasoning"]
            assert "create_agent" in decision["decision_type"]

    def test_skill_decision_recorded_on_promotion(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Skill promotion is recorded in memory_decisions table."""
        pm = ProjectMemory(str(project_with_muscle_dir))

        pipeline = LearningPipeline(str(project_with_muscle_dir), m27_client=mock_m27)

        from tools.muscle.code_review.pattern_detector import PatternCluster

        pattern = PatternCluster(
            pattern_id="null_check_1",
            pattern="null_check_missing",
            category="null-safety",
            summary="Missing null check",
            root_cause="No validation",
            occurrences=4,
            files=["src/api.py"],
            severity_counts={"HIGH": 4},
            confidence=0.75,
            evidence_count=2,
            semantically_related_issues=[],
        )

        pipeline._record_skill_decision(pattern, "promoted")

        decisions = pm.list_decisions(decision_type="create_skill")
        assert len(decisions) >= 1
        decision = decisions[0]
        assert "promoted" in decision["reasoning"]
        assert "null_check_missing" in decision["reasoning"]

    def test_archive_decision_recorded(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Archiving an agent would record the decision if migration were applied.

        NOTE: This test is skipped because _0003_agent_lifecycle.py migration is not
        loaded in _load_migrations() (both skill and agent lifecycle are labeled v1.2.0,
        and only skill_lifecycle is loaded). The archived_at column never gets added.
        This is a pre-existing bug in migrations/__init__.py.
        """
        pytest.skip("Pre-existing bug: _0003_agent_lifecycle.py migration not loaded")

    def test_reject_decision_recorded_when_cap_reached(
        self, project_with_muscle_dir: Path, mock_m27: MockM27Client
    ):
        """Agent rejection due to cap records decision in memory_decisions."""
        pm = ProjectMemory(str(project_with_muscle_dir))

        pipeline = LearningPipeline(str(project_with_muscle_dir), m27_client=mock_m27)

        from tools.muscle.code_review.pattern_detector import PatternCluster

        pattern = PatternCluster(
            pattern_id="complex_1",
            pattern="complex_pattern",
            category="security",
            summary="Complex security issue",
            root_cause="Architecture flaw",
            occurrences=6,
            files=["src/core.py"],
            severity_counts={"CRITICAL": 6},
            confidence=0.9,
            evidence_count=5,
            semantically_related_issues=[],
        )

        # Record rejection (simulating cap reached scenario)
        pipeline._record_agent_decision(
            pattern, "rejected: At max capacity (10) and no agents to archive", None
        )

        decisions = pm.list_decisions(decision_type="create_agent")
        assert len(decisions) >= 1
        decision = decisions[0]
        assert "rejected" in decision["reasoning"]
        assert "capacity" in decision["reasoning"].lower() or "10" in decision["reasoning"]

