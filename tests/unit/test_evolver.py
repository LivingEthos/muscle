"""
Unit tests for evolver.py
"""

from unittest.mock import Mock

import pytest

from tools.muscle.evolver import Evolver
from tools.muscle.m27_client import TokenUsage


class TestEvolver:
    @pytest.fixture
    def mock_client(self):
        client = Mock()
        client.chat.return_value = (
            '{"evolved_strategy": "Use a context manager for resource handling", "root_cause": "Resource not cleaned up properly", "confidence": 0.85}',
            TokenUsage(input_tokens=200, output_tokens=100),
        )
        return client

    def test_evolve_returns_strategy(self, mock_client):
        evolver = Evolver(mock_client)
        strategy, usage = evolver.evolve(
            task="handle file I/O safely",
            errors=["ResourceWarning: unclosed file"],
            previous_strategy=None,
        )
        assert isinstance(strategy, str)
        assert usage.total > 0

    def test_evolve_empty_errors(self, mock_client):
        evolver = Evolver(mock_client)
        strategy, usage = evolver.evolve(
            task="handle file I/O safely",
            errors=[],
            previous_strategy=None,
        )
        assert "No errors to analyze" in strategy

    def test_get_strategy_history(self, mock_client):
        evolver = Evolver(mock_client)
        evolver.evolve(
            task="task1",
            errors=["error1"],
            previous_strategy=None,
        )
        evolver.evolve(
            task="task2",
            errors=["error2"],
            previous_strategy=None,
        )
        history = evolver.get_strategy_history()
        assert len(history) == 2

    def test_retry_on_empty_response(self, mock_client):
        mock_client.chat.side_effect = [
            ("", TokenUsage(0, 0)),
            (
                '{"evolved_strategy": "Use retry logic", "root_cause": "Network flaky", "confidence": 0.9}',
                TokenUsage(input_tokens=100, output_tokens=50),
            ),
        ]
        evolver = Evolver(mock_client, max_retries=2)
        strategy, usage = evolver.evolve(
            task="API calls",
            errors=["ConnectionError"],
            previous_strategy=None,
        )
        assert len(strategy) > 0

    def test_evolve_streaming(self, mock_client):
        mock_client.chat_streaming.return_value = iter(
            [
                ("Step 1: ", TokenUsage(10, 5)),
                ("Step 2: ", TokenUsage(20, 10)),
                ('{"evolved_strategy": "Final strategy"}', TokenUsage(30, 15)),
            ]
        )
        evolver = Evolver(mock_client)
        chunks = list(
            evolver.evolve_streaming(task="test task", errors=["error"], previous_strategy=None)
        )
        assert len(chunks) >= 3
