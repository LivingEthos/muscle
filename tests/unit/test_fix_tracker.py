"""
Unit tests for code_review/fix_tracker.py
"""

from datetime import datetime

import pytest

from tools.muscle.code_review.fix_tracker import FixAttempt, FixTracker


class TestFixTracker:
    @pytest.fixture
    def tracker(self, tmp_path):
        return FixTracker(tracker_path=str(tmp_path / "fix_tracker"))

    def test_init_creates_directory(self, tmp_path):
        FixTracker(tracker_path=str(tmp_path / "new_tracker"))
        assert (tmp_path / "new_tracker").exists()
        assert (tmp_path / "new_tracker" / "fix_tracker.db").exists()

    def test_init_db_creates_tables(self, tmp_path):
        tracker = FixTracker(tracker_path=str(tmp_path / "t1"))
        conn = tracker._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        assert "fix_attempts" in tables
        assert "pattern_outcomes" in tables

    def test_record_fix_attempt_success(self, tracker):
        fix_id = tracker.record_fix_attempt(
            pattern="NullPointerException",
            file_path="/src/Example.java",
            fix_description="Added null check",
            was_applied=True,
            was_successful=True,
            tokens_spent=500,
        )
        assert fix_id > 0

    def test_record_fix_attempt_failure(self, tracker):
        fix_id = tracker.record_fix_attempt(
            pattern="SQLInjection",
            file_path="/src/Query.java",
            fix_description="Added parameterized query",
            was_applied=True,
            was_successful=False,
            tokens_spent=300,
        )
        assert fix_id > 0

    def test_record_fix_attempt_not_applied(self, tracker):
        fix_id = tracker.record_fix_attempt(
            pattern="RaceCondition",
            file_path="/src/Worker.java",
            fix_description="Added lock",
            was_applied=False,
            was_successful=False,
        )
        assert fix_id > 0

    def test_record_recurrence(self, tracker):
        tracker.record_fix_attempt(
            pattern="NPE",
            file_path="/src/A.java",
            fix_description="Fix",
            was_applied=True,
            was_successful=True,
        )
        tracker.record_recurrence("NPE")

    def test_get_fix_success_rate_no_data(self, tracker):
        rate = tracker.get_fix_success_rate("nonexistent_pattern")
        assert rate == 0.0

    def test_get_fix_success_rate_with_data(self, tracker):
        tracker.record_fix_attempt(
            pattern="SQL",
            file_path="/src/Query.java",
            fix_description="Fix",
            was_applied=True,
            was_successful=True,
        )
        tracker.record_fix_attempt(
            pattern="SQL",
            file_path="/src/Query2.java",
            fix_description="Fix",
            was_applied=True,
            was_successful=False,
        )
        rate = tracker.get_fix_success_rate("SQL")
        assert 0.0 <= rate <= 1.0

    def test_is_pattern_resolved_false(self, tracker):
        tracker.record_fix_attempt(
            pattern="Bug",
            file_path="/src/F.java",
            fix_description="Fix",
            was_applied=True,
            was_successful=False,
        )
        resolved = tracker.is_pattern_resolved("Bug")
        assert resolved is False

    def test_is_pattern_resolved_true(self, tracker):
        for _ in range(3):
            tracker.record_fix_attempt(
                pattern="FixedBug",
                file_path="/src/F.java",
                fix_description="Fix",
                was_applied=True,
                was_successful=True,
            )
        resolved = tracker.is_pattern_resolved("FixedBug", recurrence_threshold=1)
        assert resolved is True

    def test_get_statistics_empty(self, tracker):
        stats = tracker.get_statistics()
        assert stats["total_fix_attempts"] == 0
        assert stats["success_rate"] == 0.0

    def test_get_statistics_with_data(self, tracker):
        tracker.record_fix_attempt(
            pattern="Err",
            file_path="/src/X.java",
            fix_description="Fix",
            was_applied=True,
            was_successful=True,
            tokens_spent=100,
        )
        stats = tracker.get_statistics()
        assert stats["total_fix_attempts"] == 1
        assert stats["successful_fixes"] == 1
        assert stats["total_tokens_spent"] == 100

    def test_fix_attempt_dataclass(self):
        attempt = FixAttempt(
            id=1,
            pattern="test",
            file_path="/test.py",
            fix_description="desc",
            was_applied=True,
            was_successful=True,
            tokens_spent=50,
            recurrence_count=0,
            created_at=datetime.now().isoformat(),
        )
        assert attempt.id == 1
        assert attempt.pattern == "test"
