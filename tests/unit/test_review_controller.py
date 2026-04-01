"""
Tests for ReviewController - the main orchestrator for code review.

Integration tests that verify the controller correctly orchestrates
static analysis, semantic review, fixes, and handoff generation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.fix_generator import FixGenerator, FixResult
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
from tools.muscle.m27_client import M27Client


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


class TestReviewModes:
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

    def _make_review_issue(self, auto_fixable: bool = False) -> ReviewIssue:
        return ReviewIssue(
            file_path="/tmp/test/test.py",
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
