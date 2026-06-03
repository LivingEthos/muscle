from __future__ import annotations

from pathlib import Path

from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.committee_reviewer import AGENT_CORRECTNESS, CommitteeReviewer
from tools.muscle.code_review.types import IssueCategory, ReviewIssue, ReviewScope, Severity


class DummyM27:
    def chat(self, *args, **kwargs):
        return '{"reviews": [], "summary": {}}', type("Usage", (), {"total": 0})()


class RaisingCodeReviewer(CodeReviewer):
    def review(self, *args, **kwargs):
        msg = "LLM review should not run for deterministic fast path"
        raise AssertionError(msg)


class TestCommitteeReviewer:
    def test_correctness_agent_uses_deterministic_fast_path_for_trivial_security_file(
        self,
        tmp_path: Path,
    ):
        source = tmp_path / "bad_code.py"
        source.write_text(
            "def unsafe_eval(user_input: str):\n"
            "    return eval(user_input)\n\n"
            "def secret():\n"
            "    password = 'super_secret'\n"
            "    return password\n\n"
            "def lookup(cursor, user_id):\n"
            '    query = f"SELECT * FROM users WHERE id = {user_id}"\n'
            "    return cursor.execute(query)\n",
            encoding="utf-8",
        )
        reviewer = CommitteeReviewer(RaisingCodeReviewer(DummyM27()))
        scope = ReviewScope(
            complexity="trivial",
            source_files=[str(source)],
            review_agents=[AGENT_CORRECTNESS],
        )

        findings = reviewer.run_agent(
            AGENT_CORRECTNESS,
            str(source),
            [],
            scope,
            telemetry_session_id="session-1",
            workflow_name="review-smart",
            review_mode="review",
            language="Python",
        )

        titles = {finding.title for finding in findings}
        assert "Unsafe eval execution" in titles
        assert "Hardcoded password or API key secret" in titles
        assert "SQL injection via formatted query" in titles
        assert reviewer.consume_agent_tokens(AGENT_CORRECTNESS) == 0

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
            test_scope="targeted",
        )

        findings = reviewer.run_agent(
            "test_impact_coverage",
            str(source),
            [],
            scope,
        )

        assert findings
        assert findings[0].severity == Severity.MEDIUM

    def test_test_impact_agent_keeps_repo_scan_missing_tests_low_severity(
        self,
        tmp_path: Path,
    ):
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
            test_scope="repo-scan",
        )

        findings = reviewer.run_agent(
            "test_impact_coverage",
            str(source),
            [],
            scope,
        )

        assert findings
        assert findings[0].severity == Severity.LOW
