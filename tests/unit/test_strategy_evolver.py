"""
Unit tests for code_review/strategy_evolver.py
"""

from unittest.mock import MagicMock, Mock

import pytest

from tools.muscle.code_review.strategy_evolver import StrategyEvolver, StrategyResult


@pytest.fixture
def mock_strategy_kb():
    mock_kb = MagicMock()
    mock_kb.find_by_pattern.return_value = [Mock(solution_strategy="Original prompt")]
    return mock_kb


@pytest.fixture
def evolver(tmp_path, mock_strategy_kb):
    return StrategyEvolver(project_path=str(tmp_path), strategy_kb=mock_strategy_kb)


class TestStrategyEvolver:
    def test_init(self, tmp_path, mock_strategy_kb):
        ev = StrategyEvolver(project_path=str(tmp_path), strategy_kb=mock_strategy_kb)
        assert ev.project_path == tmp_path
        assert ev._strategy_results == {}

    def test_record_strategy_run_new(self, evolver):
        evolver.record_strategy_run(
            strategy_id="auth_fix",
            strategy_name="AuthStrategy",
            issues_found=5,
            fixes_succeeded=3,
            fixes_failed=1,
        )
        assert "auth_fix" in evolver._strategy_results
        result = evolver._strategy_results["auth_fix"]
        assert result.total_runs == 1
        assert result.successful_runs == 1

    def test_record_strategy_run_multiple(self, evolver):
        for _ in range(3):
            evolver.record_strategy_run(
                strategy_id="sql_fix",
                strategy_name="SQLStrategy",
                issues_found=2,
                fixes_succeeded=2,
                fixes_failed=0,
            )
        result = evolver._strategy_results["sql_fix"]
        assert result.total_runs == 3
        assert result.successful_runs == 3

    def test_record_strategy_run_all_failed(self, evolver):
        evolver.record_strategy_run(
            strategy_id="fail_fix",
            strategy_name="FailStrategy",
            issues_found=1,
            fixes_succeeded=0,
            fixes_failed=2,
        )
        result = evolver._strategy_results["fail_fix"]
        assert result.failed_runs == 1
        assert result.successful_runs == 0

    def test_calculate_effectiveness(self, evolver):
        result = StrategyResult(
            strategy_id="test",
            strategy_name="Test",
            total_runs=10,
            successful_runs=7,
            failed_runs=3,
            avg_fix_success_rate=0.8,
        )
        score = evolver._calculate_effectiveness(result)
        assert 0.0 <= score <= 1.0

    def test_should_evolve_false_insufficient_runs(self, evolver):
        evolver.record_strategy_run("id1", "name", 1, 1, 0)
        assert evolver.should_evolve("id1") is False

    def test_should_evolve_false_low_score(self, evolver):
        for _ in range(5):
            evolver.record_strategy_run("id2", "name", 1, 0, 5)
        assert evolver.should_evolve("id2") is False

    def test_should_evolve_true(self, evolver):
        for _ in range(5):
            evolver.record_strategy_run("id3", "name", 5, 5, 0)
        assert evolver.should_evolve("id3") is True

    def test_should_evolve_unknown_strategy(self, evolver):
        assert evolver.should_evolve("nonexistent") is False

    def test_evolve_strategy_not_found(self, evolver):
        result = evolver.evolve_strategy("nonexistent")
        assert result is None

    def test_evolve_strategy_calls_kb(self, evolver, mock_strategy_kb):
        evolver._strategy_results["test_strat"] = StrategyResult(
            strategy_id="test_strat",
            strategy_name="Test Strategy",
            total_runs=5,
            successful_runs=4,
            failed_runs=1,
            avg_fix_success_rate=0.8,
        )
        result = evolver.evolve_strategy("test_strat")
        assert result is not None
        assert "test_strat_evolved" in result["id"]
        mock_strategy_kb.add_strategy.assert_called_once()

    def test_get_top_strategies(self, evolver):
        for i in range(5):
            evolver.record_strategy_run(f"id{i}", f"Strategy{i}", 1, i, 1)
        top = evolver.get_top_strategies(limit=3)
        assert len(top) <= 3

    def test_get_strategy_recommendation(self, evolver):
        evolver.record_strategy_run("auth_fix", "AuthFixStrategy", 1, 1, 0)
        rec = evolver.get_strategy_recommendation("auth")
        assert rec == "auth_fix"

    def test_get_strategy_recommendation_no_match(self, evolver):
        evolver.record_strategy_run("other", "OtherStrategy", 1, 0, 1)
        rec = evolver.get_strategy_recommendation("nonexistent_category")
        assert rec is None

    def test_export_results(self, evolver):
        evolver.record_strategy_run("id1", "Name1", 3, 2, 1)
        evolver.record_strategy_run("id2", "Name2", 5, 5, 0)
        exported = evolver.export_results()
        assert "strategies" in exported
        assert "exported_at" in exported
        assert len(exported["strategies"]) == 2

    def test_strategy_result_dataclass(self):
        result = StrategyResult(
            strategy_id="test",
            strategy_name="Test",
            total_runs=10,
            successful_runs=8,
            failed_runs=2,
            avg_issues_found=3.5,
            avg_fix_success_rate=0.75,
            last_run="2026-03-31T00:00:00",
            effectiveness_score=0.85,
        )
        assert result.total_runs == 10
        assert result.effectiveness_score == 0.85
