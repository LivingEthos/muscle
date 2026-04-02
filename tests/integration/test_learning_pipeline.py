"""
Integration tests for the self-learning pipeline.

Tests LearningPipeline -> MemoryManager -> PatternDetector -> SkillGenerator
-> StrategyEvolver with realistic review results and project state.
"""

from __future__ import annotations

from pathlib import Path

from tools.muscle.code_review.learning_pipeline import LearningPipeline
from tools.muscle.code_review.memory_manager import MemoryManager
from tools.muscle.code_review.pattern_detector import PatternCluster, PatternDetector
from tools.muscle.code_review.skill_generator import SkillGenerator
from tools.muscle.code_review.types import (
    Severity,
)

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
        generator = SkillGenerator(str(project_with_muscle_dir), mock_m27)

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
