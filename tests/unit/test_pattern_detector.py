"""
Tests for pattern_detector.py
"""


class TestPatternDetector:
    """Tests for PatternDetector class."""

    def test_pattern_info_dataclass(self):
        """Test PatternInfo dataclass initialization."""
        from tools.muscle.code_review.pattern_detector import PatternInfo

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
        from tools.muscle.code_review.pattern_detector import PatternDetector, PatternInfo

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
        from tools.muscle.code_review.pattern_detector import PatternDetector, PatternInfo

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
