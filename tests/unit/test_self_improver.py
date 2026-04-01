"""
Unit tests for self_improver.py
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.muscle.self_improver import SelfImprover, SessionOutcome


class TestSessionOutcome:
    def test_defaults(self):
        outcome = SessionOutcome(
            session_id="abc123",
            task="build auth",
            status="success",
            iterations=3,
            tokens=5000,
            duration_seconds=60.0,
            errors=[],
            strategy_used="Strategy A",
            success=True,
            timestamp="2026-03-31T00:00:00",
        )
        assert outcome.session_id == "abc123"
        assert outcome.status == "success"


class TestSelfImprover:
    @pytest.fixture
    def improver(self, tmp_path):
        log_path = tmp_path / "improvement_log.json"
        with patch.object(Path, "home", return_value=tmp_path):
            improver = SelfImprover()
            improver.IMPROVEMENT_LOG = log_path
            improver.SYSTEM_PROMPTS_DIR = tmp_path / "prompts"
            improver.outcomes = []
            yield improver

    def test_log_session(self, improver, tmp_path):
        improver.log_session(
            session_id="sess-1",
            task="build auth",
            status="success",
            iterations=2,
            tokens=1000,
            duration=30.0,
            errors=[],
            strategy="retry with backoff",
        )
        assert improver.IMPROVEMENT_LOG.exists()

    def test_analyze_patterns_no_data(self, improver):
        improver._outcomes = []
        result = improver.analyze_patterns()
        assert "error" in result or "total_sessions" in result

    def test_analyze_patterns_with_data(self, improver):
        improver.outcomes = [
            SessionOutcome(
                session_id="s1",
                task="build auth",
                status="success",
                iterations=1,
                tokens=500,
                duration_seconds=10.0,
                errors=[],
                strategy_used="Strategy A",
                success=True,
                timestamp="2026-03-31T00:00:00",
            ),
            SessionOutcome(
                session_id="s2",
                task="build logger",
                status="success",
                iterations=1,
                tokens=600,
                duration_seconds=12.0,
                errors=[],
                strategy_used="Strategy B",
                success=True,
                timestamp="2026-03-31T00:01:00",
            ),
        ]
        result = improver.analyze_patterns()
        assert "total_sessions" in result
        assert result["total_sessions"] == 2

    def test_export_data(self, improver, tmp_path):
        improver._outcomes = [
            SessionOutcome(
                session_id="s1",
                task="test",
                status="success",
                iterations=1,
                tokens=100,
                duration_seconds=5.0,
                errors=[],
                strategy_used=None,
                success=True,
                timestamp="2026-03-31T00:00:00",
            )
        ]
        export_path = tmp_path / "export.json"
        improver.export_data(str(export_path))
        assert export_path.exists()

    def test_import_data(self, improver, tmp_path):
        import_path = tmp_path / "import.json"
        import_path.write_text(
            json.dumps(
                {
                    "outcomes": [
                        {
                            "session_id": "s1",
                            "task": "imported task",
                            "status": "success",
                            "iterations": 1,
                            "tokens": 100,
                            "duration_seconds": 5.0,
                            "errors": [],
                            "strategy_used": None,
                            "success": True,
                            "timestamp": "2026-03-31T00:00:00",
                        }
                    ]
                }
            )
        )
        count = improver.import_data(str(import_path))
        assert count == 1

    def test_clear_log(self, improver, tmp_path):
        improver.outcomes = [
            SessionOutcome(
                session_id="s1",
                task="test",
                status="success",
                iterations=1,
                tokens=100,
                duration_seconds=5.0,
                errors=[],
                strategy_used=None,
                success=True,
                timestamp="2026-03-31T00:00:00",
            )
        ]
        improver.clear_log()
        assert len(improver.outcomes) == 0
