"""
Unit tests for ReviewKB.
"""

import pytest
import tempfile
from pathlib import Path

from tools.scle.code_review.review_kb import ReviewKB, GlobalReviewKB


@pytest.fixture
def temp_kb_dir():
    """Create a temporary directory for KB testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestReviewKBInitialization:
    """Test ReviewKB initialization."""

    def test_init_creates_directory(self, temp_kb_dir):
        """Test that KB initializes and creates its directory."""
        kb = ReviewKB(str(temp_kb_dir))
        assert temp_kb_dir.exists()
        assert (temp_kb_dir / "review_kb.db").exists()

    def test_init_with_default_path(self):
        """Test KB initialization with default path."""
        kb = ReviewKB()
        # Should use DEFAULT_REVIEW_KB_DIR = ".scle/review_kb"
        assert kb.kb_path.name == "review_kb"


class TestAddReviewedIssue:
    """Test adding reviewed issues."""

    def test_add_reviewed_issue(self, temp_kb_dir):
        """Test adding a reviewed issue."""
        kb = ReviewKB(str(temp_kb_dir))

        issue_id = kb.add_reviewed_issue(
            file_path="src/auth.py",
            line_number=42,
            severity="HIGH",
            category="security",
            title="SQL Injection",
            code_pattern="eval(user_input)",
            was_valid=True,
            was_fixed=True,
            auto_fixed=False,
        )

        assert issue_id > 0

    def test_add_issue_with_false_positive(self, temp_kb_dir):
        """Test adding a false positive issue."""
        kb = ReviewKB(str(temp_kb_dir))

        issue_id = kb.add_reviewed_issue(
            file_path="src/main.py",
            line_number=10,
            severity="LOW",
            category="style",
            title="Line too long",
            code_pattern="x = 1",
            was_valid=False,
            was_fixed=False,
            false_positive_reason="Intentional - this is a one-liner",
        )

        assert issue_id > 0


class TestFixEffectiveness:
    """Test tracking fix effectiveness."""

    def test_record_fix_attempt_success(self, temp_kb_dir):
        """Test recording a successful fix attempt."""
        kb = ReviewKB(str(temp_kb_dir))

        kb.record_fix_attempt(
            pattern="eval_usage",
            success=True,
            tokens_spent=500,
        )

        rate = kb.get_fix_success_rate("eval_usage")
        assert rate == 1.0

    def test_record_multiple_fix_attempts(self, temp_kb_dir):
        """Test recording multiple fix attempts."""
        kb = ReviewKB(str(temp_kb_dir))

        kb.record_fix_attempt("pattern1", success=True, tokens_spent=100)
        kb.record_fix_attempt("pattern1", success=True, tokens_spent=100)
        kb.record_fix_attempt("pattern1", success=False, tokens_spent=100)

        rate = kb.get_fix_success_rate("pattern1")
        assert rate == pytest.approx(2 / 3)

    def test_get_fix_success_rate_unknown_pattern(self, temp_kb_dir):
        """Test fix success rate for unknown pattern."""
        kb = ReviewKB(str(temp_kb_dir))

        rate = kb.get_fix_success_rate("unknown_pattern")
        assert rate == 0.0


class TestFalsePositiveRate:
    """Test false positive rate tracking."""

    def test_false_positive_rate_calculation(self, temp_kb_dir):
        """Test false positive rate is calculated correctly."""
        kb = ReviewKB(str(temp_kb_dir))

        kb.add_reviewed_issue(
            file_path="a.py",
            line_number=1,
            severity="HIGH",
            category="style",
            title="Issue 1",
            code_pattern="pattern",
            was_valid=True,
        )
        kb.add_reviewed_issue(
            file_path="b.py",
            line_number=1,
            severity="HIGH",
            category="style",
            title="Issue 2",
            code_pattern="pattern",
            was_valid=False,
        )

        rate = kb.get_false_positive_rate("pattern")
        assert rate == pytest.approx(0.5)

    def test_should_skip_pattern_high_fp_rate(self, temp_kb_dir):
        """Test pattern skipping when false positive rate is high."""
        kb = ReviewKB(str(temp_kb_dir))

        kb.add_reviewed_issue(
            file_path="a.py",
            line_number=1,
            severity="LOW",
            category="style",
            title="Issue 1",
            code_pattern="high_fp_pattern",
            was_valid=False,
        )
        kb.add_reviewed_issue(
            file_path="b.py",
            line_number=1,
            severity="LOW",
            category="style",
            title="Issue 2",
            code_pattern="high_fp_pattern",
            was_valid=False,
        )
        kb.add_reviewed_issue(
            file_path="c.py",
            line_number=1,
            severity="LOW",
            category="style",
            title="Issue 3",
            code_pattern="high_fp_pattern",
            was_valid=False,
        )

        should_skip = kb.should_skip_pattern("high_fp_pattern", threshold=0.7)
        assert should_skip is True

    def test_should_not_skip_pattern_low_fp_rate(self, temp_kb_dir):
        """Test pattern is not skipped when false positive rate is low."""
        kb = ReviewKB(str(temp_kb_dir))

        kb.add_reviewed_issue(
            file_path="a.py",
            line_number=1,
            severity="HIGH",
            category="security",
            title="Real issue",
            code_pattern="real_issue",
            was_valid=True,
        )

        should_skip = kb.should_skip_pattern("real_issue")
        assert should_skip is False


class TestStatistics:
    """Test statistics retrieval."""

    def test_get_statistics_empty(self, temp_kb_dir):
        """Test statistics with empty KB."""
        kb = ReviewKB(str(temp_kb_dir))

        stats = kb.get_statistics()

        assert stats["total_reviewed"] == 0
        assert stats["false_positives"] == 0
        assert stats["issues_fixed"] == 0

    def test_get_statistics_with_data(self, temp_kb_dir):
        """Test statistics with some data."""
        kb = ReviewKB(str(temp_kb_dir))

        kb.add_reviewed_issue(
            file_path="a.py",
            line_number=1,
            severity="HIGH",
            category="security",
            title="Issue",
            code_pattern="pattern",
            was_valid=True,
            was_fixed=True,
            auto_fixed=True,
        )

        kb.record_fix_attempt("pattern", success=True, tokens_spent=100)

        stats = kb.get_statistics()

        assert stats["total_reviewed"] == 1
        assert stats["issues_fixed"] == 1
        assert stats["auto_fixed"] == 1
        assert stats["fix_attempts"] == 1
        assert stats["fix_successes"] == 1


class TestGlobalReviewKB:
    """Test GlobalReviewKB."""

    def test_global_kb_initialization(self):
        """Test GlobalReviewKB initializes with expanded path."""
        gkb = GlobalReviewKB()
        assert gkb.global_path.name == "global_review"

    def test_record_issue_delegates_to_review_kb(self, temp_kb_dir):
        """Test record_issue delegates to ReviewKB."""
        gkb = GlobalReviewKB(str(temp_kb_dir))

        issue_id = gkb.record_issue(
            file_path="test.py",
            line_number=1,
            severity="HIGH",
            category="style",
            title="Test",
            code_pattern="test",
            was_valid=True,
        )

        assert issue_id > 0

    def test_record_fix_delegates_to_review_kb(self, temp_kb_dir):
        """Test record_fix delegates to ReviewKB."""
        gkb = GlobalReviewKB(str(temp_kb_dir))

        gkb.record_fix("test_pattern", success=True, tokens_spent=100)

        rate = gkb.get_stats()["fix_attempts"]
        assert rate == 1

    def test_get_stats_delegates_to_review_kb(self, temp_kb_dir):
        """Test get_stats delegates to ReviewKB."""
        gkb = GlobalReviewKB(str(temp_kb_dir))

        stats = gkb.get_stats()

        assert "total_reviewed" in stats
        assert "fix_attempts" in stats
