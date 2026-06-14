"""
Unit tests for regex timeout protection and RegexResult reporting.
"""

from __future__ import annotations

from muscle.rules.regex_timeout import (
    RegexMatch,
    RegexResult,
    regex_finditer,
)


class TestRegexResult:
    """Tests for RegexResult dataclass."""

    def test_default_fields(self):
        """RegexResult defaults to no matches, no timeout, no error."""
        result = RegexResult(matches=[])
        assert result.matches == []
        assert result.timed_out is False
        assert result.error is None

    def test_with_matches(self):
        """RegexResult can carry matches."""
        match = RegexMatch(start=0, end=3, groups=("abc",))
        result = RegexResult(matches=[match])
        assert len(result.matches) == 1
        assert result.matches[0].start == 0

    def test_timed_out_flag(self):
        """RegexResult timed_out flag is set correctly."""
        result = RegexResult(matches=[], timed_out=True)
        assert result.timed_out is True

    def test_error_field(self):
        """RegexResult error field carries messages."""
        result = RegexResult(matches=[], error="bad pattern")
        assert result.error == "bad pattern"


class TestRegexFinditer:
    """Tests for regex_finditer behavior."""

    def test_finds_matches(self):
        """regex_finditer returns matches for a simple pattern."""
        result = regex_finditer(r"(\d+)", "abc 123 def 456", timeout=2)
        assert not result.timed_out
        assert result.error is None
        assert len(result.matches) == 2
        assert result.matches[0].groups == ("123",)
        assert result.matches[1].groups == ("456",)

    def test_no_matches(self):
        """regex_finditer returns empty matches when pattern does not match."""
        result = regex_finditer(r"xyz", "abc def", timeout=2)
        assert not result.timed_out
        assert result.error is None
        assert result.matches == []

    def test_invalid_pattern_returns_error(self):
        """Invalid regex patterns report an error via RegexResult."""
        result = regex_finditer(r"[invalid", "text", timeout=2)
        assert result.error is not None
        assert result.matches == []

    def test_timeout_detection(self):
        """Catastrophic backtracking triggers the timed_out flag."""
        # This pattern is known to cause catastrophic backtracking on certain input
        pattern = r"(a+)+$"
        text = "a" * 25 + "b"
        result = regex_finditer(pattern, text, timeout=1)
        assert result.timed_out is True
        assert result.matches == []

    def test_match_positions(self):
        """Match start/end positions are accurate."""
        result = regex_finditer(r"foo", "foo bar foo", timeout=2)
        assert len(result.matches) == 2
        assert result.matches[0].start == 0
        assert result.matches[0].end == 3
        assert result.matches[1].start == 8
        assert result.matches[1].end == 11

    def test_match_groups(self):
        """Captured groups are returned correctly."""
        result = regex_finditer(r"(\w+)=(\d+)", "x=1 y=2", timeout=2)
        assert len(result.matches) == 2
        assert result.matches[0].groups == ("x", "1")
        assert result.matches[1].groups == ("y", "2")
