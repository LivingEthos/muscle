"""
Tests for pattern_detector.py
"""

from unittest.mock import MagicMock, patch

from tools.muscle.code_review.pattern_detector import PatternDetector, PatternInfo


class TestPatternDetector:
    """Tests for PatternDetector class."""

    def test_pattern_info_dataclass(self):
        """Test PatternInfo dataclass initialization."""
        pattern = PatternInfo(
            pattern="test_pattern",
            category="security",
            occurrences=5,
            files=["file1.py", "file2.py"],
            severity_counts={"HIGH": 3, "MEDIUM": 2},
            confidence=0.75,
        )

        assert pattern.pattern == "test_pattern"
        assert pattern.category == "security"
        assert pattern.occurrences == 5
        assert len(pattern.files) == 2
        assert pattern.confidence == 0.75

    def test_should_create_skill(self):
        """Test skill creation eligibility check."""
        detector = PatternDetector()

        low_confidence = PatternInfo(
            pattern="test",
            category="style",
            occurrences=3,
            files=[],
            severity_counts={},
            confidence=0.3,
        )
        assert detector.should_create_skill(low_confidence) is False

        high_confidence = PatternInfo(
            pattern="test",
            category="security",
            occurrences=5,
            files=["file1.py"],
            severity_counts={"HIGH": 5},
            confidence=0.7,
        )
        assert detector.should_create_skill(high_confidence) is True

    def test_should_create_agent(self):
        """Test agent creation eligibility check."""
        detector = PatternDetector()

        non_complex = PatternInfo(
            pattern="test",
            category="style",
            occurrences=5,
            files=["file1.py"],
            severity_counts={},
            confidence=0.7,
        )
        assert detector.should_create_agent(non_complex) is False

        complex_category = PatternInfo(
            pattern="auth_bypass",
            category="security",
            occurrences=5,
            files=["file1.py"],
            severity_counts={"CRITICAL": 5},
            confidence=0.7,
        )
        assert detector.should_create_agent(complex_category) is True

    def test_calculate_confidence_perfect(self):
        """Test _calculate_confidence with ideal data."""
        detector = PatternDetector()
        data = {
            "occurrences": 10,
            "files": {"a.py", "b.py", "c.py", "d.py", "e.py"},
            "severity_counts": {"CRITICAL": 10},
        }
        confidence = detector._calculate_confidence(data)
        assert 0.0 <= confidence <= 1.0

    def test_calculate_confidence_single_file_many_occurrences(self):
        """Test _calculate_confidence with single file."""
        detector = PatternDetector()
        data = {
            "occurrences": 10,
            "files": {"same.py"},
            "severity_counts": {"HIGH": 5, "MEDIUM": 5},
        }
        confidence = detector._calculate_confidence(data)
        assert 0.0 <= confidence <= 1.0

    def test_calculate_confidence_zero_occurrences(self):
        """Test _calculate_confidence with zero occurrences."""
        detector = PatternDetector()
        data = {
            "occurrences": 0,
            "files": set(),
            "severity_counts": {},
        }
        confidence = detector._calculate_confidence(data)
        assert 0.0 <= confidence <= 1.0

    def test_get_skill_candidates_filters_by_confidence(self):
        """Test get_skill_candidates filters low confidence patterns."""
        detector = PatternDetector()
        detector._patterns = {
            "low_conf": PatternInfo(
                pattern="low_conf",
                category="style",
                occurrences=5,
                files=["a.py"],
                severity_counts={},
                confidence=0.3,
            ),
            "high_conf": PatternInfo(
                pattern="high_conf",
                category="security",
                occurrences=5,
                files=["a.py"],
                severity_counts={},
                confidence=0.7,
            ),
        }
        candidates = detector.get_skill_candidates()
        assert len(candidates) == 1
        assert candidates[0].pattern == "high_conf"

    def test_get_skill_candidates_empty_when_all_low_confidence(self):
        """Test get_skill_candidates returns empty when all low confidence."""
        detector = PatternDetector()
        detector._patterns = {
            "low": PatternInfo(
                pattern="low",
                category="style",
                occurrences=3,
                files=["a.py"],
                severity_counts={},
                confidence=0.3,
            ),
        }
        assert detector.get_skill_candidates() == []

    def test_get_agent_candidates_filters_by_category_and_confidence(self):
        """Test get_agent_candidates requires complex category."""
        detector = PatternDetector()
        detector._patterns = {
            "style_not_complex": PatternInfo(
                pattern="style",
                category="style",
                occurrences=5,
                files=["a.py"],
                severity_counts={},
                confidence=0.8,
            ),
            "security_complex": PatternInfo(
                pattern="security_issue",
                category="security",
                occurrences=5,
                files=["a.py"],
                severity_counts={"HIGH": 5},
                confidence=0.7,
            ),
            "performance_complex": PatternInfo(
                pattern="perf_issue",
                category="performance",
                occurrences=5,
                files=["a.py"],
                severity_counts={"HIGH": 5},
                confidence=0.8,
            ),
        }
        candidates = detector.get_agent_candidates()
        assert len(candidates) == 2
        patterns = [c.pattern for c in candidates]
        assert "security_issue" in patterns
        assert "perf_issue" in patterns
        assert "style_not_complex" not in patterns

    def test_get_agent_candidates_does_not_filter_by_occurrences(self):
        """Test get_agent_candidates does NOT require occurrences >= 5 (only should_create_agent does)."""
        detector = PatternDetector()
        detector._patterns = {
            "few_occurrences": PatternInfo(
                pattern="auth_bypass",
                category="security",
                occurrences=3,
                files=["a.py"],
                severity_counts={"HIGH": 3},
                confidence=0.8,
            ),
        }
        candidates = detector.get_agent_candidates()
        assert len(candidates) == 1

    def test_get_agent_candidates_requires_high_confidence(self):
        """Test get_agent_candidates requires confidence >= 0.6."""
        detector = PatternDetector()
        detector._patterns = {
            "low_conf": PatternInfo(
                pattern="auth_bypass",
                category="security",
                occurrences=5,
                files=["a.py"],
                severity_counts={"HIGH": 5},
                confidence=0.4,
            ),
        }
        assert detector.get_agent_candidates() == []

    def test_should_create_skill_requires_min_occurrences(self):
        """Test should_create_skill requires occurrences >= min_occurrences."""
        detector = PatternDetector()
        pattern = PatternInfo(
            pattern="rare",
            category="security",
            occurrences=2,
            files=["a.py"],
            severity_counts={"HIGH": 2},
            confidence=0.8,
        )
        assert detector.should_create_skill(pattern) is False

    def test_should_create_skill_requires_confidence(self):
        """Test should_create_skill requires confidence >= 0.5."""
        detector = PatternDetector()
        pattern = PatternInfo(
            pattern="frequent",
            category="security",
            occurrences=5,
            files=["a.py"],
            severity_counts={"HIGH": 5},
            confidence=0.4,
        )
        assert detector.should_create_skill(pattern) is False


class TestDetectPatterns:
    """Tests for detect_patterns and _aggregate_patterns."""

    def _make_mock_row(
        self, code_pattern: str, category: str, file_path: str, severity: str, count: int
    ):
        """Create a mock row with dictionary-style access."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "code_pattern": code_pattern,
            "category": category,
            "file_path": file_path,
            "severity": severity,
            "count": count,
        }[key]
        return row

    def test_detect_patterns_finds_pattern_with_3_plus_occurrences(self):
        """Test detect_patterns finds pattern when occurrences >= 3."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            self._make_mock_row("auth_bypass", "security", "a.py", "HIGH", 3),
            self._make_mock_row("style_issue", "style", "b.py", "MEDIUM", 2),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            patterns = detector.detect_patterns()

        assert len(patterns) == 1
        assert patterns[0].pattern == "auth_bypass"
        assert patterns[0].occurrences == 3

    def test_detect_patterns_ignores_pattern_with_fewer_than_3_occurrences(self):
        """Test detect_patterns ignores pattern when occurrences < 3."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            self._make_mock_row("rare_issue", "style", "a.py", "LOW", 1),
            self._make_mock_row("style_issue", "style", "b.py", "MEDIUM", 2),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            patterns = detector.detect_patterns()

        assert len(patterns) == 0

    def test_detect_patterns_aggregates_multiple_files(self):
        """Test detect_patterns aggregates files across multiple rows."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            self._make_mock_row("sql_injection", "security", "a.py", "HIGH", 2),
            self._make_mock_row("sql_injection", "security", "b.py", "HIGH", 1),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            patterns = detector.detect_patterns()

        assert len(patterns) == 1
        assert patterns[0].pattern == "sql_injection"
        assert patterns[0].occurrences == 3
        assert "a.py" in patterns[0].files
        assert "b.py" in patterns[0].files

    def test_detect_patterns_aggregates_severity_counts(self):
        """Test detect_patterns aggregates severity counts across rows."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            self._make_mock_row("null_check", "style", "a.py", "HIGH", 2),
            self._make_mock_row("null_check", "style", "b.py", "MEDIUM", 1),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            patterns = detector.detect_patterns()

        assert len(patterns) == 1
        assert patterns[0].severity_counts["HIGH"] == 2
        assert patterns[0].severity_counts["MEDIUM"] == 1

    def test_detect_patterns_empty_database(self):
        """Test detect_patterns returns empty list when no patterns found."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            patterns = detector.detect_patterns()

        assert patterns == []

    def test_aggregate_patterns_returns_dict(self):
        """Test _aggregate_patterns returns correct dict structure."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            self._make_mock_row("test_pattern", "security", "a.py", "HIGH", 5),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            result = detector._aggregate_patterns()

        assert "test_pattern" in result
        assert result["test_pattern"]["occurrences"] == 5
        assert "a.py" in result["test_pattern"]["files"]

    def test_aggregate_patterns_closes_connection(self):
        """Test _aggregate_patterns closes DB connection."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(detector := PatternDetector(), "kb") as mock_kb:
            mock_kb._get_connection.return_value = mock_conn
            detector._aggregate_patterns()

        mock_conn.close.assert_called_once()
