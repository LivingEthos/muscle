"""
Unit tests for evolver.py
"""

from unittest.mock import Mock

import pytest

from tools.muscle.evolver import Evolver, _build_evolver_prompt, _sanitize_for_prompt
from tools.muscle.m27_client import TokenUsage


class TestSanitizeForPrompt:
    def test_none_input(self):
        result = _sanitize_for_prompt(None)
        assert result == ""

    def test_non_string_input(self):
        result = _sanitize_for_prompt(123)
        assert result == "123"

    def test_empty_string(self):
        result = _sanitize_for_prompt("")
        assert result == ""

    def test_truncation_long_string(self):
        long_text = "a" * 3000
        result = _sanitize_for_prompt(long_text)
        assert len(result) <= 2000 + len("... [truncated]")

    def test_removes_null_bytes(self):
        result = _sanitize_for_prompt("hello\x00world")
        assert "\x00" not in result
        assert "helloworld" in result

    def test_removes_crlf(self):
        result = _sanitize_for_prompt("line1\r\nline2")
        assert "\r\n" not in result


class TestBuildEvolverPrompt:
    def test_empty_errors_returns_message(self):
        result = _build_evolver_prompt("task", [], None, 1, None)
        assert "Error:" in result

    def test_escapes_error_content(self):
        result = _build_evolver_prompt("task", ['Error "x" occurred'], None, 1, None)
        assert "Error" in result

    def test_with_previous_strategy(self):
        result = _build_evolver_prompt("task", ["Error"], "previous strategy", 1, None)
        assert "previous strategy" in result.lower() or "Previous" in result

    def test_truncates_task(self):
        long_task = "x" * 5000
        result = _build_evolver_prompt(long_task, ["Error"], None, 1, None)
        assert "Task:" in result


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
        evolver = Evolver(mock_client, use_kb=False)
        strategy, usage = evolver.evolve(
            task="handle file I/O safely",
            errors=["ResourceWarning: unclosed file"],
            previous_strategy=None,
        )
        assert isinstance(strategy, str)
        assert usage.total > 0

    def test_evolve_empty_errors(self, mock_client):
        evolver = Evolver(mock_client, use_kb=False)
        strategy, usage = evolver.evolve(
            task="handle file I/O safely",
            errors=[],
            previous_strategy=None,
        )
        assert "No errors to analyze" in strategy

    def test_get_strategy_history(self, mock_client):
        evolver = Evolver(mock_client, use_kb=False)
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
        evolver = Evolver(mock_client, max_retries=2, use_kb=False)
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
        evolver = Evolver(mock_client, use_kb=False)
        chunks = list(
            evolver.evolve_streaming(task="test task", errors=["error"], previous_strategy=None)
        )
        assert len(chunks) >= 3
