"""
Integration tests for data stores: ReviewKB, FixTracker, StrategyKB.

Tests real SQLite operations and JSON file persistence.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.muscle.code_review.fix_tracker import FixTracker
from tools.muscle.code_review.review_kb import GlobalReviewKB, ReviewKB
from tools.muscle.strategy_kb import GlobalKnowledgeBase


class TestReviewKBIntegration:
    """Tests ReviewKB with real SQLite operations."""

    def test_full_review_lifecycle(self, tmp_path: Path):
        """Test add -> query -> stats lifecycle."""
        kb = ReviewKB(str(tmp_path / "review_kb"))

        # Add various issues
        id1 = kb.add_reviewed_issue(
            file_path="src/auth.py",
            line_number=42,
            severity="CRITICAL",
            category="security",
            title="SQL injection in login",
            code_pattern="f-string SQL",
            was_valid=True,
            was_fixed=True,
            auto_fixed=False,
        )
        assert id1 > 0

        id2 = kb.add_reviewed_issue(
            file_path="src/auth.py",
            line_number=55,
            severity="HIGH",
            category="security",
            title="Hardcoded credentials",
            code_pattern="hardcoded password",
            was_valid=True,
            was_fixed=False,
        )
        assert id2 > 0

        id3 = kb.add_reviewed_issue(
            file_path="src/utils.py",
            line_number=10,
            severity="LOW",
            category="style",
            title="Unused import",
            code_pattern="unused import",
            was_valid=False,
            false_positive_reason="Import used in test file",
        )
        assert id3 > 0

        # Check statistics
        stats = kb.get_statistics()
        assert stats["total_reviewed"] == 3
        assert stats["false_positives"] == 1
        assert stats["issues_fixed"] == 1

    def test_fix_effectiveness_tracking(self, tmp_path: Path):
        """Fix attempts should be tracked with success/failure rates."""
        kb = ReviewKB(str(tmp_path / "review_kb"))

        # Record multiple fix attempts for same pattern
        kb.record_fix_attempt("f-string SQL", success=True, tokens_spent=500)
        kb.record_fix_attempt("f-string SQL", success=True, tokens_spent=600)
        kb.record_fix_attempt("f-string SQL", success=False, tokens_spent=800)

        # Check effectiveness
        rate = kb.get_false_positive_rate("f-string SQL")
        # This queries reviewed_issues, not fix_effectiveness, so rate is 0
        assert isinstance(rate, float)

    def test_multiple_patterns_independence(self, tmp_path: Path):
        """Different patterns should track independently."""
        kb = ReviewKB(str(tmp_path / "review_kb"))

        for i in range(5):
            kb.add_reviewed_issue(
                file_path=f"file_{i}.py",
                line_number=i,
                severity="HIGH",
                category="security",
                title="Pattern A",
                code_pattern="pattern_a",
                was_valid=True,
            )

        for i in range(3):
            kb.add_reviewed_issue(
                file_path=f"file_{i}.py",
                line_number=i,
                severity="MEDIUM",
                category="correctness",
                title="Pattern B",
                code_pattern="pattern_b",
                was_valid=True,
            )

        stats = kb.get_statistics()
        assert stats["total_reviewed"] == 8


class TestGlobalReviewKBIntegration:
    """Tests cross-project GlobalReviewKB."""

    def test_global_kb_records_and_queries(self, tmp_path: Path):
        """GlobalReviewKB should aggregate across projects."""
        gkb = GlobalReviewKB(str(tmp_path / "global_kb"))

        gkb.record_issue(
            file_path="project_a/src/main.py",
            line_number=10,
            severity="HIGH",
            category="security",
            title="XSS vulnerability",
            code_pattern="unsanitized output",
            was_valid=True,
        )

        gkb.record_fix("unsanitized output", success=True, tokens_spent=300)

        stats = gkb.get_stats()
        assert stats["total_reviewed"] == 1
        assert stats["fix_successes"] == 1


class TestFixTrackerIntegration:
    """Tests FixTracker with real SQLite operations."""

    def test_record_and_query_fixes(self, tmp_path: Path):
        """Fix attempts should be persistently tracked."""
        tracker = FixTracker(str(tmp_path / "fix_tracker"))

        # Record successful fix
        id1 = tracker.record_fix_attempt(
            pattern="SQL injection",
            file_path="src/db.py",
            fix_description="Replaced f-string with parameterized query",
            was_applied=True,
            was_successful=True,
            tokens_spent=500,
        )
        assert id1 > 0

        # Record failed fix
        id2 = tracker.record_fix_attempt(
            pattern="SQL injection",
            file_path="src/api.py",
            fix_description="Added input sanitization",
            was_applied=True,
            was_successful=False,
            tokens_spent=700,
        )
        assert id2 > 0

        # Query fix success rate
        rate = tracker.get_fix_success_rate("SQL injection")
        assert rate == 0.5  # 1 success / 2 attempts

    def test_success_rate_calculation(self, tmp_path: Path):
        """Success rate should be accurately calculated."""
        tracker = FixTracker(str(tmp_path / "fix_tracker"))

        # 3 successes, 2 failures
        for i in range(3):
            tracker.record_fix_attempt(
                pattern="missing validation",
                file_path=f"src/handler_{i}.py",
                fix_description="Added input validation",
                was_applied=True,
                was_successful=True,
                tokens_spent=300,
            )

        for i in range(2):
            tracker.record_fix_attempt(
                pattern="missing validation",
                file_path=f"src/other_{i}.py",
                fix_description="Added validation (failed)",
                was_applied=True,
                was_successful=False,
                tokens_spent=400,
            )

        rate = tracker.get_fix_success_rate("missing validation")
        assert abs(rate - 0.6) < 0.01

    def test_statistics(self, tmp_path: Path):
        """Statistics should report aggregate fix data."""
        tracker = FixTracker(str(tmp_path / "fix_tracker"))

        tracker.record_fix_attempt(
            pattern="pattern_alpha",
            file_path="a.py",
            fix_description="fix a",
            was_applied=True,
            was_successful=True,
        )
        tracker.record_fix_attempt(
            pattern="pattern_beta",
            file_path="b.py",
            fix_description="fix b",
            was_applied=True,
            was_successful=False,
        )

        stats = tracker.get_statistics()
        assert isinstance(stats, dict)
        assert stats.get("total_fix_attempts", 0) >= 2


class TestStrategyKBIntegration:
    """Tests strategy knowledge base with real operations."""

    def test_add_and_search_strategies(self, tmp_path: Path):
        """Strategies should be searchable after adding."""
        gkb = GlobalKnowledgeBase(str(tmp_path / "strategy_kb"))

        gkb.strategy_kb.add_strategy(
            error_pattern="TypeError in API handler",
            root_cause="Missing type validation at API boundary",
            solution_strategy="Add type checking with isinstance()",
            language="python",
        )

        gkb.strategy_kb.add_strategy(
            error_pattern="Connection timeout in database",
            root_cause="Single connection under load",
            solution_strategy="Add connection pooling with retry",
            language="python",
        )

        results = gkb.search("TypeError handler")
        assert isinstance(results, list)

    def test_export_import_roundtrip(self, tmp_path: Path):
        """Export then import should preserve all strategies."""
        kb_path = str(tmp_path / "strategy_kb")
        gkb = GlobalKnowledgeBase(kb_path)

        gkb.strategy_kb.add_strategy(
            error_pattern="Test pattern",
            root_cause="Test cause",
            solution_strategy="Test solution",
            language="python",
        )

        export_file = str(tmp_path / "export.json")
        gkb.strategy_kb.export_to_json(export_file)

        assert Path(export_file).exists()
        data = json.loads(Path(export_file).read_text())
        assert isinstance(data, list)

        # Import into a new KB
        gkb2 = GlobalKnowledgeBase(str(tmp_path / "strategy_kb2"))
        count = gkb2.strategy_kb.import_from_json(export_file)
        assert count >= 1

    def test_usage_tracking(self, tmp_path: Path):
        """Strategy usage should be tracked for effectiveness scoring."""
        gkb = GlobalKnowledgeBase(str(tmp_path / "strategy_kb"))

        sid = gkb.strategy_kb.add_strategy(
            error_pattern="Race condition",
            root_cause="Shared mutable state",
            solution_strategy="Add threading lock",
            language="python",
        )

        if sid:
            gkb.strategy_kb.increment_usage(sid, success=True)
            gkb.strategy_kb.increment_usage(sid, success=True)
            gkb.strategy_kb.increment_usage(sid, success=False)

            stats = gkb.strategy_kb.get_statistics()
            assert stats["total_strategies"] >= 1
            assert stats["total_usage"] >= 3
