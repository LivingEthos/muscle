"""Tests for token budget management."""

from __future__ import annotations

import pytest

from tools.muscle.exceptions import BudgetExceededError
from tools.muscle.llm.token_budget import BudgetConfig, TokenBudget, TokenUsage


def test_budget_config_defaults():
    config = BudgetConfig()
    assert config.max_tokens_per_minute == 100_000
    assert config.max_tokens_per_hour == 1_000_000
    assert config.max_tokens_per_day == 10_000_000
    assert config.max_cost_per_day == 50.0
    assert config.warning_threshold == 0.8
    assert config.hard_limit is True


def test_budget_record_usage():
    budget = TokenBudget()
    usage = budget.record_usage(
        prompt_tokens=10, completion_tokens=5, provider="openai", model="gpt-4o"
    )
    assert isinstance(usage, TokenUsage)
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 5
    assert usage.total_tokens == 15
    assert usage.provider == "openai"


def test_budget_check_within_limits():
    budget = TokenBudget()
    status = budget.check_budget(estimated_tokens=100)
    assert status["can_proceed"] is True
    assert status["limits_hit"] == []


def test_budget_check_exceeds_hard_limit():
    config = BudgetConfig(max_tokens_per_day=10, hard_limit=True)
    budget = TokenBudget(config=config)
    budget.record_usage(prompt_tokens=5, completion_tokens=5)
    status = budget.check_budget(estimated_tokens=10)
    assert status["can_proceed"] is False
    assert "day_tokens" in status["limits_hit"]


def test_budget_reserve_and_commit():
    budget = TokenBudget()
    rid = budget.reserve_tokens(estimated_tokens=100)
    assert rid in budget._reservations
    assert budget._reservations[rid] == 100

    usage = budget.commit_reservation(
        rid, prompt_tokens=50, completion_tokens=30, provider="openai"
    )
    assert rid not in budget._reservations
    assert usage.prompt_tokens == 50
    assert usage.completion_tokens == 30


def test_budget_release_on_failure():
    budget = TokenBudget()
    rid = budget.reserve_tokens(estimated_tokens=100)
    assert rid in budget._reservations

    budget.release_reservation(rid)
    assert rid not in budget._reservations


def test_budget_reserve_raises_when_exceeded():
    config = BudgetConfig(max_tokens_per_minute=10, hard_limit=True)
    budget = TokenBudget(config=config)
    budget.record_usage(prompt_tokens=5, completion_tokens=5)
    with pytest.raises(BudgetExceededError):
        budget.reserve_tokens(estimated_tokens=10)


def test_budget_empty_config_allows_all_usage():
    """Test that zero-limit config blocks all usage when hard_limit=True."""
    config = BudgetConfig(
        max_tokens_per_minute=0,
        max_tokens_per_hour=0,
        max_tokens_per_day=0,
        hard_limit=True,
    )
    budget = TokenBudget(config=config)
    status = budget.check_budget(estimated_tokens=1)
    assert status["can_proceed"] is False
    assert "minute_tokens" in status["limits_hit"]


def test_budget_zero_tokens_commit():
    """Test that committing a reservation with 0 tokens works correctly."""
    budget = TokenBudget()
    rid = budget.reserve_tokens(estimated_tokens=100)
    usage = budget.commit_reservation(rid, prompt_tokens=0, completion_tokens=0)
    assert usage.total_tokens == 0
    assert usage.cost_usd == 0.0


def test_budget_cleanup_old_history():
    from datetime import UTC, datetime, timedelta

    budget = TokenBudget(max_history_entries=5)
    # Add old entry
    old_usage = TokenUsage(
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
        timestamp=datetime.now(UTC) - timedelta(days=31),
    )
    budget.usage_history.append(old_usage)
    budget.prune_history()  # public self-locking entry point
    assert len(budget.usage_history) == 0


def test_budget_estimate_cost():
    budget = TokenBudget()
    cost = budget.estimate_cost("openai", "gpt-4", prompt_tokens=1000, completion_tokens=500)
    assert cost > 0
    # gpt-4 rates: (0.03, 0.06)
    expected = (1000 / 1000) * 0.03 + (500 / 1000) * 0.06
    assert cost == pytest.approx(expected)


def test_budget_record_usage_concurrent_no_lost_updates():
    """CONCURRENCY: record_usage is self-locking, so N threads hammering it
    without ANY external lock must not lose appends to usage_history."""
    import threading

    # Generous limits + large history cap so nothing is pruned mid-run.
    config = BudgetConfig(
        max_tokens_per_minute=10**12,
        max_tokens_per_hour=10**12,
        max_tokens_per_day=10**12,
        max_cost_per_day=10**12,
    )
    budget = TokenBudget(config=config, max_history_entries=10**9)

    threads_count = 16
    per_thread = 200
    start = threading.Barrier(threads_count)

    def worker() -> None:
        start.wait()
        for _ in range(per_thread):
            budget.record_usage(prompt_tokens=1, completion_tokens=1)

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(budget.usage_history) == threads_count * per_thread
