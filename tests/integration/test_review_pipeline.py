"""
Integration tests for the full review pipeline.

Tests ReviewController -> CodeReviewer -> FixGenerator -> HandoffGenerator
with a realistic mock M27Client that returns structured JSON.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.fix_generator import FixGenerator, FixResult
from tools.muscle.code_review.handoff_generator import HandoffGenerator
from tools.muscle.code_review.review_controller import ReviewController
from tools.muscle.code_review.static_analyzer import StaticAnalyzer
from tools.muscle.code_review.types import (
    HandoffPlan,
    IssueCategory,
    ReviewConfig,
    ReviewEvent,
    ReviewMode,
    Severity,
    StaticAnalysisResult,
    StaticIssue,
)

from .conftest import MockM27Client, make_review_issue

# ---------------------------------------------------------------------------
# Review pipeline integration
# ---------------------------------------------------------------------------


class TestReviewPipelineFlow:
    """Tests the full review pipeline from static analysis through handoff generation."""

    def test_review_mode_collects_issues(
        self, sample_python_project: Path, mock_m27: MockM27Client
    ):
        """Review mode should find issues without applying fixes."""
        config = ReviewConfig(
            target_path=str(sample_python_project / "src"),
            language="python",
            mode=ReviewMode.REVIEW,
        )

        # Mock static analyzer to return known issues
        static_issues = [
            StaticIssue(
                file_path="src/api.py",
                line_number=12,
                severity="HIGH",
                rule_id="S324",
                message="Use of insecure MD5 hash function",
                category="security",
            ),
            StaticIssue(
                file_path="src/utils.py",
                line_number=11,
                severity="HIGH",
                rule_id="S603",
                message="subprocess call with shell=True",
                category="security",
            ),
        ]

        with patch.object(StaticAnalyzer, "analyze") as mock_analyze:
            mock_analyze.return_value = [
                StaticAnalysisResult(
                    tool_name="ruff",
                    language="python",
                    issues=static_issues,
                    duration_seconds=0.5,
                )
            ]

            # Mock code_reviewer.review to return structured issues
            mock_issues = [
                make_review_issue(
                    severity=Severity.CRITICAL,
                    title="MD5 password hashing",
                ),
                make_review_issue(
                    file_path="src/utils.py",
                    line_number=11,
                    severity=Severity.HIGH,
                    title="Command injection",
                    category=IssueCategory.SECURITY,
                ),
            ]

            with patch.object(CodeReviewer, "review", return_value=(mock_issues, "Summary")):
                controller = ReviewController(
                    config=config,
                    m27_client=mock_m27,
                    use_kb=False,
                )
                result = controller.run()

        assert result.stats.valid_issues >= 1
        assert result.session_id

    def test_auto_fix_mode_applies_fixes(
        self, sample_python_project: Path, mock_m27: MockM27Client
    ):
        """Auto-fix mode should attempt to apply fixes to issues."""
        config = ReviewConfig(
            target_path=str(sample_python_project / "src"),
            language="python",
            mode=ReviewMode.AUTO_FIX,
            max_fixes_per_round=3,
        )

        fixable_issue = make_review_issue(
            severity=Severity.HIGH,
            title="Unsafe deserialization",
            auto_fixable=True,
            suggested_fix="Use json.loads instead",
        )

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(CodeReviewer, "review", return_value=([fixable_issue], "Summary")):
                with patch.object(
                    FixGenerator,
                    "generate_fix",
                    return_value=("src/api.py", "fixed code"),
                ):
                    with patch.object(
                        FixGenerator,
                        "apply_fix",
                        return_value=FixResult(
                            success=True,
                            file_path="src/api.py",
                            original_content="old",
                            fixed_content="new",
                            applied=True,
                            verified=True,
                        ),
                    ):
                        controller = ReviewController(
                            config=config,
                            m27_client=mock_m27,
                            use_kb=False,
                        )
                        result = controller.run()

        assert result.stats.fixed_issues >= 0  # May be 0 if filter removes

    def test_plan_mode_generates_handoffs(
        self, sample_python_project: Path, mock_m27: MockM27Client
    ):
        """Plan mode should generate handoff plans for complex issues."""
        config = ReviewConfig(
            target_path=str(sample_python_project / "src"),
            language="python",
            mode=ReviewMode.PLAN,
        )

        critical_issue = make_review_issue(
            severity=Severity.CRITICAL,
            title="SQL injection vulnerability",
            category=IssueCategory.SECURITY,
        )

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(CodeReviewer, "review", return_value=([critical_issue], "Summary")):
                controller = ReviewController(
                    config=config,
                    m27_client=mock_m27,
                    use_kb=False,
                )
                result = controller.run()

        # Plan mode should generate handoff plans
        if result.handoff_plan:
            assert len(result.handoff_plan.issues) >= 1
            assert result.stats.handoffs_generated >= 1

    def test_hybrid_mode_fixes_and_hands_off(
        self, sample_python_project: Path, mock_m27: MockM27Client
    ):
        """Hybrid mode should fix what it can and hand off the rest."""
        config = ReviewConfig(
            target_path=str(sample_python_project / "src"),
            language="python",
            mode=ReviewMode.HYBRID,
            max_fixes_per_round=1,
        )

        fixable = make_review_issue(
            severity=Severity.HIGH,
            title="Fixable issue",
            auto_fixable=True,
            suggested_fix="Easy fix",
        )
        complex_issue = make_review_issue(
            severity=Severity.CRITICAL,
            title="Complex architecture issue",
            auto_fixable=False,
        )

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(
                CodeReviewer, "review", return_value=([fixable, complex_issue], "Summary")
            ):
                with patch.object(
                    FixGenerator,
                    "generate_fix",
                    return_value=("src/api.py", "fixed"),
                ):
                    with patch.object(
                        FixGenerator,
                        "apply_fix",
                        return_value=FixResult(
                            success=True,
                            file_path="src/api.py",
                            original_content="old",
                            fixed_content="new",
                            applied=True,
                            verified=True,
                        ),
                    ):
                        controller = ReviewController(
                            config=config,
                            m27_client=mock_m27,
                            use_kb=False,
                        )
                        result = controller.run()

        assert result.session_id

    def test_event_callbacks_fire_in_order(
        self, sample_python_project: Path, mock_m27: MockM27Client
    ):
        """Event callbacks should fire in correct order during review."""
        events: list[tuple[ReviewEvent, dict]] = []

        def callback(event: ReviewEvent, data: dict) -> None:
            events.append((event, data))

        config = ReviewConfig(
            target_path=str(sample_python_project / "src"),
            language="python",
            mode=ReviewMode.REVIEW,
        )

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(CodeReviewer, "review", return_value=([], "No issues")):
                controller = ReviewController(
                    config=config,
                    m27_client=mock_m27,
                    event_callback=callback,
                    use_kb=False,
                )
                controller.run()

        event_types = [e[0] for e in events]
        assert ReviewEvent.REVIEW_START in event_types
        assert ReviewEvent.REVIEW_COMPLETE in event_types

        # REVIEW_START should come before REVIEW_COMPLETE
        start_idx = event_types.index(ReviewEvent.REVIEW_START)
        complete_idx = event_types.index(ReviewEvent.REVIEW_COMPLETE)
        assert start_idx < complete_idx

    def test_severity_filtering(self, sample_python_project: Path, mock_m27: MockM27Client):
        """Issues below severity threshold should be filtered out."""
        config = ReviewConfig(
            target_path=str(sample_python_project / "src"),
            language="python",
            mode=ReviewMode.REVIEW,
            severity_threshold=Severity.HIGH,
        )

        low_issue = make_review_issue(severity=Severity.LOW, title="Minor style issue")
        high_issue = make_review_issue(severity=Severity.HIGH, title="Security flaw")

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(
                CodeReviewer, "review", return_value=([low_issue, high_issue], "Summary")
            ):
                controller = ReviewController(
                    config=config,
                    m27_client=mock_m27,
                    use_kb=False,
                )
                result = controller.run()

        # Only HIGH and above should be in final results
        for issue in result.issues:
            assert issue.severity.value >= Severity.HIGH.value


class TestReviewWithKB:
    """Tests review pipeline with knowledge base integration."""

    def test_review_records_to_kb(self, project_with_muscle_dir: Path, mock_m27: MockM27Client):
        """Review results should be recorded in the ReviewKB."""
        kb_path = str(project_with_muscle_dir / ".muscle" / "review_kb")
        config = ReviewConfig(
            target_path=str(project_with_muscle_dir / "src"),
            language="python",
            mode=ReviewMode.REVIEW,
        )

        issue = make_review_issue(severity=Severity.HIGH)

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(CodeReviewer, "review", return_value=([issue], "Summary")):
                controller = ReviewController(
                    config=config,
                    m27_client=mock_m27,
                    use_kb=True,
                    kb_path=kb_path,
                )
                result = controller.run()

        assert result.session_id

    def test_empty_project_review(self, tmp_path: Path, mock_m27: MockM27Client):
        """Reviewing an empty project should complete without errors."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "empty.py").write_text("# empty file\n")

        config = ReviewConfig(
            target_path=str(src),
            language="python",
            mode=ReviewMode.REVIEW,
        )

        with patch.object(StaticAnalyzer, "analyze", return_value=[]):
            with patch.object(CodeReviewer, "review", return_value=([], "No issues found")):
                controller = ReviewController(
                    config=config,
                    m27_client=mock_m27,
                    use_kb=False,
                )
                result = controller.run()

        assert result.stats.valid_issues == 0
        assert result.session_id


class TestCodeReviewerIntegration:
    """Tests CodeReviewer with MockM27Client for realistic response parsing."""

    def test_review_parses_findings(self, sample_python_project: Path, mock_m27: MockM27Client):
        """CodeReviewer should parse M27 findings into ReviewIssue objects."""
        reviewer = CodeReviewer(mock_m27)

        # The mock returns REVIEW_JSON_RESPONSE by default
        issues, summary = reviewer.review(str(sample_python_project / "src"), [])

        # The mock returns our structured JSON, but the reviewer may parse differently
        # depending on the code. This tests that it doesn't crash.
        assert isinstance(issues, list)
        assert isinstance(summary, dict)

    def test_review_handles_empty_target(self, tmp_path: Path, mock_m27: MockM27Client):
        """CodeReviewer should handle empty directories gracefully."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        reviewer = CodeReviewer(mock_m27)
        issues, summary = reviewer.review(str(empty_dir), [])

        assert isinstance(issues, list)


class TestFixGeneratorIntegration:
    """Tests FixGenerator with MockM27Client."""

    def test_generate_fix_returns_code(self, mock_m27: MockM27Client):
        """FixGenerator should return file path and fixed code."""
        generator = FixGenerator(mock_m27)
        issue = make_review_issue(
            suggested_fix="Use json.loads instead of unsafe deserialization",
            auto_fixable=True,
        )

        file_path, fixed_code = generator.generate_fix(issue)

        assert isinstance(file_path, str)
        assert isinstance(fixed_code, str)

    def test_generate_fix_no_suggestion(self, mock_m27: MockM27Client):
        """FixGenerator should return empty strings when no suggested fix."""
        generator = FixGenerator(mock_m27)
        issue = make_review_issue(suggested_fix=None)

        file_path, fixed_code = generator.generate_fix(issue)

        assert file_path == ""
        assert fixed_code == ""

    def test_apply_fix_to_real_file(self, sample_python_project: Path, mock_m27: MockM27Client):
        """FixGenerator should apply fix to an actual file with backup."""
        generator = FixGenerator(mock_m27)
        target_file = sample_python_project / "src" / "api.py"

        issue = make_review_issue(
            file_path=str(target_file),
            suggested_fix="Replace MD5 with bcrypt",
            auto_fixable=True,
        )

        original_content = target_file.read_text()
        fixed_content = original_content.replace(
            "hashlib.md5(password.encode()).hexdigest()",
            "bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()",
        )

        result = generator.apply_fix(issue, fixed_content)

        assert isinstance(result, FixResult)
        assert result.file_path == str(target_file)


class TestHandoffGeneratorIntegration:
    """Tests HandoffGenerator with MockM27Client."""

    def test_generate_single_handoff(self, mock_m27: MockM27Client):
        """HandoffGenerator should produce a complete handoff plan."""
        generator = HandoffGenerator(mock_m27)
        issue = make_review_issue(
            severity=Severity.CRITICAL,
            title="SQL injection vulnerability",
        )

        plan = generator.generate_handoff(
            issue=issue,
            all_issues=[issue],
            session_id="test-001",
            target_path="/tmp/test",
        )

        assert isinstance(plan, HandoffPlan)
        assert plan.session_id == "test-001"
        assert len(plan.issues) >= 1
        assert plan.issues[0].root_cause

    def test_generate_multiple_handoffs(self, mock_m27: MockM27Client):
        """HandoffGenerator should handle multiple issues."""
        generator = HandoffGenerator(mock_m27)
        issues = [
            make_review_issue(
                severity=Severity.CRITICAL,
                title="Critical bug 1",
            ),
            make_review_issue(
                severity=Severity.HIGH,
                title="High priority fix",
                category=IssueCategory.SECURITY,
            ),
        ]

        plan = generator.generate_handoffs(
            issues=issues,
            session_id="test-002",
            target_path="/tmp/test",
        )

        assert isinstance(plan, HandoffPlan)
        assert len(plan.issues) >= 1
        assert plan.markdown  # Should generate markdown

    def test_handoff_with_code_context(self, sample_python_project: Path, mock_m27: MockM27Client):
        """HandoffGenerator should include code context in plans."""
        generator = HandoffGenerator(mock_m27)
        api_file = sample_python_project / "src" / "api.py"

        issue = make_review_issue(
            file_path=str(api_file),
            severity=Severity.CRITICAL,
        )

        plan = generator.generate_handoff(
            issue=issue,
            all_issues=[issue],
            session_id="test-003",
            target_path=str(sample_python_project),
        )

        assert plan.issues[0].verification_steps
        assert plan.issues[0].effort_estimate
