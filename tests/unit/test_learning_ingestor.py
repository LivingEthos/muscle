"""
Tests for learning_ingestor.py — LearningIngestor service for structured DB evidence capture.
"""

import tempfile
from unittest.mock import MagicMock

from tools.muscle.code_review.types import (
    IssueCategory,
    ReviewIssue,
    ReviewResult,
    Severity,
)
from tools.muscle.learning_ingestor import LearningIngestor
from tools.muscle.project_memory_types import TaskStatus


def _make_issue(
    title="Test issue",
    severity=Severity.HIGH,
    category=IssueCategory.CORRECTNESS,
    file_path="src/foo.py",
    line_number=10,
    suggested_fix="Fix it",
    auto_fixable=False,
    cwe_id=None,
):
    return ReviewIssue(
        file_path=file_path,
        line_number=line_number,
        severity=severity,
        category=category,
        cwe_id=cwe_id,
        title=title,
        description=f"{title} description",
        code_snippet="x = 1",
        suggested_fix=suggested_fix,
        auto_fixable=auto_fixable,
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


class TestLearningIngestorWriteTaskRun:
    """Tests for write_task_run()."""

    def test_write_task_run_success(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_task.return_value = 42

            ingestor = LearningIngestor(mock_pm)
            task_id = ingestor.write_task_run(
                project_path=tmpdir,
                title="Test task",
                description="Test description",
                status=TaskStatus.SUCCESS,
                outcome=None,
                token_cost=1000,
                duration_ms=5000,
            )

            assert task_id == 42
            mock_pm.insert_task.assert_called_once()
            call_kwargs = mock_pm.insert_task.call_args
            assert call_kwargs.kwargs["project_path"] == tmpdir
            assert call_kwargs.kwargs["title"] == "Test task"
            assert call_kwargs.kwargs["status"] == "success"
            assert call_kwargs.kwargs["token_cost"] == 1000
            assert call_kwargs.kwargs["duration_ms"] == 5000

    def test_write_task_run_with_outcome(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_task.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            task_id = ingestor.write_task_run(
                project_path=tmpdir,
                title="Failing task",
                description="Will fail",
                status=TaskStatus.FAILED,
                outcome="RuntimeError: out of memory",
                token_cost=500,
                duration_ms=2000,
            )

            assert task_id == 1
            call_kwargs = mock_pm.insert_task.call_args
            assert call_kwargs.kwargs["outcome"] == "RuntimeError: out of memory"

    def test_write_task_run_optional_fields_missing(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_task.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            # Only pass required fields
            task_id = ingestor.write_task_run(
                project_path=tmpdir,
                title="Minimal task",
                description="",
                status=TaskStatus.PENDING,
            )

            assert task_id == 1
            call_kwargs = mock_pm.insert_task.call_args
            assert call_kwargs.kwargs["token_cost"] == 0
            assert call_kwargs.kwargs["duration_ms"] == 0
            assert call_kwargs.kwargs["outcome"] is None

    def test_write_task_run_db_error(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_task.side_effect = Exception("DB error")

            ingestor = LearningIngestor(mock_pm)
            result = ingestor.write_task_run(
                project_path=tmpdir,
                title="Failing task",
                description="",
                status=TaskStatus.FAILED,
            )

            assert result is None


class TestLearningIngestorWriteReviewRun:
    """Tests for write_review_run()."""

    def test_write_review_run_success(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.return_value = 7

            ingestor = LearningIngestor(mock_pm)
            review_run_id = ingestor.write_review_run(
                project_path=tmpdir,
                review_mode="auto_fix",
                target_path="./src",
                findings_count=5,
                token_cost=2000,
                duration_ms=10000,
            )

            assert review_run_id == 7
            mock_pm.insert_review_run.assert_called_once()
            call_kwargs = mock_pm.insert_review_run.call_args
            assert call_kwargs.kwargs["project_path"] == tmpdir
            assert call_kwargs.kwargs["review_mode"] == "auto_fix"
            assert call_kwargs.kwargs["findings_count"] == 5

    def test_write_review_run_zero_findings(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            review_run_id = ingestor.write_review_run(
                project_path=tmpdir,
                review_mode="review",
                target_path="./src",
                findings_count=0,
            )

            assert review_run_id == 1
            call_kwargs = mock_pm.insert_review_run.call_args
            assert call_kwargs.kwargs["findings_count"] == 0

    def test_write_review_run_db_error(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.side_effect = Exception("DB error")

            ingestor = LearningIngestor(mock_pm)
            result = ingestor.write_review_run(
                project_path=tmpdir,
                review_mode="review",
                target_path="./src",
            )

            assert result is None


class TestLearningIngestorWriteFindings:
    """Tests for write_findings()."""

    def test_write_findings_single_issue(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_finding.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            issues = [_make_issue(title="SQL injection", severity=Severity.HIGH)]
            count = ingestor.write_findings(review_run_id=5, issues=issues)

            assert count == 1
            mock_pm.insert_review_finding.assert_called_once()
            call_kwargs = mock_pm.insert_review_finding.call_args
            assert call_kwargs.kwargs["review_run_id"] == 5
            assert call_kwargs.kwargs["severity"] == "HIGH"
            assert call_kwargs.kwargs["file_path"] == "src/foo.py"
            assert call_kwargs.kwargs["line_number"] == 10
            assert "SQL injection" in call_kwargs.kwargs["message"]

    def test_write_findings_multiple_issues(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_finding.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            issues = [
                _make_issue(title="Issue 1", severity=Severity.HIGH, file_path="a.py"),
                _make_issue(title="Issue 2", severity=Severity.CRITICAL, file_path="b.py"),
                _make_issue(title="Issue 3", severity=Severity.MEDIUM, file_path="c.py"),
            ]
            count = ingestor.write_findings(review_run_id=1, issues=issues)

            assert count == 3
            assert mock_pm.insert_review_finding.call_count == 3

    def test_write_findings_with_fix_results(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_finding.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            issues = [
                _make_issue(title="Fixable", auto_fixable=True),
                _make_issue(title="Not fixable", auto_fixable=False),
            ]
            fix_results = {0: True}  # First issue was fixed, second was not
            count = ingestor.write_findings(review_run_id=1, issues=issues, fix_results=fix_results)

            assert count == 2
            calls = mock_pm.insert_review_finding.call_args_list
            # First issue was fixed
            assert calls[0].kwargs["fix_applied"] is True
            # Second issue was not fixed
            assert calls[1].kwargs["fix_applied"] is False

    def test_write_findings_empty_list(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()

            ingestor = LearningIngestor(mock_pm)
            count = ingestor.write_findings(review_run_id=1, issues=[])

            assert count == 0
            mock_pm.insert_review_finding.assert_not_called()

    def test_write_findings_db_error_continues(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            # First call succeeds, second fails
            mock_pm.insert_review_finding.side_effect = [1, Exception("DB error"), 3]

            ingestor = LearningIngestor(mock_pm)
            issues = [
                _make_issue(title="Issue 1"),
                _make_issue(title="Issue 2"),
                _make_issue(title="Issue 3"),
            ]
            count = ingestor.write_findings(review_run_id=1, issues=issues)

            # Should have written 2 out of 3
            assert count == 2

    def test_write_findings_with_ids_preserves_issue_order(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_finding.side_effect = [11, Exception("DB error"), 13]

            ingestor = LearningIngestor(mock_pm)
            issues = [
                _make_issue(title="Issue 1"),
                _make_issue(title="Issue 2"),
                _make_issue(title="Issue 3"),
            ]

            finding_ids = ingestor.write_findings_with_ids(review_run_id=7, issues=issues)

            assert finding_ids == [11, None, 13]


class TestLearningIngestorIssueToRuleId:
    """Tests for _issue_to_rule_id()."""

    def test_cwe_id_used_when_present(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            ingestor = LearningIngestor(mock_pm)

            issue = _make_issue(cwe_id="CWE-89")
            rule_id = ingestor._issue_to_rule_id(issue)

            assert rule_id == "CWE-89"

    def test_generated_id_from_title(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            ingestor = LearningIngestor(mock_pm)

            issue = _make_issue(title="SQL injection vulnerability")
            rule_id = ingestor._issue_to_rule_id(issue)

            assert rule_id.startswith("gen_")
            assert "sql" in rule_id
            assert "injection" in rule_id


class TestLearningIngestorLinkSessionOutcome:
    """Tests for link_session_outcome()."""

    def test_link_outcome_success(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.update_task_outcome.return_value = True

            ingestor = LearningIngestor(mock_pm)
            ingestor.link_session_outcome(
                session_id="sess-123",
                project_path=tmpdir,
                success=True,
                task_id=5,
            )

            mock_pm.update_task_outcome.assert_called_once_with(5, "success")

    def test_link_outcome_failure(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.update_task_outcome.return_value = True

            ingestor = LearningIngestor(mock_pm)
            ingestor.link_session_outcome(
                session_id="sess-123",
                project_path=tmpdir,
                success=False,
                outcome_message="Segmentation fault",
                task_id=5,
            )

            mock_pm.update_task_outcome.assert_called_once_with(5, "failed: Segmentation fault")

    def test_link_outcome_failure_no_message(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.update_task_outcome.return_value = True

            ingestor = LearningIngestor(mock_pm)
            ingestor.link_session_outcome(
                session_id="sess-123",
                project_path=tmpdir,
                success=False,
                task_id=5,
            )

            mock_pm.update_task_outcome.assert_called_once_with(5, "failed")

    def test_link_outcome_no_task_id(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()

            ingestor = LearningIngestor(mock_pm)
            # Should not raise even if task_id is None
            ingestor.link_session_outcome(
                session_id="sess-123",
                project_path=tmpdir,
                success=True,
                task_id=None,
            )

            mock_pm.update_task_outcome.assert_not_called()


class TestLearningIngestorIngestReviewResult:
    """Tests for ingest_review_result()."""

    def test_ingest_review_result_with_issues(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.return_value = 10
            mock_pm.insert_review_finding.return_value = 1

            ingestor = LearningIngestor(mock_pm)
            issues = [
                _make_issue(title="Issue 1", severity=Severity.HIGH),
                _make_issue(title="Issue 2", severity=Severity.MEDIUM),
            ]
            review_result = _make_review_result(issues=issues)

            result = ingestor.ingest_review_result(
                review_result=review_result,
                project_path=tmpdir,
                review_mode="review",
                token_cost=5000,
                duration_ms=15000,
            )

            assert result["review_run_id"] == 10
            assert result["findings_written"] == 2
            assert result["task_id"] is None
            mock_pm.insert_review_run.assert_called_once()
            assert mock_pm.insert_review_finding.call_count == 2

    def test_ingest_review_result_no_issues(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.return_value = 5

            ingestor = LearningIngestor(mock_pm)
            review_result = _make_review_result(issues=[])

            result = ingestor.ingest_review_result(
                review_result=review_result,
                project_path=tmpdir,
                review_mode="review",
            )

            assert result["review_run_id"] == 5
            assert result["findings_written"] == 0
            mock_pm.insert_review_finding.assert_not_called()

    def test_ingest_review_result_db_error_on_review_run(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.side_effect = Exception("DB error")

            ingestor = LearningIngestor(mock_pm)
            issues = [_make_issue()]
            review_result = _make_review_result(issues=issues)

            result = ingestor.ingest_review_result(
                review_result=review_result,
                project_path=tmpdir,
                review_mode="review",
            )

            assert result["review_run_id"] is None
            assert result["findings_written"] == 0
            mock_pm.insert_review_finding.assert_not_called()


class TestLearningIngestorIngestFailedReview:
    """Tests for ingest_failed_review()."""

    def test_ingest_failed_review(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            mock_pm.insert_review_run.return_value = 3

            ingestor = LearningIngestor(mock_pm)
            result = ingestor.ingest_failed_review(
                project_path=tmpdir,
                review_mode="auto_fix",
                target_path="./src",
                error_message="Static analysis failed: ruff not found",
                token_cost=100,
                duration_ms=500,
            )

            assert result["review_run_id"] == 3
            assert result["findings_written"] == 0
            mock_pm.insert_review_run.assert_called_once()
            call_kwargs = mock_pm.insert_review_run.call_args
            assert call_kwargs.kwargs["findings_count"] == 0


class TestLearningIngestorBuildFixResults:
    """Tests for _build_fix_results()."""

    def test_build_fix_results_mixed(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            ingestor = LearningIngestor(mock_pm)

            issue_a = _make_issue(title="Issue A")
            issue_b = _make_issue(title="Issue B")
            issue_c = _make_issue(title="Issue C")

            review_result = _make_review_result(issues=[issue_a, issue_b, issue_c])
            review_result.fixed_issues = [issue_a, issue_c]  # A and C fixed, B not

            fix_results = ingestor._build_fix_results(review_result)

            assert fix_results == {0: True, 1: False, 2: True}

    def test_build_fix_results_none_fixed(self):

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_pm = MagicMock()
            ingestor = LearningIngestor(mock_pm)

            issue_a = _make_issue(title="Issue A")
            review_result = _make_review_result(issues=[issue_a])
            review_result.fixed_issues = []

            fix_results = ingestor._build_fix_results(review_result)

            assert fix_results == {0: False}


class TestLearningIngestorIntegration:
    """Integration-style tests using a real ProjectMemory instance."""

    def test_full_review_ingestion_cycle(self, tmp_path):
        """Test complete review ingestion with real ProjectMemory."""
        from tools.muscle.project_memory import ProjectMemory

        project_path = str(tmp_path)
        pm = ProjectMemory(project_path)
        ingestor = LearningIngestor(pm)

        # Write a review run
        issues = [
            _make_issue(
                title="SQL injection risk",
                severity=Severity.CRITICAL,
                file_path="src/handler.py",
                line_number=42,
            ),
            _make_issue(
                title="Hardcoded secret",
                severity=Severity.HIGH,
                file_path="src/config.py",
                line_number=10,
            ),
        ]
        review_result = _make_review_result(issues=issues)

        result = ingestor.ingest_review_result(
            review_result=review_result,
            project_path=project_path,
            review_mode="auto_fix",
            token_cost=3000,
            duration_ms=12000,
        )

        assert result["review_run_id"] is not None
        assert result["findings_written"] == 2

        # Verify review run was stored
        stored_run = pm.get_review_run(result["review_run_id"])
        assert stored_run is not None
        assert stored_run["project_path"] == project_path
        assert stored_run["review_mode"] == "auto_fix"
        assert stored_run["findings_count"] == 2
        assert stored_run["token_cost"] == 3000

        # Verify findings were stored
        findings = pm.list_findings_for_run(result["review_run_id"])
        assert len(findings) == 2
        severities = {f["severity"] for f in findings}
        assert "CRITICAL" in severities
        assert "HIGH" in severities

    def test_full_task_ingestion_cycle(self, tmp_path):
        """Test complete task ingestion with real ProjectMemory."""
        from tools.muscle.project_memory import ProjectMemory

        project_path = str(tmp_path)
        pm = ProjectMemory(project_path)
        ingestor = LearningIngestor(pm)

        # Write a task run
        task_id = ingestor.write_task_run(
            project_path=project_path,
            title="Generate user auth",
            description="Create authentication module for user management",
            status=TaskStatus.SUCCESS,
            outcome=None,
            token_cost=5000,
            duration_ms=25000,
        )

        assert task_id is not None and task_id > 0

        # Verify task was stored
        tasks = pm.list_tasks(project_path=project_path)
        assert len(tasks) == 1
        stored_task = tasks[0]
        assert stored_task["title"] == "Generate user auth"
        assert stored_task["status"] == "success"
        assert stored_task["token_cost"] == 5000
        assert stored_task["duration_ms"] == 25000

    def test_failed_task_ingestion(self, tmp_path):
        """Test failed task ingestion with real ProjectMemory."""
        from tools.muscle.project_memory import ProjectMemory

        project_path = str(tmp_path)
        pm = ProjectMemory(project_path)
        ingestor = LearningIngestor(pm)

        task_id = ingestor.write_task_run(
            project_path=project_path,
            title="Compile codebase",
            description="Try to compile all source files",
            status=TaskStatus.FAILED,
            outcome="SyntaxError: unexpected EOF",
            token_cost=200,
            duration_ms=1000,
        )

        assert task_id is not None

        tasks = pm.list_tasks(project_path=project_path)
        assert len(tasks) == 1
        assert tasks[0]["status"] == "failed"
        assert "SyntaxError" in tasks[0]["outcome"]

    def test_review_with_zero_findings(self, tmp_path):
        """Test review ingestion when no issues are found."""
        from tools.muscle.project_memory import ProjectMemory

        project_path = str(tmp_path)
        pm = ProjectMemory(project_path)
        ingestor = LearningIngestor(pm)

        review_result = _make_review_result(issues=[])

        result = ingestor.ingest_review_result(
            review_result=review_result,
            project_path=project_path,
            review_mode="review",
            token_cost=1000,
            duration_ms=5000,
        )

        assert result["review_run_id"] is not None
        assert result["findings_written"] == 0

        stored_run = pm.get_review_run(result["review_run_id"])
        assert stored_run["findings_count"] == 0

    def test_multiple_reviews_accumulate(self, tmp_path):
        """Test that multiple reviews create multiple review_run rows."""
        from tools.muscle.project_memory import ProjectMemory

        project_path = str(tmp_path)
        pm = ProjectMemory(project_path)
        ingestor = LearningIngestor(pm)

        # First review
        result1 = ingestor.ingest_review_result(
            review_result=_make_review_result(issues=[_make_issue(title="Issue A")]),
            project_path=project_path,
            review_mode="review",
        )

        # Second review
        result2 = ingestor.ingest_review_result(
            review_result=_make_review_result(issues=[_make_issue(title="Issue B")]),
            project_path=project_path,
            review_mode="auto_fix",
        )

        assert result1["review_run_id"] != result2["review_run_id"]

        runs = pm.list_review_runs(project_path=project_path)
        assert len(runs) == 2
