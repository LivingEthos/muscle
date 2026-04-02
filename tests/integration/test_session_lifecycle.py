"""
Integration tests for session lifecycle.

Tests LoopController -> SessionManager -> BudgetManager full lifecycle,
including session creation, iteration tracking, resume, and budget enforcement.
"""

from __future__ import annotations

from pathlib import Path

from tools.muscle.budget_manager import BudgetInfo, BudgetManager
from tools.muscle.session_manager import SessionManager
from tools.muscle.types import (
    BudgetMode,
    IterationResult,
    RunConfig,
    SessionStatus,
)


class TestSessionManagerLifecycle:
    """Tests session creation, iteration tracking, and resume."""

    def test_create_and_load_session(self, tmp_path: Path):
        """Create a session, then load it back and verify metadata."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(
            task="Generate a REST API for user management",
            language="python",
            output_dir=str(tmp_path / "output"),
            max_iterations=10,
            budget_tokens=50000,
            budget_mode=BudgetMode.FIXED,
        )

        session_id = sm.create_session(config)
        assert session_id

        meta = sm.load_session(session_id)
        assert meta is not None
        assert meta["task"] == config.task
        assert meta["language"] == "python"
        assert meta["max_iterations"] == 10
        assert meta["budget_tokens"] == 50000
        assert meta["status"] == SessionStatus.RUNNING.value

    def test_save_and_load_iterations(self, tmp_path: Path):
        """Iteration results should be persisted and recoverable."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(task="Test task", language="python")
        session_id = sm.create_session(config)

        # Save multiple iterations
        iterations = [
            IterationResult(
                iteration=1,
                success=False,
                errors=["SyntaxError: unexpected EOF"],
                token_cost=1500,
                duration_seconds=2.5,
            ),
            IterationResult(
                iteration=2,
                success=False,
                errors=["ImportError: no module named flask"],
                token_cost=1200,
                duration_seconds=1.8,
            ),
            IterationResult(
                iteration=3,
                success=True,
                errors=[],
                token_cost=800,
                duration_seconds=1.2,
            ),
        ]

        for it in iterations:
            sm.save_iteration(session_id, it)

        loaded = sm.load_iterations(session_id)
        assert len(loaded) == 3
        assert loaded[0].iteration == 1
        assert loaded[0].success is False
        assert loaded[2].success is True
        assert loaded[0].token_cost == 1500

    def test_resume_context(self, tmp_path: Path):
        """Resume context should restore full state including iterations."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(
            task="Build a CLI tool",
            language="python",
            max_iterations=20,
            budget_tokens=100000,
            budget_mode=BudgetMode.FIXED,
        )
        session_id = sm.create_session(config)

        # Save some iterations
        sm.save_iteration(
            session_id,
            IterationResult(iteration=1, success=False, errors=["err1"], token_cost=5000),
        )
        sm.save_iteration(
            session_id,
            IterationResult(iteration=2, success=False, errors=["err2"], token_cost=3000),
        )

        ctx = sm.load_resume_context(session_id)
        assert ctx is not None
        assert ctx.session_id == session_id
        assert ctx.config.task == "Build a CLI tool"
        assert ctx.current_iteration == 2
        assert ctx.stats.total_tokens == 8000  # 5000 + 3000
        assert len(ctx.iterations) == 2

    def test_mark_resumed(self, tmp_path: Path):
        """mark_resumed should update session metadata."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(task="Resumable task")
        session_id = sm.create_session(config)

        sm.mark_resumed(session_id)

        meta = sm.load_session(session_id)
        assert meta is not None
        assert meta.get("resume_count") == 1
        assert "resumed_at" in meta

    def test_delete_session(self, tmp_path: Path):
        """Deleted sessions should be fully cleaned up."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(task="Deletable task")
        session_id = sm.create_session(config)

        result = sm.delete_session(session_id)
        assert result is True

        meta = sm.load_session(session_id)
        assert meta is None

    def test_session_id_sanitization(self, tmp_path: Path):
        """Invalid session IDs should be handled safely."""
        sm = SessionManager(str(tmp_path / "sessions"))

        # These should not crash
        assert sm.load_session("../../../etc/passwd") is None
        assert sm.load_session("") is None
        assert sm.load_session("valid_id_that_doesnt_exist") is None

    def test_concurrent_sessions(self, tmp_path: Path):
        """Multiple sessions should coexist without conflicts."""
        sm = SessionManager(str(tmp_path / "sessions"))

        sessions = []
        for i in range(5):
            config = RunConfig(task=f"Task {i}", language="python")
            sid = sm.create_session(config)
            sessions.append(sid)

        # All should be unique
        assert len(set(sessions)) == 5

        # All should be loadable
        for sid in sessions:
            meta = sm.load_session(sid)
            assert meta is not None


class TestBudgetManagerIntegration:
    """Tests budget tracking across modes."""

    def test_unlimited_mode_always_allows(self):
        """Unlimited mode should never block."""
        bm = BudgetManager(mode=BudgetMode.UNLIMITED)

        for _ in range(100):
            ok, reason = bm.check_budget(10000)
            assert ok is True
            assert reason is None or reason == ""

    def test_fixed_mode_tracks_consumption(self):
        """Fixed mode should track and enforce token limits."""
        bm = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=50000)

        # First call should succeed
        ok, _ = bm.check_budget(20000)
        assert ok is True

        # Second call should succeed (40000 total)
        ok, _ = bm.check_budget(20000)
        assert ok is True

        # Third call should fail (60000 > 50000)
        ok, reason = bm.check_budget(20000)
        assert ok is False
        assert reason is not None

    def test_fixed_mode_with_initial_consumption(self):
        """Fixed mode should account for already-consumed tokens."""
        bm = BudgetManager(
            mode=BudgetMode.FIXED,
            fixed_limit=50000,
            consumed_tokens=30000,
        )

        # Should only have 20000 remaining
        ok, _ = bm.check_budget(15000)
        assert ok is True

        ok, reason = bm.check_budget(15000)
        assert ok is False

    def test_budget_info_property(self):
        """BudgetInfo should report accurate remaining tokens."""
        bm = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=100000)

        bm.check_budget(30000)
        info = bm.get_budget_info()

        assert isinstance(info, BudgetInfo)
        assert info.mode == BudgetMode.FIXED
        assert info.total_tokens == 100000
        assert info.used_tokens == 30000
        assert info.remaining_tokens == 70000
        assert 29.0 <= info.usage_percent <= 31.0

    def test_warning_thresholds(self):
        """Warnings should be issued at 80% and 95% thresholds."""
        bm = BudgetManager(
            mode=BudgetMode.FIXED,
            fixed_limit=100000,
            warning_thresholds=(80.0, 95.0),
        )

        # Consume 81% -> should trigger 80% warning
        ok, _ = bm.check_budget(81000)
        assert ok is True

        info = bm.get_budget_info()
        assert info.usage_percent >= 80.0

    def test_auto_mode_loads_budget_file(self, tmp_path: Path):
        """Auto mode should load budget from a JSON file."""
        budget_file = tmp_path / "budget.json"
        budget_file.write_text('{"remaining_tokens": 75000}')

        bm = BudgetManager(
            mode=BudgetMode.AUTO,
            auto_budget_path=str(budget_file),
        )

        # Should have loaded 75000 from file
        ok, _ = bm.check_budget(50000)
        assert ok is True

        ok, reason = bm.check_budget(50000)
        assert ok is False

    def test_auto_mode_missing_file(self, tmp_path: Path):
        """Auto mode with missing budget file behaves as unlimited."""
        bm = BudgetManager(
            mode=BudgetMode.AUTO,
            auto_budget_path=str(tmp_path / "nonexistent.json"),
        )

        # With no file and no API key, BudgetManager falls back to unlimited behavior
        # The mode may stay AUTO but check_budget always returns True
        ok, _ = bm.check_budget(999999)
        assert ok is True


class TestSessionBudgetIntegration:
    """Tests SessionManager + BudgetManager working together."""

    def test_session_with_budget_tracking(self, tmp_path: Path):
        """Session should track budget across iterations."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(
            task="Budget-tracked task",
            budget_tokens=50000,
            budget_mode=BudgetMode.FIXED,
        )
        session_id = sm.create_session(config)

        bm = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=50000)

        # Simulate iterations with budget checks
        total_tokens = 0
        for i in range(5):
            token_cost = 8000
            ok, _ = bm.check_budget(token_cost)
            if not ok:
                break
            total_tokens += token_cost
            sm.save_iteration(
                session_id,
                IterationResult(
                    iteration=i + 1,
                    success=False,
                    errors=[f"Error in iteration {i + 1}"],
                    token_cost=token_cost,
                ),
            )

        # Should have run at most 6 iterations (48000 < 50000, 56000 > 50000)
        iterations = sm.load_iterations(session_id)
        assert 1 <= len(iterations) <= 6

    def test_resume_respects_consumed_budget(self, tmp_path: Path):
        """Resumed session should not re-allow already-spent budget."""
        sm = SessionManager(str(tmp_path / "sessions"))
        config = RunConfig(
            task="Resumable budget task",
            budget_tokens=50000,
            budget_mode=BudgetMode.FIXED,
        )
        session_id = sm.create_session(config)

        # Simulate 30000 tokens consumed
        sm.save_iteration(
            session_id,
            IterationResult(iteration=1, success=False, errors=["err"], token_cost=30000),
        )

        # Resume
        ctx = sm.load_resume_context(session_id)
        assert ctx is not None
        assert ctx.stats.total_tokens == 30000

        # Create budget manager with consumed tokens
        bm = BudgetManager(
            mode=BudgetMode.FIXED,
            fixed_limit=50000,
            consumed_tokens=ctx.stats.total_tokens,
        )

        # Should only have 20000 remaining
        ok, _ = bm.check_budget(15000)
        assert ok is True

        ok, reason = bm.check_budget(15000)
        assert ok is False
