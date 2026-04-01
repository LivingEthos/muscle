"""
Unit tests for SCLE budget manager.
"""

import tempfile
from pathlib import Path

from tools.muscle.budget_manager import BudgetManager
from tools.muscle.types import BudgetMode


def test_budget_manager_unlimited():
    manager = BudgetManager(mode=BudgetMode.UNLIMITED)

    ok, reason = manager.check_budget(10000)
    assert ok is True
    assert reason == ""

    info = manager.get_budget_info()
    assert info.mode == BudgetMode.UNLIMITED
    assert info.total_tokens == 0


def test_budget_manager_fixed():
    manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=50000)

    ok, reason = manager.check_budget(10000)
    assert ok is True
    assert reason == "" or "WARNING" in reason

    info = manager.get_budget_info()
    assert info.total_tokens == 50000


def test_budget_manager_fixed_exceeded():
    manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=5000)

    ok, reason = manager.check_budget(10000)
    assert ok is False
    assert "Budget exceeded" in reason


def test_budget_manager_auto_loads_from_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        budget_file = Path(tmpdir) / "budget.json"
        budget_file.write_text('{"remaining_tokens": 100000}')

        manager = BudgetManager(
            mode=BudgetMode.AUTO,
            auto_budget_path=str(budget_file),
        )

        info = manager.get_budget_info()
        assert info.remaining_tokens == 100000


def test_budget_manager_save_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=50000)

        manager.check_budget(10000)

        save_path = Path(tmpdir) / "budget.json"
        manager.save_budget_state(str(save_path))

        assert save_path.exists()
        content = save_path.read_text()
        assert "remaining_tokens" in content
