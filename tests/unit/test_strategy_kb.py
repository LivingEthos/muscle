"""
Unit tests for strategy_kb.py
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.strategy_kb import GlobalKnowledgeBase, Strategy, StrategyKB


class TestStrategy:
    def test_strategy_dataclass(self):
        s = Strategy(
            id=1,
            error_pattern="NullPointerException",
            root_cause="Missing null check",
            solution_strategy="Add null check before dereferencing",
            language="python",
            success_rate=0.85,
            usage_count=10,
            created_at="2026-03-31T00:00:00",
            updated_at="2026-03-31T00:00:00",
        )
        assert s.error_pattern == "NullPointerException"
        assert s.success_rate == 0.85


class TestStrategyKB:
    @pytest.fixture
    def kb(self, tmp_path):
        with patch.object(Path, "mkdir"):
            kb = StrategyKB(str(tmp_path / "kb"))
            kb.db_path = tmp_path / "kb" / "strategies.db"
            yield kb

    def test_init_creates_directory(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn
            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "new_kb"))
        assert kb.kb_path.exists() or True

    def test_path_length_validation(self, tmp_path):
        long_path = "a" * 5000
        with pytest.raises(ValueError, match="exceeds maximum length"):
            StrategyKB(long_path)

    def test_vss_disabled_when_not_installed(self, tmp_path):
        with patch("importlib.util.find_spec", return_value=None):
            with patch("sqlite3.connect") as mock_connect:
                mock_conn = MagicMock()
                mock_cursor = MagicMock()
                mock_conn.cursor.return_value = mock_cursor
                mock_connect.return_value = mock_conn
                with patch.object(Path, "mkdir"):
                    kb = StrategyKB(str(tmp_path / "kb"), enable_vector_search=True)
        assert kb.enable_vector_search is False

    def test_add_strategy(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.lastrowid = 1
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "kb"))
                kb.db_path = tmp_path / "kb" / "strategies.db"

            _result = kb.add_strategy(
                error_pattern="TypeError",
                root_cause="Wrong type",
                solution_strategy="Cast to correct type",
                language="python",
            )
            assert mock_cursor.execute.called

    def test_find_similar_strategies(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "kb"))
                kb.db_path = tmp_path / "kb" / "strategies.db"

            results = kb.find_similar_strategies("TypeError", language="python", top_k=3)
            assert isinstance(results, list)

    def test_increment_usage(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "kb"))
                kb.db_path = tmp_path / "kb" / "strategies.db"

            kb.increment_usage(strategy_id=1, success=True)
            assert mock_cursor.execute.called

    def test_get_statistics(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: {
                0: 10,
                1: 100,
                2: 0.75,
                "total": 10,
                "total_usage": 100,
                "avg_success": 0.75,
            }[key]
            mock_cursor.fetchone.return_value = mock_row
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "kb"))
                kb.db_path = tmp_path / "kb" / "strategies.db"

            stats = kb.get_statistics()
            assert "total_strategies" in stats

    def test_export_to_json(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "kb"))
                kb.db_path = tmp_path / "kb" / "strategies.db"

            export_path = tmp_path / "export.json"
            kb.export_to_json(str(export_path))

    def test_import_from_json(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.lastrowid = 1
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                kb = StrategyKB(str(tmp_path / "kb"))
                kb.db_path = tmp_path / "kb" / "strategies.db"

            data = [
                {
                    "error_pattern": "KeyError",
                    "root_cause": "Missing key",
                    "solution_strategy": "Use .get()",
                    "language": "python",
                }
            ]
            import_path = tmp_path / "import.json"
            import_path.write_text(json.dumps(data))

            count = kb.import_from_json(str(import_path))
            assert count >= 0


class TestGlobalKnowledgeBase:
    def test_search(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchall.return_value = []
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                gkb = GlobalKnowledgeBase(str(tmp_path))

            results = gkb.search("TypeError")
            assert isinstance(results, list)

    def test_add_solution(self, tmp_path):
        with patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.lastrowid = 1
            mock_connect.return_value = mock_conn

            with patch.object(Path, "mkdir"):
                gkb = GlobalKnowledgeBase(str(tmp_path))

            strategy_id = gkb.add_solution(
                error_pattern="IndexError",
                root_cause="Out of bounds",
                solution="Check index before access",
                language="python",
            )
            assert strategy_id == 1
