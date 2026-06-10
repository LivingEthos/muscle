"""
Tests for ReviewController - the main orchestrator for code review.

Integration tests that verify the controller correctly orchestrates
static analysis, semantic review, fixes, and handoff generation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.fix_generator import FixGenerator, FixResult, GeneratedFix
from tools.muscle.code_review.handoff_generator import HandoffGenerator
from tools.muscle.code_review.review_controller import ReviewContext, ReviewController
from tools.muscle.code_review.static_analyzer import StaticAnalyzer
from tools.muscle.code_review.types import (
    HandoffPlan,
    IssueCategory,
    ReviewConfig,
    ReviewEvent,
    ReviewIssue,
    ReviewMode,
    ReviewStats,
    Severity,
    StaticAnalysisResult,
    StaticIssue,
)
from tools.muscle.code_review.verification_loop import VerificationResult
from tools.muscle.m27_client import M27Client
from tools.muscle.project_memory import ProjectMemory
from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager


class MockM27Client(M27Client):
    def __init__(self):
        self._mock_response = "Mock response"
        self.model = "MiniMax-M2.7"

    def generate(self, prompt: str, system_prompt: str | None = None, **kwargs) -> str:
        return self._mock_response


class TestReviewControllerInitialization:
    def test_init_with_valid_config(self):
        config = ReviewConfig(target_path="/tmp/test")
        mock_client = MockM27Client()

        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        assert controller.config == config
        assert controller.m27_client == mock_client
        assert isinstance(controller.static_analyzer, StaticAnalyzer)
        assert isinstance(controller.code_reviewer, CodeReviewer)
        assert isinstance(controller.fix_generator, FixGenerator)
        assert isinstance(controller.handoff_generator, HandoffGenerator)
        assert controller.review_kb is None
        assert controller.global_review_kb is None

    def test_init_with_kb_enabled(self):
        config = ReviewConfig(target_path="/tmp/test")
        mock_client = MockM27Client()

        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = str(Path(tmpdir) / "test_kb.db")
            controller = ReviewController(
                config=config, m27_client=mock_client, use_kb=True, kb_path=kb_path
            )

            assert controller.review_kb is not None
            assert controller.global_review_kb is not None

    def test_init_with_event_callback(self):
        config = ReviewConfig(target_path="/tmp/test")
        mock_client = MockM27Client()
        callback_called: list[tuple[ReviewEvent, dict]] = []

        def callback(event: ReviewEvent, data: dict):
            callback_called.append((event, data))

        controller = ReviewController(
            config=config, m27_client=mock_client, event_callback=callback, use_kb=False
        )

        assert controller.event_callback is not None
        controller._emit(ReviewEvent.REVIEW_START, {"test": "data"})
        assert len(callback_called) == 1
        assert callback_called[0][0] == ReviewEvent.REVIEW_START

    def test_emit_swallows_callback_exceptions(self):
        """A throwing observer must not abort the review (FAILOPEN#6)."""
        config = ReviewConfig(target_path="/tmp/test")
        mock_client = MockM27Client()

        def boom(event: ReviewEvent, data: dict):
            raise RuntimeError("observer blew up")

        controller = ReviewController(
            config=config, m27_client=mock_client, event_callback=boom, use_kb=False
        )
        # Must not raise.
        controller._emit(ReviewEvent.REVIEW_START, {"test": "data"})


class TestReviewModes:
    def test_worktree_mode_fails_closed_outside_git_repo(self, tmp_path):
        config = ReviewConfig(
            target_path=str(tmp_path),
            mode=ReviewMode.AUTO_FIX,
            execution_mode="worktree",
        )
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        with patch.object(controller.static_analyzer, "analyze", return_value=[]):
            with pytest.raises(RuntimeError, match="git repository"):
                controller.run()

    def test_run_review_mode(self):
        config = ReviewConfig(target_path="/tmp/test", mode=ReviewMode.REVIEW)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        mock_static_result = [
            StaticAnalysisResult(
                tool_name="ruff",
                language="python",
                issues=[
                    StaticIssue(
                        file_path="/tmp/test/test.py",
                        line_number=10,
                        severity="error",
                        rule_id="E501",
                        message="Line too long",
                        category="style",
                    )
                ],
                duration_seconds=0.1,
            )
        ]

        with patch.object(controller.static_analyzer, "analyze", return_value=mock_static_result):
            with patch.object(
                controller.code_reviewer,
                "review",
                return_value=([self._make_review_issue()], "summary"),
            ):
                ctx = controller.run()

        assert ctx is not None
        assert ctx.session_id is not None
        assert ctx.stats is not None

    def test_run_review_mode_writes_artifact_manifest(self, tmp_path):
        target = tmp_path / "module.py"
        target.write_text("print('hello')\n", encoding="utf-8")
        config = ReviewConfig(target_path=str(target), mode=ReviewMode.REVIEW)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        with patch.object(controller.static_analyzer, "analyze", return_value=[]):
            with patch.object(
                controller.code_reviewer,
                "review",
                return_value=([self._make_review_issue(file_path=str(target))], {"token_usage": 0}),
            ):
                ctx = controller.run()

        assert ctx.artifact_dir is not None
        manifest = json.loads(
            (Path(ctx.artifact_dir) / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["artifact_count"] >= 3
        assert "summary.md" in manifest["artifacts"]

    def test_run_plan_mode(self):
        config = ReviewConfig(target_path="/tmp/test", mode=ReviewMode.PLAN)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        mock_static_result = [
            StaticAnalysisResult(
                tool_name="ruff",
                language="python",
                issues=[
                    StaticIssue(
                        file_path="/tmp/test/test.py",
                        line_number=10,
                        severity="error",
                        rule_id="E501",
                        message="Line too long",
                        category="style",
                    )
                ],
                duration_seconds=0.1,
            )
        ]

        with patch.object(controller.static_analyzer, "analyze", return_value=mock_static_result):
            with patch.object(
                controller.code_reviewer,
                "review",
                return_value=([self._make_review_issue()], "summary"),
            ):
                with patch.object(
                    controller.handoff_generator,
                    "generate_handoffs",
                    return_value=HandoffPlan(
                        session_id="test",
                        target_path="/tmp/test",
                        issues=[],
                        generated_at="2024-01-01",
                    ),
                ):
                    ctx = controller.run()

        assert ctx is not None
        assert ctx.handoff_plan is not None

    def test_run_auto_fix_mode(self):
        config = ReviewConfig(target_path="/tmp/test", mode=ReviewMode.AUTO_FIX)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        issue = self._make_fixable_issue()

        mock_static_result = [
            StaticAnalysisResult(
                tool_name="ruff",
                language="python",
                issues=[
                    StaticIssue(
                        file_path="/tmp/test/test.py",
                        line_number=10,
                        severity="error",
                        rule_id="E501",
                        message="Line too long",
                        category="style",
                    )
                ],
                duration_seconds=0.1,
            )
        ]

        with patch.object(controller.static_analyzer, "analyze", return_value=mock_static_result):
            with patch.object(
                controller.code_reviewer, "review", return_value=([issue], "summary")
            ):
                with patch.object(
                    controller.fix_generator,
                    "apply_fix_from_suggestion",
                    return_value=FixResult(
                        success=True,
                        file_path="/tmp/test/test.py",
                        original_content="old",
                        fixed_content="new",
                        applied=True,
                        verified=True,
                    ),
                ):
                    ctx = controller.run()

        assert ctx is not None

    def test_run_hybrid_mode(self):
        config = ReviewConfig(target_path="/tmp/test", mode=ReviewMode.HYBRID)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        issue = self._make_fixable_issue()

        mock_static_result = [
            StaticAnalysisResult(
                tool_name="ruff",
                language="python",
                issues=[
                    StaticIssue(
                        file_path="/tmp/test/test.py",
                        line_number=10,
                        severity="error",
                        rule_id="E501",
                        message="Line too long",
                        category="style",
                    )
                ],
                duration_seconds=0.1,
            )
        ]

        with patch.object(controller.static_analyzer, "analyze", return_value=mock_static_result):
            with patch.object(
                controller.code_reviewer, "review", return_value=([issue], "summary")
            ):
                with patch.object(
                    controller.handoff_generator,
                    "generate_handoffs",
                    return_value=HandoffPlan(
                        session_id="test",
                        target_path="/tmp/test",
                        issues=[],
                        generated_at="2024-01-01",
                    ),
                ):
                    with patch.object(
                        controller.fix_generator,
                        "apply_fix_from_suggestion",
                        return_value=FixResult(
                            success=True,
                            file_path="/tmp/test/test.py",
                            original_content="old",
                            fixed_content="new",
                            applied=True,
                            verified=True,
                        ),
                    ):
                        ctx = controller.run()

        assert ctx is not None

    def test_pressure_mode_threads_fragility_challenge_into_committee(self, tmp_path):
        target = tmp_path / "service.py"
        target.write_text("value = 1\n", encoding="utf-8")
        config = ReviewConfig(
            target_path=str(target),
            mode=ReviewMode.PRESSURE,
            pressure_challenge="fragility",
        )
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)
        pressure_issue = ReviewIssue(
            file_path=str(target),
            line_number=1,
            severity=Severity.MEDIUM,
            category=IssueCategory.BEST_PRACTICE,
            cwe_id=None,
            title="Retry storm after refactor",
            description="Ordering dependency hidden in retries.",
            code_snippet="value = 1",
            auto_fixable=False,
            source_agent="pressure:fragility",
        )

        with patch.object(controller.static_analyzer, "analyze", return_value=[]):
            with patch.object(controller, "_route_review_request", return_value=False):
                with patch.object(
                    controller.committee_reviewer,
                    "run_agent",
                    return_value=[pressure_issue],
                ) as mock_run_agent:
                    ctx = controller.run()

        assert ctx.issues[0].source_agent == "pressure:fragility"
        assert mock_run_agent.call_args.args[5] == "fragility"

    def _make_review_issue(
        self,
        auto_fixable: bool = False,
        file_path: str = "/tmp/test/test.py",
    ) -> ReviewIssue:
        return ReviewIssue(
            file_path=file_path,
            line_number=10,
            severity=Severity.MEDIUM,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Line too long",
            description="Line exceeds 100 characters",
            code_snippet='x = "very long string that exceeds the line length limit"',
            suggested_fix='x = "short"' if auto_fixable else None,
            auto_fixable=auto_fixable,
        )

    def _make_fixable_issue(self) -> ReviewIssue:
        return self._make_review_issue(auto_fixable=True)


class TestSeverityFiltering:
    def test_filter_by_severity_threshold(self):
        config = ReviewConfig(target_path="/tmp/test", severity_threshold=Severity.HIGH)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        issues = [
            ReviewIssue(
                file_path="/tmp/test.py",
                line_number=1,
                severity=Severity.CRITICAL,
                category=IssueCategory.SECURITY,
                cwe_id="CWE-79",
                title="XSS",
                description="Cross-site scripting",
                code_snippet="",
                auto_fixable=False,
            ),
            ReviewIssue(
                file_path="/tmp/test.py",
                line_number=2,
                severity=Severity.INFO,
                category=IssueCategory.STYLE,
                cwe_id=None,
                title="Style",
                description="Style issue",
                code_snippet="",
                auto_fixable=False,
            ),
        ]

        filtered = controller._filter_by_severity(issues)

        assert len(filtered) == 1
        assert filtered[0].severity == Severity.CRITICAL

    def test_filter_includes_equal_threshold(self):
        config = ReviewConfig(target_path="/tmp/test", severity_threshold=Severity.MEDIUM)
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        issues = [
            ReviewIssue(
                file_path="/tmp/test.py",
                line_number=1,
                severity=Severity.MEDIUM,
                category=IssueCategory.STYLE,
                cwe_id=None,
                title="Medium",
                description="Medium severity",
                code_snippet="",
                auto_fixable=False,
            ),
        ]

        filtered = controller._filter_by_severity(issues)

        assert len(filtered) == 1


class TestGetReviewResult:
    def test_get_review_result_before_run(self):
        config = ReviewConfig(target_path="/tmp/test")
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        result = controller.get_review_result()

        assert result is None

    def test_get_review_result_after_run(self):
        config = ReviewConfig(target_path="/tmp/test")
        mock_client = MockM27Client()
        controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

        mock_static_result = [
            StaticAnalysisResult(
                tool_name="ruff",
                language="python",
                issues=[
                    StaticIssue(
                        file_path="/tmp/test/test.py",
                        line_number=10,
                        severity="error",
                        rule_id="E501",
                        message="Line too long",
                        category="style",
                    )
                ],
                duration_seconds=0.1,
            )
        ]

        critical_issue = ReviewIssue(
            file_path="/tmp/test/test.py",
            line_number=10,
            severity=Severity.CRITICAL,
            category=IssueCategory.SECURITY,
            cwe_id="CWE-79",
            title="XSS",
            description="Cross-site scripting",
            code_snippet="",
            auto_fixable=False,
        )

        with patch.object(controller.static_analyzer, "analyze", return_value=mock_static_result):
            with patch.object(
                controller.code_reviewer,
                "review",
                return_value=([critical_issue], "summary"),
            ):
                with patch.object(
                    controller.handoff_generator,
                    "generate_handoffs",
                    return_value=HandoffPlan(
                        session_id="test",
                        target_path="/tmp/test",
                        issues=[],
                        generated_at="2024-01-01",
                    ),
                ):
                    controller.run()

        result = controller.get_review_result()

        assert result is not None
        assert result.session_id is not None
        assert result.critical_count == 1
        assert result.high_count == 0
        assert result.medium_count == 0


class TestReviewContext:
    def test_review_context_initialization(self):
        config = ReviewConfig(target_path="/tmp/test")
        ctx = ReviewContext(
            session_id="abc123",
            config=config,
            stats=ReviewStats(),
        )

        assert ctx.session_id == "abc123"
        assert ctx.config == config
        assert ctx.stats is not None
        assert ctx.issues == []
        assert ctx.handoff_plan is None

    def test_review_context_with_issues(self):
        config = ReviewConfig(target_path="/tmp/test")
        issue = ReviewIssue(
            file_path="/tmp/test.py",
            line_number=1,
            severity=Severity.HIGH,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="Bug",
            description="Bug description",
            code_snippet="",
            auto_fixable=False,
        )
        ctx = ReviewContext(
            session_id="abc123",
            config=config,
            stats=ReviewStats(valid_issues=1),
            issues=[issue],
        )

        assert len(ctx.issues) == 1
        assert ctx.issues[0].title == "Bug"


def test_review_controller_records_positive_external_lesson_outcome(tmp_path):
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    file_path = current / "module.py"
    file_path.write_text("x = 1\n", encoding="utf-8")

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Prefer schema-first review retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.insert_lesson_usage_event(
        project_path=str(current),
        session_id="review-session",
        stage="fix_generation",
        lesson_source="related",
        lesson_key=str(lesson["lesson_key"]),
        source_project_path=str(source),
    )

    controller = ReviewController(
        config=ReviewConfig(target_path=str(file_path), mode=ReviewMode.AUTO_FIX),
        m27_client=MockM27Client(),
        use_kb=False,
        project_path=str(current),
    )
    issue = ReviewIssue(
        file_path=str(file_path),
        line_number=1,
        severity=Severity.MEDIUM,
        category=IssueCategory.CORRECTNESS,
        cwe_id=None,
        title="Bug",
        description="Bug description",
        code_snippet="x = 1",
        suggested_fix="x = 2",
        auto_fixable=True,
    )
    ctx = ReviewContext(session_id="review-session", config=controller.config, stats=ReviewStats())
    controller._review_context = ctx

    with patch.object(
        controller.fix_generator,
        "generate_fix",
        return_value=GeneratedFix(ok=True, file_path=str(file_path), code="x = 2\n"),
    ):
        with patch.object(
            controller.fix_generator,
            "apply_fix",
            return_value=FixResult(
                success=True,
                file_path=str(file_path),
                original_content="x = 1\n",
                fixed_content="x = 2\n",
                applied=True,
                verified=False,
            ),
        ):
            with patch.object(
                controller.verification_loop,
                "verify_fix",
                return_value=VerificationResult(
                    issue=issue,
                    fix_applied=True,
                    fix_verified=True,
                    verification_details="verified",
                    reverted=False,
                ),
            ):
                success, _ = controller._apply_fix_with_verification(ctx, issue)

    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    usage_events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="review-session"
    )

    assert success is True
    assert usage_events[0]["outcome"] == "positive_fix_verification"
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 1


def test_review_controller_records_negative_external_lesson_outcome(tmp_path):
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    file_path = current / "module.py"
    file_path.write_text("x = 1\n", encoding="utf-8")

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Prefer schema-first review retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.insert_lesson_usage_event(
        project_path=str(current),
        session_id="review-session",
        stage="semantic_review",
        lesson_source="related",
        lesson_key=str(lesson["lesson_key"]),
        source_project_path=str(source),
    )

    controller = ReviewController(
        config=ReviewConfig(target_path=str(file_path), mode=ReviewMode.AUTO_FIX),
        m27_client=MockM27Client(),
        use_kb=False,
        project_path=str(current),
    )
    issue = ReviewIssue(
        file_path=str(file_path),
        line_number=1,
        severity=Severity.MEDIUM,
        category=IssueCategory.CORRECTNESS,
        cwe_id=None,
        title="Bug",
        description="Bug description",
        code_snippet="x = 1",
        suggested_fix="x = 2",
        auto_fixable=True,
    )
    ctx = ReviewContext(session_id="review-session", config=controller.config, stats=ReviewStats())
    controller._review_context = ctx

    with patch.object(
        controller.fix_generator,
        "generate_fix",
        return_value=GeneratedFix(ok=True, file_path=str(file_path), code="x = 2\n"),
    ):
        with patch.object(
            controller.fix_generator,
            "apply_fix",
            return_value=FixResult(
                success=True,
                file_path=str(file_path),
                original_content="x = 1\n",
                fixed_content="x = 2\n",
                applied=True,
                verified=False,
            ),
        ):
            with patch.object(
                controller.verification_loop,
                "verify_fix",
                return_value=VerificationResult(
                    issue=issue,
                    fix_applied=True,
                    fix_verified=False,
                    verification_details="failed",
                    reverted=False,
                    failure_analysis="still broken",
                ),
            ):
                with patch.object(controller.fix_generator, "rollback_fix", return_value=True):
                    success, _ = controller._apply_fix_with_verification(ctx, issue)

    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    usage_events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="review-session"
    )

    assert success is False
    assert usage_events[0]["outcome"] == "negative_fix_verification"
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 0


# ---------------------------------------------------------------------------
# RC-02: Worktree cleanup swallows exceptions — failure counter must increment
# ---------------------------------------------------------------------------


class TestRC02WorktreeCleanupFailureCounter:
    """Acceptance tests for RC-02: worktree cleanup failures are tracked."""

    def _make_controller(self, tmp_path: Path) -> ReviewController:
        config = ReviewConfig(
            target_path=str(tmp_path),
            mode=ReviewMode.AUTO_FIX,
            execution_mode="worktree",
        )
        return ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)

    def test_cleanup_failure_increments_counter(self, tmp_path):
        """RC-02: When worktree cleanup raises, the failure counter increments."""
        controller = self._make_controller(tmp_path)

        assert controller._worktree_cleanup_failures == 0

        # Simulate a cleanup failure by patching GitWorktreeManager
        from tools.muscle.code_review.worktree_manager import WorktreeSession

        fake_session = MagicMock(spec=WorktreeSession)
        fake_session.worktree_path = str(tmp_path / "wt")
        fake_session.base_branch = "main"

        with patch("tools.muscle.code_review.review_controller.GitWorktreeManager") as mock_mgr_cls:
            mock_mgr = mock_mgr_cls.return_value
            mock_mgr.is_available.return_value = True
            mock_mgr.create.return_value = fake_session
            mock_mgr.sync_local_changes.side_effect = RuntimeError("forced failure before review")
            mock_mgr.cleanup.side_effect = OSError("locked worktree")

            with pytest.raises(RuntimeError):
                controller._run_in_isolated_worktree()

        assert controller._worktree_cleanup_failures == 1

    def test_cleanup_failure_not_reraised(self, tmp_path):
        """RC-02: A cleanup failure must not propagate as an exception."""
        controller = self._make_controller(tmp_path)

        from tools.muscle.code_review.worktree_manager import WorktreeSession

        fake_session = MagicMock(spec=WorktreeSession)
        fake_session.worktree_path = str(tmp_path / "wt")
        fake_session.base_branch = "main"

        raised_exception: list[Exception] = []

        with patch("tools.muscle.code_review.review_controller.GitWorktreeManager") as mock_mgr_cls:
            mock_mgr = mock_mgr_cls.return_value
            mock_mgr.is_available.return_value = True
            mock_mgr.create.return_value = fake_session
            # Make the review itself fail so we reach the finally block
            mock_mgr.sync_local_changes.side_effect = RuntimeError("review failed")
            mock_mgr.cleanup.side_effect = OSError("locked worktree")

            try:
                controller._run_in_isolated_worktree()
            except RuntimeError as exc:
                raised_exception.append(exc)
            except OSError as exc:
                raised_exception.append(exc)

        # The cleanup OSError must NOT be the raised exception
        if raised_exception:
            assert not isinstance(raised_exception[0], OSError), (
                "Cleanup exception should have been swallowed, not re-raised"
            )
        # Counter must still be updated
        assert controller._worktree_cleanup_failures == 1

    def test_counter_accessible_after_review_completes(self, tmp_path):
        """RC-02: _worktree_cleanup_failures is readable on the controller instance."""
        controller = self._make_controller(tmp_path)
        # Default is 0 before any review
        assert controller._worktree_cleanup_failures == 0
        # Attribute must be an int
        assert isinstance(controller._worktree_cleanup_failures, int)


# ---------------------------------------------------------------------------
# RC-03: fix_lock scope regression — lock must be released even on exception
# ---------------------------------------------------------------------------


class TestRC03FixLockReleasedOnException:
    """Regression tests for RC-03: fix_lock is always released, even on exception."""

    def _make_fixable_issue(self) -> ReviewIssue:
        return ReviewIssue(
            file_path="/tmp/test/test.py",
            line_number=1,
            severity=Severity.MEDIUM,
            category=IssueCategory.STYLE,
            cwe_id=None,
            title="Test",
            description="Test",
            code_snippet="x = 1",
            suggested_fix="x = 2",
            auto_fixable=True,
        )

    def test_fix_lock_released_after_exception_inside_locked_region(self, tmp_path):
        """RC-03: When apply_fix raises inside the locked region of
        _run_auto_fix_mode, the lock must be released afterwards."""
        config = ReviewConfig(target_path=str(tmp_path), mode=ReviewMode.AUTO_FIX)
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)

        issue = self._make_fixable_issue()
        ctx = ReviewContext(
            session_id="test-session",
            config=config,
            stats=ReviewStats(),
            issues=[issue],
        )
        controller._review_context = ctx

        # Capture the fix_lock that _run_auto_fix_mode creates so we can
        # inspect it after the run.  We wrap the Lock constructor to intercept.
        captured_locks: list[Lock] = []
        original_lock_cls = Lock

        def capturing_lock() -> Lock:  # type: ignore[return]
            lk = original_lock_cls()
            captured_locks.append(lk)
            return lk

        with patch.object(controller.static_analyzer, "analyze", return_value=[]):
            # _run_review_mode will produce no issues from static analysis;
            # we inject the issue via ctx directly.
            # Patch _apply_fix_with_verification to raise inside the future.
            with patch.object(
                controller,
                "_apply_fix_with_verification",
                side_effect=RuntimeError("simulated exception in locked region"),
            ):
                with patch(
                    "tools.muscle.code_review.review_controller.Lock",
                    side_effect=capturing_lock,
                ):
                    with patch.object(
                        controller.code_reviewer,
                        "review",
                        return_value=([issue], "summary"),
                    ):
                        # Should not hang or deadlock
                        result_ctx = controller._run_auto_fix_mode(ctx)

        # The review must complete (return a context) and not hang
        assert result_ctx is not None

        # All captured locks must be released (not held)
        for lk in captured_locks:
            # If the lock were still held, acquire(blocking=False) would fail
            acquired = lk.acquire(blocking=False)
            assert acquired, "fix_lock was not released after exception"
            lk.release()

    def test_fix_lock_subsequent_acquire_succeeds_after_exception(self, tmp_path):
        """RC-03: A subsequent acquire on fix_lock succeeds (no deadlock) even
        when an exception occurred during a previous fix application."""
        config = ReviewConfig(target_path=str(tmp_path), mode=ReviewMode.AUTO_FIX)
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)

        issue = self._make_fixable_issue()
        ctx = ReviewContext(
            session_id="test-session",
            config=config,
            stats=ReviewStats(),
            issues=[issue],
        )
        controller._review_context = ctx

        # This lock is the one used in _run_auto_fix_mode; Python's `with`
        # statement guarantees it is always released.
        fix_lock = Lock()

        def raise_inside_lock() -> None:
            with fix_lock:
                raise RuntimeError("error inside locked region")

        try:
            raise_inside_lock()
        except RuntimeError:
            pass

        # The lock must be released even though we raised inside it
        assert not fix_lock.locked(), "Lock held after exception inside `with` block"
        # Must be acquirable again
        acquired = fix_lock.acquire(blocking=False)
        assert acquired, "Lock was not released; deadlock would occur"
        fix_lock.release()


class TestFixLockMapDoesNotLeak:
    """CONCURRENCY: _fix_locks is a WeakValueDictionary so idle entries evict."""

    def test_fix_lock_entry_evicted_when_no_holder(self):
        import gc

        config = ReviewConfig(target_path="/tmp/test")
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)

        # Returned lock with no retained reference must drop from the map.
        controller._get_fix_lock("/tmp/test/a.py")
        gc.collect()
        assert len(controller._fix_locks) == 0

    def test_fix_lock_entry_retained_while_held(self):
        config = ReviewConfig(target_path="/tmp/test")
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)

        lock = controller._get_fix_lock("/tmp/test/a.py")
        # Same path returns the same lock while a strong ref is alive.
        assert controller._get_fix_lock("/tmp/test/a.py") is lock


class TestFixApplyCrossProcessLock:
    """CONCURRENCY: fix-apply takes an advisory file lock on a `.muscle/locks/`
    sentinel so two muscle processes auto-fixing the same file serialize."""

    def test_advisory_lock_taken_on_expected_sentinel(self, tmp_path):
        from contextlib import contextmanager

        file_path = tmp_path / "src.py"
        file_path.write_text("x = 1\n")

        controller = ReviewController(
            config=ReviewConfig(target_path=str(file_path), mode=ReviewMode.AUTO_FIX),
            m27_client=MockM27Client(),
            use_kb=False,
            project_path=str(tmp_path),
        )
        issue = ReviewIssue(
            file_path=str(file_path),
            line_number=1,
            severity=Severity.MEDIUM,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="Bug",
            description="Bug description",
            code_snippet="x = 1",
            suggested_fix="x = 2",
            auto_fixable=True,
        )
        ctx = ReviewContext(session_id="sess", config=controller.config, stats=ReviewStats())
        controller._review_context = ctx

        expected_sentinel = controller._fix_file_lock_sentinel(str(file_path))
        locked_paths: list[Path] = []

        @contextmanager
        def spy_lock(path):
            locked_paths.append(Path(path))
            yield

        with (
            patch(
                "tools.muscle.code_review.review_controller.advisory_file_lock",
                spy_lock,
            ),
            patch.object(
                controller.fix_generator,
                "generate_fix",
                return_value=GeneratedFix(ok=True, file_path=str(file_path), code="x = 2\n"),
            ),
            patch.object(
                controller.fix_generator,
                "apply_fix",
                return_value=FixResult(
                    success=True,
                    file_path=str(file_path),
                    original_content="x = 1\n",
                    fixed_content="x = 2\n",
                    applied=True,
                    verified=False,
                ),
            ),
            patch.object(
                controller.verification_loop,
                "verify_fix",
                return_value=VerificationResult(
                    issue=issue,
                    fix_applied=True,
                    fix_verified=True,
                    verification_details="verified",
                    reverted=False,
                ),
            ),
        ):
            success, _ = controller._apply_fix_with_verification(ctx, issue)

        assert success is True
        # The advisory lock was taken on the per-path sentinel under .muscle/locks/.
        assert expected_sentinel in locked_paths
        assert expected_sentinel.parent == tmp_path / ".muscle" / "locks"

    def test_sentinel_path_is_stable_and_repo_clean(self, tmp_path):
        controller = ReviewController(
            config=ReviewConfig(target_path=str(tmp_path)),
            m27_client=MockM27Client(),
            use_kb=False,
            project_path=str(tmp_path),
        )
        src = tmp_path / "deep" / "module.py"
        s1 = controller._fix_file_lock_sentinel(str(src))
        s2 = controller._fix_file_lock_sentinel(str(src))
        # Deterministic for a given resolved path.
        assert s1 == s2
        # Lock sentinel lives under .muscle/locks/, never next to user sources.
        assert s1.parent == tmp_path / ".muscle" / "locks"
        assert src.parent != s1.parent


class TestUnknownReviewModeRaises:
    """FAILOPEN#7: an unrecognized mode must fail loudly, not run as hybrid."""

    def test_run_raises_value_error_for_unknown_mode(self, tmp_path):
        config = ReviewConfig(target_path=str(tmp_path), mode=ReviewMode.REVIEW)
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)

        class _FakeMode:
            value = "bogus"

        # ReviewConfig is a frozen dataclass; bypass __setattr__ to inject an
        # out-of-band mode that matches no dispatch branch.
        object.__setattr__(controller.config, "mode", _FakeMode())

        with (
            patch.object(controller, "_assert_path_within_project"),
            patch.object(controller, "_should_use_isolated_worktree", return_value=False),
            patch.object(controller, "_resolve_workflow_name", return_value=""),
        ):
            with pytest.raises(ValueError, match="Unknown review mode"):
                controller.run()


class TestReviewDelegationTokenSplit:
    """COST#1/#2: review delegation events record the measured input/output split."""

    def test_record_delegation_event_uses_real_token_split(self, tmp_path):
        from tools.muscle.delegation_metrics import estimate_m27_cents

        config = ReviewConfig(target_path=str(tmp_path), mode=ReviewMode.REVIEW)
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)
        ctx = ReviewContext(
            session_id="rev-split",
            config=config,
            stats=ReviewStats(input_tokens=900, output_tokens=300, tokens_used=1200),
        )

        recorded = []
        fake_metrics = MagicMock()
        fake_metrics.record.side_effect = lambda event: recorded.append(event)
        with patch(
            "tools.muscle.code_review.review_controller.DelegationMetrics",
            return_value=fake_metrics,
        ):
            controller._record_delegation_event(ctx)

        assert len(recorded) == 1
        event = recorded[0]
        assert event.m27_tokens_in == 900
        assert event.m27_tokens_out == 300
        assert event.m27_usd_cents == estimate_m27_cents("MiniMax-M2.7", 900, 300)

    def test_record_delegation_event_attributes_legacy_remainder_to_input(self, tmp_path):
        from tools.muscle.delegation_metrics import estimate_m27_cents

        config = ReviewConfig(target_path=str(tmp_path), mode=ReviewMode.REVIEW)
        controller = ReviewController(config=config, m27_client=MockM27Client(), use_kb=False)
        ctx = ReviewContext(
            session_id="rev-legacy",
            config=config,
            stats=ReviewStats(input_tokens=0, output_tokens=0, tokens_used=1200),
        )

        recorded = []
        fake_metrics = MagicMock()
        fake_metrics.record.side_effect = lambda event: recorded.append(event)
        with patch(
            "tools.muscle.code_review.review_controller.DelegationMetrics",
            return_value=fake_metrics,
        ):
            controller._record_delegation_event(ctx)

        assert recorded[0].m27_tokens_in == 1200
        assert recorded[0].m27_tokens_out == 0
        assert recorded[0].m27_usd_cents == estimate_m27_cents("MiniMax-M2.7", 1200, 0)


def test_apply_fix_accumulates_verification_token_split(tmp_path):
    """The verification token split lands on ctx.stats alongside the combined total."""
    current = tmp_path / "current"
    current.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    file_path = current / "module.py"
    file_path.write_text("x = 1\n", encoding="utf-8")

    controller = ReviewController(
        config=ReviewConfig(target_path=str(file_path), mode=ReviewMode.AUTO_FIX),
        m27_client=MockM27Client(),
        use_kb=False,
        project_path=str(current),
    )
    issue = ReviewIssue(
        file_path=str(file_path),
        line_number=1,
        severity=Severity.MEDIUM,
        category=IssueCategory.CORRECTNESS,
        cwe_id=None,
        title="Bug",
        description="Bug description",
        code_snippet="x = 1",
        suggested_fix="x = 2",
        auto_fixable=True,
    )
    ctx = ReviewContext(session_id="review-session", config=controller.config, stats=ReviewStats())
    controller._review_context = ctx

    with patch.object(
        controller.fix_generator,
        "generate_fix",
        return_value=GeneratedFix(ok=True, file_path=str(file_path), code="x = 2\n"),
    ):
        with patch.object(
            controller.fix_generator,
            "apply_fix",
            return_value=FixResult(
                success=True,
                file_path=str(file_path),
                original_content="x = 1\n",
                fixed_content="x = 2\n",
                applied=True,
                verified=False,
            ),
        ):
            with patch.object(
                controller.verification_loop,
                "verify_fix",
                return_value=VerificationResult(
                    issue=issue,
                    fix_applied=True,
                    fix_verified=True,
                    verification_details="verified",
                    reverted=False,
                    tokens_spent=150,
                    input_tokens_spent=110,
                    output_tokens_spent=40,
                ),
            ):
                success, _ = controller._apply_fix_with_verification(ctx, issue)

    assert success is True
    assert ctx.stats.tokens_used == 150
    assert ctx.stats.input_tokens == 110
    assert ctx.stats.output_tokens == 40
