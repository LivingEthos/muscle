from __future__ import annotations

from pathlib import Path

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.committee_reviewer import CommitteeReviewer
from tools.muscle.code_review.types import IssueCategory, ReviewIssue, ReviewScope, Severity


class DummyM27:
    def chat(self, *args, **kwargs):
        return '{"reviews": [], "summary": {}}', type("Usage", (), {"total": 0})()


class TestCommitteeReviewer:
    def test_synthesize_dedupes_and_keeps_highest_severity(self):
        reviewer = CommitteeReviewer(CodeReviewer(DummyM27()))
        low = ReviewIssue(
            file_path="src/app.py",
            line_number=10,
            severity=Severity.LOW,
            category=IssueCategory.BEST_PRACTICE,
            cwe_id=None,
            title="Network request missing timeout",
            description="low",
            code_snippet="requests.get(url)",
            source_agent="error_handling_concurrency",
        )
        high = ReviewIssue(
            file_path="src/app.py",
            line_number=10,
            severity=Severity.HIGH,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="Network request missing timeout",
            description="high",
            code_snippet="requests.get(url)",
            source_agent="correctness_security",
        )

        synthesized = reviewer.synthesize(
            {
                "correctness_security": [high],
                "error_handling_concurrency": [low],
            }
        )

        assert len(synthesized) == 1
        assert synthesized[0].severity == Severity.HIGH
        assert synthesized[0].source_agent == "correctness_security,error_handling_concurrency"

    def test_error_handling_agent_detects_swallowed_exception(self, tmp_path: Path):
        source = tmp_path / "service.py"
        source.write_text(
            "def run():\n    try:\n        return 1\n    except Exception:\n        pass\n",
            encoding="utf-8",
        )
        reviewer = CommitteeReviewer(CodeReviewer(DummyM27()))
        scope = ReviewScope(
            complexity="small",
            source_files=[str(source)],
            review_agents=["error_handling_concurrency"],
        )

        findings = reviewer.run_agent(
            "error_handling_concurrency",
            str(source),
            [],
            scope,
        )

        assert findings
        assert findings[0].title == "Swallowed exception hides failure path"

    def test_test_impact_agent_flags_missing_test_companion(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        source = src / "worker.py"
        source.write_text("def work() -> None:\n    pass\n", encoding="utf-8")
        reviewer = CommitteeReviewer(CodeReviewer(DummyM27()))
        scope = ReviewScope(
            complexity="small",
            source_files=[str(source)],
            review_agents=["test_impact_coverage"],
            changed_files=[str(source)],
        )

        findings = reviewer.run_agent(
            "test_impact_coverage",
            str(source),
            [],
            scope,
        )

        assert findings
        assert findings[0].severity == Severity.MEDIUM
