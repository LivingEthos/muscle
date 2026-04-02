"""
Unit tests for SCLE budget manager.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

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


def test_budget_exceeded_does_not_modify_state():
    """Regression: check_budget must NOT deduct tokens when budget is exceeded."""
    manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=5000)

    ok, reason = manager.check_budget(10000)
    assert ok is False
    assert manager.fixed_limit == 5000, "fixed_limit should not change on rejection"

    info = manager.get_budget_info()
    assert info.remaining_tokens == 5000


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


def test_budget_info_usage_percent_zero_total():
    """Test usage_percent returns 0.0 when total_tokens is 0."""
    from tools.muscle.budget_manager import BudgetInfo

    info = BudgetInfo(
        total_tokens=0,
        used_tokens=0,
        remaining_tokens=0,
        mode=BudgetMode.FIXED,
    )
    assert info.usage_percent == 0.0


def test_budget_info_usage_percent_normal():
    """Test usage_percent calculation."""
    from tools.muscle.budget_manager import BudgetInfo

    info = BudgetInfo(
        total_tokens=100,
        used_tokens=50,
        remaining_tokens=50,
        mode=BudgetMode.FIXED,
    )
    assert info.usage_percent == 50.0


def test_check_budget_fixed_limit_zero_returns_true():
    """Test check_budget returns True when fixed_limit is 0."""
    manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=0)
    ok, reason = manager.check_budget(1000)
    assert ok is True
    assert reason == ""


def test_check_budget_fixed_limit_negative_returns_true():
    """Test check_budget returns True when fixed_limit is negative."""
    manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=-100)
    ok, reason = manager.check_budget(1000)
    assert ok is True
    assert reason == ""


def test_check_budget_warning_threshold_80_percent():
    """Test 80% warning threshold."""
    manager = BudgetManager(
        mode=BudgetMode.FIXED,
        fixed_limit=10000,
        warning_thresholds=(80.0, 95.0),
    )
    ok, reason = manager.check_budget(8000)
    assert "WARNING" in reason
    assert "80" in reason


def test_check_budget_warning_threshold_95_percent():
    """Test 95% warning threshold fires when usage >= 95%."""
    manager = BudgetManager(
        mode=BudgetMode.FIXED,
        fixed_limit=10000,
        warning_thresholds=(80.0, 95.0),
    )
    manager.check_budget(8000)
    ok, reason = manager.check_budget(1501)
    assert "WARNING" in reason
    assert "95" in reason


def test_check_budget_warning_threshold_once_per_threshold():
    """Test warning only issued once per threshold."""
    manager = BudgetManager(
        mode=BudgetMode.FIXED,
        fixed_limit=10000,
        warning_thresholds=(80.0, 95.0),
    )
    _, reason1 = manager.check_budget(8000)
    _, reason2 = manager.check_budget(1)
    _, reason3 = manager.check_budget(1)
    assert "WARNING" in reason1
    assert reason2 == ""
    assert reason3 == ""


def test_load_auto_budget_invalid_json():
    """Test _load_auto_budget with invalid JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        budget_file = Path(tmpdir) / "budget.json"
        budget_file.write_text("not valid json")

        manager = BudgetManager(
            mode=BudgetMode.AUTO,
            auto_budget_path=str(budget_file),
        )
        assert manager.fixed_limit == 0


def test_load_auto_budget_no_api_key_no_file():
    """Test _load_auto_budget falls back when no API key and no file (mode stays AUTO)."""
    with patch.dict("os.environ", {}, clear=True):
        with tempfile.TemporaryDirectory() as tmpdir:
            budget_file = Path(tmpdir) / "budget.json"
            budget_file.write_text('{"remaining_tokens": 100000}')

            with patch.object(Path, "exists", return_value=False):
                manager = BudgetManager(mode=BudgetMode.AUTO)
            assert manager.mode == BudgetMode.AUTO


def test_save_budget_state_unlimited_does_nothing():
    """Test save_budget_state returns early in unlimited mode."""
    manager = BudgetManager(mode=BudgetMode.UNLIMITED)
    manager.save_budget_state()


def test_save_budget_state_creates_parent_dirs():
    """Test save_budget_state creates parent directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=50000)
        manager.check_budget(10000)

        save_path = Path(tmpdir) / "subdir" / "nested" / "budget.json"
        manager.save_budget_state(str(save_path))

        assert save_path.exists()
        content = save_path.read_text()
        assert "remaining_tokens" in content


def test_estimate_iteration_cost_unlimited():
    """Test estimate_iteration_cost returns 0 in unlimited mode."""
    manager = BudgetManager(mode=BudgetMode.UNLIMITED)
    assert manager.estimate_iteration_cost(5000) == 0


def test_estimate_iteration_cost_fixed():
    """Test estimate_iteration_cost returns avg_output_tokens in fixed mode."""
    manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=50000)
    assert manager.estimate_iteration_cost(3000) == 3000
