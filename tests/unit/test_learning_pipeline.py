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
        from tools.muscle.code_review.learning_pipeline import LearningPipeline, ARCHIVE_VALIDATED_THRESHOLD

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
                mock_detector_cls.return_value = mock_detector

                count = pipeline._detect_and_generate_skills()

            assert count == 0

    def test_skill_generation_catches_exceptions(self):
        from tools.muscle.code_review.learning_pipeline import LearningPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = LearningPipeline(tmpdir)

            with patch(
                "tools.muscle.code_review.learning_pipeline.PatternDetector"
            ) as mock_detector_cls:
                mock_detector_cls.side_effect = Exception("DB error")

                count = pipeline._detect_and_generate_skills()

            assert count == 0

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
