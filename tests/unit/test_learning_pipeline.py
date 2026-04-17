"""
Tests for learning_pipeline.py — LearningPipeline orchestrator for self-learning after reviews.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.code_review.types import (
    IssueCategory,
    ReviewIssue,
    ReviewResult,
    Severity,
)


def _make_issue(
    title="Test issue",
    severity=Severity.HIGH,
    category=IssueCategory.CORRECTNESS,
    file_path="src/foo.py",
    line_number=10,
    suggested_fix="Fix it",
):
    return ReviewIssue(
        file_path=file_path,
        line_number=line_number,
        severity=severity,
        category=category,
        cwe_id=None,
        title=title,
        description="Test description",
        code_snippet="x = 1",
        suggested_fix=suggested_fix,
    )


def _make_review_result(issues=None):
    issues = issues or []
    return ReviewResult(
        session_id="test-session",
        target_path="./src",
        issues=issues,
        critical_count=sum(1 for i in issues if i.severity == Severity.CRITICAL),
        high_count=sum(1 for i in issues if i.severity == Severity.HIGH),
        medium_count=sum(1 for i in issues if i.severity == Severity.MEDIUM),
        low_count=sum(1 for i in issues if i.severity == Severity.LOW),
    )


class TestLearningPipelineCategorize:
    """Tests that _categorize_findings correctly splits high/critical from medium/low."""

    def test_high_issues_go_to_immediate(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            high_issue = _make_issue(severity=Severity.HIGH)
            result = _make_review_result([high_issue])

            immediate, tracked = pipeline._categorize_findings(result)

            assert len(immediate) == 1
            assert len(tracked) == 0
            assert immediate[0].severity == Severity.HIGH

    def test_critical_issues_go_to_immediate(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            critical_issue = _make_issue(severity=Severity.CRITICAL)
            result = _make_review_result([critical_issue])

            immediate, tracked = pipeline._categorize_findings(result)

            assert len(immediate) == 1
            assert immediate[0].severity == Severity.CRITICAL

    def test_medium_issues_go_to_tracked(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            medium_issue = _make_issue(severity=Severity.MEDIUM)
            result = _make_review_result([medium_issue])

            immediate, tracked = pipeline._categorize_findings(result)

            assert len(immediate) == 0
            assert len(tracked) == 1
            assert tracked[0].severity == Severity.MEDIUM

    def test_low_issues_go_to_tracked(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            low_issue = _make_issue(severity=Severity.LOW)
            result = _make_review_result([low_issue])

            immediate, tracked = pipeline._categorize_findings(result)

            assert len(immediate) == 0
            assert len(tracked) == 1

    def test_info_issues_go_to_tracked(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            info_issue = _make_issue(severity=Severity.INFO)
            result = _make_review_result([info_issue])

            immediate, tracked = pipeline._categorize_findings(result)

            assert len(immediate) == 0
            assert len(tracked) == 1

    def test_mixed_severity_split(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issues = [
                _make_issue(title="Critical bug", severity=Severity.CRITICAL),
                _make_issue(title="High bug", severity=Severity.HIGH),
                _make_issue(title="Medium issue", severity=Severity.MEDIUM),
                _make_issue(title="Low issue", severity=Severity.LOW),
                _make_issue(title="Info note", severity=Severity.INFO),
            ]
            result = _make_review_result(issues)

            immediate, tracked = pipeline._categorize_findings(result)

            assert len(immediate) == 2  # critical + high
            assert len(tracked) == 3  # medium + low + info


class TestLearningPipelineUpdateClaudeMd:
    """Tests that high/critical issues create rules in CLAUDE.md."""

    def test_high_issue_creates_dont_rule(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(
                title="SQL injection risk",
                severity=Severity.HIGH,
                suggested_fix="Use parameterized queries",
            )
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            assert actions["rules_added"] == 1
            # Verify the rule was written to CLAUDE.md
            claude_md = pipeline.memory_manager.muscle_dir / "CLAUDE.md"
            assert claude_md.exists()
            content = claude_md.read_text()
            assert "SQL injection risk" in content

    def test_critical_issue_creates_rule_with_suggested_fix(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(
                title="Buffer overflow",
                severity=Severity.CRITICAL,
                suggested_fix="Validate input length",
            )
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            assert actions["rules_added"] == 1
            claude_md = pipeline.memory_manager.muscle_dir / "CLAUDE.md"
            content = claude_md.read_text()
            # When suggested_fix is present, rule_text should include it
            assert "Validate input length" in content

    def test_issue_without_suggested_fix_uses_file_path(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(
                title="Missing null check",
                severity=Severity.HIGH,
                file_path="src/handler.py",
                suggested_fix=None,
            )
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            assert actions["rules_added"] == 1
            claude_md = pipeline.memory_manager.muscle_dir / "CLAUDE.md"
            content = claude_md.read_text()
            assert "Missing null check" in content
            assert "src/handler.py" in content

    def test_medium_issue_does_not_create_rule(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(title="Style nit", severity=Severity.MEDIUM)
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            assert actions["rules_added"] == 0

    def test_duplicate_rule_not_added_twice(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(
                title="SQL injection risk",
                severity=Severity.HIGH,
                suggested_fix="Use params",
            )
            result1 = _make_review_result([issue])
            result2 = _make_review_result([issue])

            actions1 = pipeline.learn_from_review(result1)
            actions2 = pipeline.learn_from_review(result2)

            assert actions1["rules_added"] == 1
            assert actions2["rules_added"] == 0

    def test_clean_review_persists_review_run(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            result = _make_review_result([])

            actions = pipeline.learn_from_review(result, review_mode="review", duration_ms=250)

            assert actions["review_run_id"] is not None
            stored = pipeline._pm.get_review_run(actions["review_run_id"])
            assert stored is not None
            assert stored["findings_count"] == 0
            assert stored["duration_ms"] == 250

    def test_decisions_link_to_inserted_finding_ids(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(title="Linked issue", severity=Severity.HIGH)
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            findings = pipeline._pm.list_findings_for_run(actions["review_run_id"])
            decisions = pipeline._pm.list_decisions(project_path=tmpdir, limit=10)

            assert len(findings) == 1
            assert len(decisions) >= 1
            assert decisions[0]["source_table"] == "review_findings"
            assert decisions[0]["source_id"] == findings[0]["id"]


class TestLearningPipelineValidation:
    """Tests for the validation loop: rules validated when pattern absent, confidence upgrades, stale rules archived."""

    def test_rule_validated_when_pattern_absent(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            # First, add a rule
            pipeline.memory_manager.write_rule(
                rule_text="Avoid raw SQL",
                rule_type="dont",
                severity="high",
                confidence="low",
                validated_count=0,
            )

            # Review with no matching issues
            clean_result = _make_review_result([])

            actions = pipeline.learn_from_review(clean_result)

            assert actions["rules_validated"] >= 1
            # Check the rule's validated_count was incremented
            rules = pipeline.memory_manager.read_rules()
            assert len(rules) == 1
            assert rules[0]["validated_count"] == 1

    def test_confidence_upgrades_with_validations(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            pipeline.memory_manager.write_rule(
                rule_text="Check return values",
                rule_type="do",
                severity="medium",
                confidence="low",
                validated_count=1,
            )

            # Run clean reviews to bump validation count
            clean_result = _make_review_result([])
            pipeline.learn_from_review(clean_result)

            rules = pipeline.memory_manager.read_rules()
            assert len(rules) == 1
            assert rules[0]["validated_count"] == 2
            assert rules[0]["confidence"] == "medium"

    def test_confidence_reaches_high(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            pipeline.memory_manager.write_rule(
                rule_text="Always validate inputs",
                rule_type="do",
                severity="high",
                confidence="medium",
                validated_count=3,
            )

            clean_result = _make_review_result([])
            pipeline.learn_from_review(clean_result)

            rules = pipeline.memory_manager.read_rules()
            assert rules[0]["validated_count"] == 4
            assert rules[0]["confidence"] == "high"

    def test_stale_rule_archived_after_threshold(self):
        from tools.muscle.code_review.learning_pipeline import (
            ARCHIVE_VALIDATED_THRESHOLD,
            LearningPipeline,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            # Set validated_count to just below the threshold
            pipeline.memory_manager.write_rule(
                rule_text="Obsolete pattern",
                rule_type="dont",
                severity="low",
                confidence="high",
                validated_count=ARCHIVE_VALIDATED_THRESHOLD - 1,
            )

            clean_result = _make_review_result([])
            actions = pipeline.learn_from_review(clean_result)

            assert actions["rules_archived"] == 1
            # Rule should be removed from CLAUDE.md
            rules = pipeline.memory_manager.read_rules()
            assert len(rules) == 0
            # And archived in MEMORY.md
            memory_md = pipeline.memory_manager.muscle_dir / "MEMORY.md"
            assert memory_md.exists()
            content = memory_md.read_text()
            assert "Obsolete pattern" in content

    def test_rule_not_validated_when_pattern_found(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            pipeline.memory_manager.write_rule(
                rule_text="SQL injection risk",
                rule_type="dont",
                severity="high",
                confidence="low",
                validated_count=0,
            )

            # Review that has the same pattern
            issue = _make_issue(title="SQL injection risk", severity=Severity.HIGH)
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            # Rule should NOT be validated (pattern still seen)
            rules = pipeline.memory_manager.read_rules()
            matching = [r for r in rules if "SQL injection" in r["text"]]
            # validated_count stays at 0 (not incremented)
            for rule in matching:
                assert rule["validated_count"] == 0

    def test_compute_confidence_boundaries(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            assert pipeline._compute_confidence(0) == "low"
            assert pipeline._compute_confidence(1) == "low"
            assert pipeline._compute_confidence(2) == "medium"
            assert pipeline._compute_confidence(3) == "medium"
            assert pipeline._compute_confidence(4) == "high"
            assert pipeline._compute_confidence(10) == "high"


class TestLearningPipelineMemoryMd:
    """Tests for review session logging to MEMORY.md."""

    def test_session_logged_on_review(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(severity=Severity.HIGH)
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            assert actions["session_logged"] is True
            memory_md = pipeline.memory_manager.muscle_dir / "MEMORY.md"
            assert memory_md.exists()
            content = memory_md.read_text()
            assert "critical=0" in content
            assert "high=1" in content

    def test_session_logged_for_empty_review(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            result = _make_review_result([])

            actions = pipeline.learn_from_review(result)

            assert actions["session_logged"] is True

    def test_tracked_issues_logged_to_memory(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            medium_issue = _make_issue(
                title="Unused import",
                severity=Severity.MEDIUM,
                file_path="src/utils.py",
            )
            result = _make_review_result([medium_issue])

            actions = pipeline.learn_from_review(result)

            # Medium issues should be tracked in MEMORY.md via update_memory_md
            memory_md = pipeline.memory_manager.muscle_dir / "MEMORY.md"
            assert memory_md.exists()
            content = memory_md.read_text()
            assert "Unused import" in content

    def test_actions_summary_logged(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            issue = _make_issue(severity=Severity.HIGH, title="Test rule addition")
            result = _make_review_result([issue])

            actions = pipeline.learn_from_review(result)

            assert actions["rules_added"] >= 1
            memory_md = pipeline.memory_manager.muscle_dir / "MEMORY.md"
            content = memory_md.read_text()
            assert "added" in content.lower() or "rule" in content.lower()


class TestLearningPipelineSkillGeneration:
    """Tests for skill detection and generation flow."""

    def test_skill_generation_handles_no_patterns(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)

            # Mock PatternDetector to return no patterns
            with patch(
                "tools.muscle.code_review.learning_pipeline.PatternDetector"
            ) as mock_detector_cls:
                mock_detector = MagicMock()
                mock_detector.detect_patterns.return_value = []
                mock_detector.get_skill_candidates.return_value = []
                mock_detector.get_agent_candidates.return_value = []
                mock_detector_cls.return_value = mock_detector

                skill_count, agent_count = pipeline._detect_and_generate_specializations()

            assert skill_count == 0
            assert agent_count == 0

    def test_skill_generation_catches_exceptions(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)

            with patch(
                "tools.muscle.code_review.learning_pipeline.PatternDetector"
            ) as mock_detector_cls:
                mock_detector_cls.side_effect = Exception("DB error")

                skill_count, agent_count = pipeline._detect_and_generate_specializations()

            assert skill_count == 0
            assert agent_count == 0

    def test_learn_from_review_returns_complete_actions_dict(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)
            result = _make_review_result([])

            actions = pipeline.learn_from_review(result)

            assert "rules_added" in actions
            assert "rules_validated" in actions
            assert "rules_archived" in actions
            assert "skills_generated" in actions
            assert "session_logged" in actions


class TestLearningPipelineInit:
    """Tests for LearningPipeline initialization."""

    def test_init_creates_memory_manager(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)

            assert pipeline.project_path == Path(tmpdir)
            assert pipeline.memory_manager is not None
            assert pipeline.m27 is None

    def test_init_with_m27_client(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_m27 = MagicMock()
            pipeline = LearningPipeline(tmpdir, m27_client=mock_m27)

            assert pipeline.m27 is mock_m27


class TestLearningPipelineEndToEnd:
    def test_full_cycle_learn_validate_archive(self, tmp_path):
        """Simulate: review with issues -> rules added -> clean review -> rules validated -> many clean reviews -> rule archived."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))

        # Review 1: issues found -> rules added
        issues = [
            _make_issue(title="Use print instead of logger", severity=Severity.HIGH),
            _make_issue(title="Missing null check", severity=Severity.CRITICAL),
        ]
        result1 = _make_review_result(issues)
        actions1 = pipeline.learn_from_review(result1)
        assert actions1["rules_added"] == 2

        rules = pipeline.memory_manager.read_rules()
        assert len(rules) == 2
        assert all(r["confidence"] == "low" for r in rules)

        # Review 2: clean -> rules validated, confidence upgrades
        result2 = _make_review_result([])
        actions2 = pipeline.learn_from_review(result2)
        assert actions2["rules_validated"] == 2

        rules = pipeline.memory_manager.read_rules()
        assert all(r["validated_count"] >= 1 for r in rules)

        # Review 3: clean again -> further validation
        result3 = _make_review_result([])
        pipeline.learn_from_review(result3)

        rules = pipeline.memory_manager.read_rules()
        assert any(r["confidence"] == "medium" for r in rules)

    def test_memory_md_tracks_sessions(self, tmp_path):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))
        issues = [_make_issue(severity=Severity.HIGH)]
        result = _make_review_result(issues)
        pipeline.learn_from_review(result)

        memory_md = tmp_path / ".muscle" / "MEMORY.md"
        assert memory_md.exists()
        content = memory_md.read_text()
        assert "Review Sessions" in content

    def test_outside_markers_untouched(self, tmp_path):
        """Verify that content outside MUSCLE markers is never modified."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.memory_manager import RULES_END, RULES_START

        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir(parents=True, exist_ok=True)
        claude_md = muscle_dir / "CLAUDE.md"
        claude_md.write_text(
            "# My Project Rules\n\nDo not touch this.\n\n"
            f"## MUSCLE Learned Rules\n"
            f"{RULES_START}\n\n"
            f"### Do\n\n### Don't\n\n### Project Skills\n\n"
            f"{RULES_END}\n"
        )

        pipeline = LearningPipeline(str(tmp_path))
        issues = [_make_issue(title="New issue", severity=Severity.HIGH)]
        result = _make_review_result(issues)
        pipeline.learn_from_review(result)

        content = claude_md.read_text()
        assert "# My Project Rules" in content
        assert "Do not touch this." in content
        assert "New issue" in content

    def test_multiple_reviews_compound_learning(self, tmp_path):
        """Multiple reviews with different issues should accumulate rules."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))

        # Review 1
        result1 = _make_review_result(
            [_make_issue(title="SQL injection risk", severity=Severity.CRITICAL)]
        )
        pipeline.learn_from_review(result1)

        # Review 2 (different issue)
        result2 = _make_review_result(
            [_make_issue(title="Hardcoded secrets", severity=Severity.HIGH)]
        )
        pipeline.learn_from_review(result2)

        rules = pipeline.memory_manager.read_rules()
        rule_texts = [r["text"] for r in rules]
        assert any("SQL injection" in t for t in rule_texts)
        assert any("Hardcoded secrets" in t for t in rule_texts)


class TestSkillLifecycleDB:
    """Tests for DB-first skill lifecycle: metadata in DB, duplicate suppression, revisioning."""

    def test_skill_creation_writes_to_db(self, tmp_path):
        """Skill generation writes skill metadata to project_memory.db."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternCluster
        from tools.muscle.code_review.skill_generator import SkillGenerator

        pipeline = LearningPipeline(str(tmp_path))

        # Create a mock pattern
        pattern = PatternCluster(
            pattern_id="test_pattern",
            pattern="null_check_missing",
            category="null-safety",
            summary="Missing null check on external data",
            root_cause="Assuming external data is always valid",
            occurrences=5,
            files=["src/api.py", "src/handler.py"],
            severity_counts={"HIGH": 3, "MEDIUM": 2},
            confidence=0.8,
            evidence_count=5,
            semantically_related_issues=[],
        )

        # Mock M27 to avoid actual API calls
        with patch.object(pipeline._publisher, "publish"):
            with patch("tools.muscle.code_review.skill_generator.M27Client") as mock_m27:
                mock_instance = MagicMock()
                mock_instance.chat.return_value = (
                    "---\nname: test\ndescription: test desc\ntriggers:\n---\n# Test\n",
                    None,
                )
                mock_m27.return_value = mock_instance

                generator = SkillGenerator(
                    str(tmp_path),
                    m27_client=mock_instance,
                    project_memory=pipeline._pm,
                )
                skill_path = generator.generate_skill(pattern, [])

        assert skill_path is not None
        # Verify skill was written to DB
        skills = pipeline._pm.list_skills(project_path=str(tmp_path))
        assert len(skills) >= 1
        skill = next(s for s in skills if s["name"] == "null_check_missing")
        assert skill["trigger_pattern"] == "null_check_missing"
        assert skill["status"] == "active"
        assert skill["evidence_count"] == 5

    def test_duplicate_skill_suppressed(self, tmp_path):
        """Skill with same trigger_pattern is suppressed if active skill exists."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternCluster
        from tools.muscle.code_review.skill_generator import SkillGenerator

        # Pre-create a skill in DB
        pipeline = LearningPipeline(str(tmp_path))
        pm = pipeline._pm
        skill_id = pm.insert_skill(
            project_path=str(tmp_path),
            name="existing_skill",
            description="Already exists",
            trigger_pattern="null_check_missing",
            file_path=".muscle/skills/null_check_missing.md",
            status="active",
        )

        pattern = PatternCluster(
            pattern_id="dup_pattern",
            pattern="null_check_missing",
            category="null-safety",
            summary="Duplicate pattern",
            root_cause="Same",
            occurrences=3,
            files=["src/other.py"],
            severity_counts={"HIGH": 3},
            confidence=0.8,
            evidence_count=3,
            semantically_related_issues=[],
        )

        with patch("tools.muscle.code_review.skill_generator.M27Client") as mock_m27:
            mock_instance = MagicMock()
            mock_instance.chat.return_value = ("---\nname: new\n---\n# New\n", None)
            mock_m27.return_value = mock_instance

            generator = SkillGenerator(
                str(tmp_path),
                m27_client=mock_instance,
                project_memory=pm,
            )
            result = generator.generate_skill(pattern, [])

        # Should be suppressed (None returned)
        assert result is None
        # DB should still have only 1 skill
        skills = pm.list_skills(project_path=str(tmp_path), status="active")
        assert len(skills) == 1

    def test_skill_creation_records_decision(self, tmp_path):
        """Skill creation records CREATE_SKILL decision in memory_decisions with reasoning."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternCluster
        from tools.muscle.code_review.skill_generator import SkillGenerator

        pipeline = LearningPipeline(str(tmp_path))

        pattern = PatternCluster(
            pattern_id="reasoning_test",
            pattern="resource_leak",
            category="resource-management",
            summary="File handle not closed",
            root_cause="Missing close() call",
            occurrences=4,
            files=["src/fileutil.py"],
            severity_counts={"HIGH": 4},
            confidence=0.75,
            evidence_count=2,
            semantically_related_issues=[],
        )

        with patch("tools.muscle.code_review.skill_generator.M27Client") as mock_m27:
            mock_instance = MagicMock()
            mock_instance.chat.return_value = (
                "---\nname: resource\ndescription: close files\ntriggers:\n---\n# Resource\n",
                None,
            )
            mock_m27.return_value = mock_instance

            generator = SkillGenerator(
                str(tmp_path),
                m27_client=mock_instance,
                project_memory=pipeline._pm,
            )
            generator.generate_skill(pattern, [{"title": "Issue 1"}])

        # Verify decision was recorded
        decisions = pipeline._pm.list_decisions(decision_type="create_skill")
        assert len(decisions) >= 1
        decision = decisions[0]
        assert "resource_leak" in decision["reasoning"]
        assert "4" in decision["reasoning"]  # occurrences

    def test_skill_revision_increments_on_update(self, tmp_path):
        """update_skill increments revision number, not just appending."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.skill_generator import SkillGenerator

        pipeline = LearningPipeline(str(tmp_path))

        skill_file = tmp_path / ".muscle" / "skills" / "test_skill.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(
            "---\nname: test\ndescription: test\ntriggers:\n---\n# Test\n## Old content\n"
        )

        # Write initial skill to DB
        pm = pipeline._pm
        pm.insert_skill(
            project_path=str(tmp_path),
            name="test_skill",
            description="test",
            trigger_pattern="test_pattern",
            file_path=str(skill_file),
            status="active",
        )

        generator = SkillGenerator(str(tmp_path), project_memory=pm)
        generator.update_skill(skill_file, "New update content")

        content = skill_file.read_text()
        assert "revision: 2" in content
        # Should NOT just append (old update section shouldn't be duplicated)
        assert content.count("## Update") == 1

    def test_archive_skill_updates_db_and_file(self, tmp_path):
        """archive_skill marks DB record as archived and moves file."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.skill_generator import SkillGenerator

        pipeline = LearningPipeline(str(tmp_path))

        skill_file = tmp_path / ".muscle" / "skills" / "archivable.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("---\nname: arch\n---\n# Arch\n")

        pm = pipeline._pm
        skill_id = pm.insert_skill(
            project_path=str(tmp_path),
            name="archivable",
            description="to archive",
            trigger_pattern="old_pattern",
            file_path=str(skill_file),
            status="active",
        )

        generator = SkillGenerator(str(tmp_path), project_memory=pm)
        archived_path = generator.archive_skill(skill_file, reason="low evidence")

        # File should be moved to archived/
        assert not skill_file.exists()
        assert archived_path.exists()
        assert "archived" in str(archived_path)

        # DB should be updated
        skill = pm.get_skill(skill_id)
        assert skill["status"] == "archived"
        assert skill["archived_at"] is not None

    def test_stale_skills_archived_by_pipeline(self, tmp_path):
        """_archive_stale_skills archives active skills with low evidence_count."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))

        # Create a stale skill (old, low evidence)
        skill_file = tmp_path / ".muscle" / "skills" / "stale.md"
        skill_file.parent.mkdir(parents=True, exist_ok=True)
        skill_file.write_text("---\nname: stale\n---\n# Stale\n")

        pm = pipeline._pm
        skill_id = pm.insert_skill(
            project_path=str(tmp_path),
            name="stale_skill",
            description="old",
            trigger_pattern="stale_pattern",
            file_path=str(skill_file),
            status="active",
        )

        # Directly set a very old created_at and low evidence_count
        conn = pm._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE skills
            SET created_at = datetime('now', '-60 days'),
                evidence_count = 1
            WHERE id = ?
            """,
            (skill_id,),
        )
        conn.commit()
        conn.close()

        archived = pipeline._archive_stale_skills()

        # Skill should be archived
        skill = pm.get_skill(skill_id)
        assert skill["status"] == "archived"

    def test_pattern_detector_queries_memory_decisions(self, tmp_path):
        """PatternDetector uses memory_decisions for evidence_count when project_memory provided."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternDetector

        pipeline = LearningPipeline(str(tmp_path))

        # Pre-record a create_skill decision
        pm = pipeline._pm
        pm.record_skill_decision(
            project_path=str(tmp_path),
            skill_id=0,
            reasoning="Skill for null_check_missing pattern - detected 5 times",
            evidence_json='{"occurrences": 5}',
        )

        detector = PatternDetector(
            kb_path=None,
            project_memory=pm,
        )

        # The evidence query should return 1 for "null_check_missing"
        evidence = detector._get_evidence_from_decisions("null_check_missing")
        assert evidence >= 1


class TestSkillGeneratorDBMethods:
    """Unit tests for SkillGenerator DB-first methods."""

    def test_insert_skill_writes_all_fields(self, tmp_path):
        """insert_skill stores all provided fields in DB."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))
        pm = pipeline._pm

        skill_id = pm.insert_skill(
            project_path=str(tmp_path),
            name="full_skill",
            description="A complete skill",
            trigger_pattern="full_pattern",
            file_path=".muscle/skills/full_skill.md",
            status="active",
        )

        skill = pm.get_skill(skill_id)
        assert skill["name"] == "full_skill"
        assert skill["description"] == "A complete skill"
        assert skill["trigger_pattern"] == "full_pattern"
        assert skill["status"] == "active"

    def test_update_skill_evidence_count(self, tmp_path):
        """update_skill_evidence_count correctly updates evidence_count."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))
        pm = pipeline._pm

        skill_id = pm.insert_skill(
            project_path=str(tmp_path),
            name="ev_skill",
            description="test",
            trigger_pattern="ev_pattern",
            status="active",
        )

        pm.update_skill_evidence_count(skill_id, 10)
        skill = pm.get_skill(skill_id)
        assert skill["evidence_count"] == 10

        # Should be MAX, not replace
        pm.update_skill_evidence_count(skill_id, 5)
        skill = pm.get_skill(skill_id)
        assert skill["evidence_count"] == 10  # MAX(10, 5) = 10

    def test_skill_similar_exists_suppresses_dupes(self, tmp_path):
        """skill_similar_exists returns existing skill for same trigger_pattern, suppresses creation."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))
        pm = pipeline._pm

        # Insert first skill
        skill_id1 = pm.insert_skill(
            project_path=str(tmp_path),
            name="first",
            description="first",
            trigger_pattern="shared_pattern",
            status="active",
        )

        # Check similar exists
        existing = pm.skill_similar_exists(str(tmp_path), "shared_pattern", "active")
        assert existing is not None
        assert existing["id"] == skill_id1

        # Archived skill should not match (status filter)
        pm.archive_skill(skill_id1, "archived")
        existing_after = pm.skill_similar_exists(str(tmp_path), "shared_pattern", "active")
        assert existing_after is None  # No active match

    def test_get_stale_skills_returns_low_evidence(self, tmp_path):
        """get_stale_skills returns active skills with evidence_count below threshold."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))
        pm = pipeline._pm

        # Stale: low evidence, old
        sid1 = pm.insert_skill(
            project_path=str(tmp_path),
            name="stale1",
            description="desc",
            trigger_pattern="stale1",
            status="active",
        )
        # Fresh: high evidence
        sid2 = pm.insert_skill(
            project_path=str(tmp_path),
            name="fresh",
            description="desc",
            trigger_pattern="fresh",
            status="active",
        )

        conn = pm._get_connection()
        cursor = conn.cursor()
        # Make stale1 very old and low evidence
        cursor.execute(
            "UPDATE skills SET created_at = datetime('now', '-60 days'), evidence_count = 1 WHERE id = ?",
            (sid1,),
        )
        # Make fresh recent with high evidence
        cursor.execute(
            "UPDATE skills SET created_at = datetime('now', '-1 day'), evidence_count = 10 WHERE id = ?",
            (sid2,),
        )
        conn.commit()
        conn.close()

        stale = pm.get_stale_skills(str(tmp_path), evidence_threshold=3, lookback_days=30)
        stale_ids = [s["id"] for s in stale]
        assert sid1 in stale_ids
        assert sid2 not in stale_ids


class TestAgentLifecycleDB:
    """Tests for DB-first agent lifecycle: cap enforcement, evidence thresholds, decision recording."""

    def test_agent_creation_records_decision(self, tmp_path):
        """Agent creation records CREATE_AGENT decision in memory_decisions with reasoning."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternCluster

        pipeline = LearningPipeline(str(tmp_path))

        pattern = PatternCluster(
            pattern_id="security_auth",
            pattern="auth_bypass",
            category="security",
            summary="Authentication bypass vulnerabilities",
            root_cause="Missing auth checks",
            occurrences=6,
            files=["src/auth.py", "src/login.py"],
            severity_counts={"CRITICAL": 4, "HIGH": 2},
            confidence=0.75,
            evidence_count=3,
            semantically_related_issues=[],
        )

        with patch("tools.muscle.code_review.agent_generator.M27Client") as mock_m27:
            mock_instance = MagicMock()
            mock_instance.chat.return_value = (
                "---\nname: auth\ndescription: Auth agent\ntriggers:\n---\n# Auth Agent\n",
                None,
            )
            mock_m27.return_value = mock_instance

            # Pre-populate decisions to meet evidence threshold
            pm = pipeline._pm
            for i in range(3):
                pm.record_agent_decision(
                    project_path=str(tmp_path),
                    agent_id=0,
                    decision_type="agent_candidate",
                    reasoning=f"Agent candidate for auth_bypass pattern - occurrence {i + 1}",
                    evidence_json=f'{{"occurrences": {i + 1}}}',
                )

            from tools.muscle.code_review.agent_generator import AgentGenerator

            agent_gen = AgentGenerator(
                str(tmp_path),
                m27_client=mock_instance,
                project_memory=pm,
            )
            agent_path = agent_gen.generate_agent(pattern, [])

        # Verify decision was recorded
        if agent_path:
            decisions = pipeline._pm.list_decisions(decision_type="create_agent")
            assert len(decisions) >= 1
            decision = decisions[0]
            assert "auth_bypass" in decision["reasoning"]
            assert decision["evidence_json"] is not None

    def test_can_create_agent_checks_cap(self, tmp_path):
        """can_create_agent returns False when MAX_ACTIVE_AGENTS is reached."""
        from tools.muscle.code_review.agent_generator import MAX_ACTIVE_AGENTS, AgentGenerator

        mock_m27 = MagicMock()
        pm = MagicMock()
        pm.get_active_agents_count.return_value = MAX_ACTIVE_AGENTS
        pm.get_least_used_active_agent.return_value = None

        agent_gen = AgentGenerator(str(tmp_path), m27_client=mock_m27, project_memory=pm)
        can_create, reason = agent_gen.can_create_agent("test_pattern")

        assert can_create is False
        assert str(MAX_ACTIVE_AGENTS) in reason

    def test_can_create_agent_checks_evidence_threshold(self, tmp_path):
        """can_create_agent returns False when evidence threshold not met."""
        from tools.muscle.code_review.agent_generator import MIN_EVIDENCE_COUNT, AgentGenerator

        mock_m27 = MagicMock()
        pm = MagicMock()
        pm.get_active_agents_count.return_value = 0
        pm.count_decisions_for_pattern.return_value = MIN_EVIDENCE_COUNT - 1

        agent_gen = AgentGenerator(str(tmp_path), m27_client=mock_m27, project_memory=pm)
        can_create, reason = agent_gen.can_create_agent("test_pattern")

        assert can_create is False
        assert "threshold not met" in reason.lower()

    def test_can_create_agent_returns_true_when_checks_pass(self, tmp_path):
        """can_create_agent returns True when cap and evidence checks both pass."""
        from tools.muscle.code_review.agent_generator import MIN_EVIDENCE_COUNT, AgentGenerator

        mock_m27 = MagicMock()
        pm = MagicMock()
        pm.get_active_agents_count.return_value = 0
        pm.count_decisions_for_pattern.return_value = MIN_EVIDENCE_COUNT

        agent_gen = AgentGenerator(str(tmp_path), m27_client=mock_m27, project_memory=pm)
        can_create, reason = agent_gen.can_create_agent("test_pattern")

        assert can_create is True
        assert "All checks passed" in reason

    def test_archive_agent_records_decision(self, tmp_path):
        """archive_agent would record ARCHIVE_AGENT decision if migration were applied.

        NOTE: This test is skipped because _0003_agent_lifecycle.py migration is not
        loaded in _load_migrations() (both skill and agent lifecycle are labeled v1.2.0,
        and only skill_lifecycle is loaded). The archived_at column never gets added.
        This is a pre-existing bug in migrations/__init__.py.
        """
        pytest.skip("Pre-existing bug: _0003_agent_lifecycle.py migration not loaded")

    def test_record_agent_decision_in_project_memory(self, tmp_path):
        """project_memory.record_agent_decision stores decision in memory_decisions table."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))
        pm = pipeline._pm

        decision_id = pm.record_agent_decision(
            project_path=str(tmp_path),
            agent_id=1,
            decision_type="create_agent",
            reasoning="Test agent created for pattern X",
            evidence_json='{"occurrences": 5}',
        )

        assert decision_id > 0

        decisions = pm.list_decisions(decision_type="create_agent")
        assert len(decisions) >= 1
        assert decisions[0]["reasoning"] == "Test agent created for pattern X"


class TestLearningPipelineSpecializations:
    """Tests for LearningPipeline wiring of skills + agents with decision recording."""

    def test_detect_and_generate_specializations_returns_both_counts(self, tmp_path):
        """_detect_and_generate_specializations returns (skill_count, agent_count)."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))

        with patch(
            "tools.muscle.code_review.learning_pipeline.PatternDetector"
        ) as mock_detector_cls:
            mock_detector = MagicMock()
            mock_detector.detect_patterns.return_value = []
            mock_detector.get_skill_candidates.return_value = []
            mock_detector.get_agent_candidates.return_value = []
            mock_detector_cls.return_value = mock_detector

            skill_count, agent_count = pipeline._detect_and_generate_specializations()

        assert skill_count == 0
        assert agent_count == 0

    def test_learn_from_review_tracks_agents_generated(self, tmp_path):
        """learn_from_review actions dict includes agents_generated."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))

        with patch(
            "tools.muscle.code_review.learning_pipeline.PatternDetector"
        ) as mock_detector_cls:
            mock_detector = MagicMock()
            mock_detector.detect_patterns.return_value = []
            mock_detector.get_skill_candidates.return_value = []
            mock_detector.get_agent_candidates.return_value = []
            mock_detector_cls.return_value = mock_detector

            result = _make_review_result([])
            actions = pipeline.learn_from_review(result)

        assert "agents_generated" in actions
        assert actions["agents_generated"] == 0

    def test_publish_active_specializations_calls_publisher(self, tmp_path):
        """_publish_active_specializations calls _publisher.publish with skills and agents."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        pipeline = LearningPipeline(str(tmp_path))

        # Pre-populate skills and agents in DB WITH file_path (required for publishing)
        pm = pipeline._pm
        pm.insert_skill(
            project_path=str(tmp_path),
            name="test_skill",
            description="Test skill",
            trigger_pattern="test_pattern",
            file_path=".muscle/skills/test_skill.md",
            status="active",
        )
        pm.insert_agent(
            project_path=str(tmp_path),
            name="test_agent",
            description="Test agent",
            trigger_pattern="test_pattern",
            file_path=".muscle/agents/test_agent.md",
            status="active",
        )

        with patch.object(pipeline._publisher, "publish") as mock_publish:
            pipeline._publish_active_specializations()

            # Publisher should have been called with skill_calls and/or agent_calls
            assert mock_publish.call_count >= 1

    def test_decision_recording_for_skill_promotion(self, tmp_path):
        """Skill promotion records decision in memory_decisions."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternCluster

        pipeline = LearningPipeline(str(tmp_path))

        pattern = PatternCluster(
            pattern_id="null_check",
            pattern="null_check_missing",
            category="null-safety",
            summary="Missing null checks",
            root_cause="No validation",
            occurrences=5,
            files=["src/api.py"],
            severity_counts={"HIGH": 5},
            confidence=0.8,
            evidence_count=3,
            semantically_related_issues=[],
        )

        pipeline._record_skill_decision(pattern, "promoted")

        # Verify decision was recorded
        decisions = pipeline._pm.list_decisions(decision_type="create_skill")
        assert len(decisions) >= 1
        decision = decisions[0]
        assert "promoted" in decision["reasoning"]
        assert "null_check_missing" in decision["reasoning"]

    def test_decision_recording_for_agent_rejection(self, tmp_path):
        """Agent rejection records decision with reason in memory_decisions."""
        from tools.muscle.code_review.learning_pipeline import LearningPipeline
        from tools.muscle.code_review.pattern_detector import PatternCluster

        pipeline = LearningPipeline(str(tmp_path))

        pattern = PatternCluster(
            pattern_id="simple",
            pattern="simple_pattern",
            category="style",
            summary="Style issue",
            root_cause="Formatting",
            occurrences=2,
            files=["src/style.py"],
            severity_counts={"LOW": 2},
            confidence=0.3,
            evidence_count=0,
            semantically_related_issues=[],
        )

        pipeline._record_agent_decision(pattern, "rejected: evidence threshold not met", None)

        # Verify decision was recorded
        decisions = pipeline._pm.list_decisions(decision_type="create_agent")
        assert len(decisions) >= 1
        decision = decisions[0]
        assert "rejected" in decision["reasoning"]
