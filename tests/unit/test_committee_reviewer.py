from __future__ import annotations

from pathlib import Path
from threading import Thread

from muscle.code_review.code_reviewer import CodeReviewer
from muscle.code_review.committee_reviewer import (
    AGENT_CORRECTNESS,
    CommitteeReviewer,
    _split_from_summary,
)
from muscle.code_review.types import IssueCategory, ReviewIssue, ReviewScope, Severity


class DummyM27:
    def chat(self, *args, **kwargs):
        return '{"reviews": [], "summary": {}}', type("Usage", (), {"total": 0})()


class RecordingCodeReviewer(CodeReviewer):
    def __init__(self, client):
        super().__init__(client)
        self.review_calls = 0

    def review(self, *args, **kwargs):
        self.review_calls += 1
        llm_issue = ReviewIssue(
            file_path="bad_code.py",
            line_number=1,
            severity=Severity.HIGH,
            category=IssueCategory.SECURITY,
            cwe_id=None,
            title="Injection risk found by LLM",
            description="llm",
            code_snippet="eval(user_input)",
            source_agent="correctness_security",
        )
        return [llm_issue], {"token_usage": 50, "token_usage_input": 40, "token_usage_output": 10}


class TestCommitteeReviewer:
    def test_correctness_agent_runs_llm_even_with_deterministic_findings(
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
        code_reviewer = RecordingCodeReviewer(DummyM27())
        reviewer = CommitteeReviewer(code_reviewer)
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

        # Positive deterministic findings must never suppress the LLM pass.
        assert code_reviewer.review_calls == 1
        titles = {finding.title for finding in findings}
        assert "Unsafe eval execution" in titles
        assert "Hardcoded password or API key secret" in titles
        assert "SQL injection via formatted query" in titles
        assert "Injection risk found by LLM" in titles
        assert reviewer.consume_agent_tokens(AGENT_CORRECTNESS) == (40, 10, 0)

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
            suggested_fix="Add timeout=5.",
            source_agent="error_handling_concurrency",
        )
        high = ReviewIssue(
            file_path="src/app.py",
            line_number=10,
            severity=Severity.HIGH,
            category=IssueCategory.BEST_PRACTICE,
            cwe_id=None,
            title="Network request missing timeout",
            description="high",
            code_snippet="requests.get(url)",
            suggested_fix="Use a shared client timeout.",
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
        assert "Add timeout=5." in (synthesized[0].suggested_fix or "")
        assert "Use a shared client timeout." in (synthesized[0].suggested_fix or "")

    def test_synthesize_keeps_same_line_similar_title_different_categories(self):
        reviewer = CommitteeReviewer(CodeReviewer(DummyM27()))
        security = ReviewIssue(
            file_path="src/app.py",
            line_number=10,
            severity=Severity.HIGH,
            category=IssueCategory.SECURITY,
            cwe_id="CWE-89",
            title="User input reaches query",
            description="security",
            code_snippet="cursor.execute(query)",
            source_agent="correctness_security",
        )
        correctness = ReviewIssue(
            file_path="src/app.py",
            line_number=10,
            severity=Severity.HIGH,
            category=IssueCategory.CORRECTNESS,
            cwe_id=None,
            title="User input reaches query",
            description="correctness",
            code_snippet="cursor.execute(query)",
            source_agent="error_handling_concurrency",
        )

        synthesized = reviewer.synthesize(
            {
                "correctness_security": [security],
                "error_handling_concurrency": [correctness],
            }
        )

        assert len(synthesized) == 2
        assert {issue.category for issue in synthesized} == {
            IssueCategory.SECURITY,
            IssueCategory.CORRECTNESS,
        }

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


class TestAgentTokenSplitAccounting:
    def test_record_consume_split_round_trip(self) -> None:
        reviewer = CommitteeReviewer(CodeReviewer(DummyM27()))
        reviewer._record_agent_tokens(AGENT_CORRECTNESS, 100, 40, 25)
        reviewer._record_agent_tokens(AGENT_CORRECTNESS, 100, 40, 25)
        assert reviewer.consume_agent_tokens(AGENT_CORRECTNESS) == (200, 80, 50)
        # Second consume drains the entry to the empty default.
        assert reviewer.consume_agent_tokens(AGENT_CORRECTNESS) == (0, 0, 0)

    def test_concurrent_record_does_not_lose_tokens(self) -> None:
        reviewer = CommitteeReviewer(CodeReviewer(DummyM27()))

        def worker() -> None:
            for _ in range(100):
                reviewer._record_agent_tokens(AGENT_CORRECTNESS, 1, 2, 1)

        threads = [Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # 8 threads * 100 iterations * (1 in, 2 out) with no lost updates.
        assert reviewer.consume_agent_tokens(AGENT_CORRECTNESS) == (800, 1600, 800)


class TestSplitFromSummary:
    def test_both_split_keys_present(self) -> None:
        summary = {"token_usage": 1200, "token_usage_input": 900, "token_usage_output": 300}
        assert _split_from_summary(summary) == (900, 300, 0)

    def test_cached_input_subset_threaded_through(self) -> None:
        summary = {
            "token_usage_input": 900,
            "token_usage_output": 300,
            "token_usage_cached_input": 700,
        }
        assert _split_from_summary(summary) == (900, 300, 700)

    def test_cached_input_clamped_to_input(self) -> None:
        summary = {
            "token_usage_input": 100,
            "token_usage_output": 50,
            "token_usage_cached_input": 500,
        }
        assert _split_from_summary(summary) == (100, 50, 100)

    def test_legacy_dict_with_only_combined_total(self) -> None:
        # Older summaries that never carried the split: attribute all to input.
        assert _split_from_summary({"token_usage": 1200}) == (1200, 0, 0)

    def test_empty_dict_yields_zero_split(self) -> None:
        assert _split_from_summary({}) == (0, 0, 0)
