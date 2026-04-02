"""
Unit tests for session_manager.py
"""

import json
from unittest.mock import patch

import pytest

from tools.muscle.loop_controller import LoopContext
from tools.muscle.session_manager import SessionManager
from tools.muscle.types import BudgetMode, IterationResult, LoopStats, RunConfig, SessionStatus


class TestSessionManager:
    @pytest.fixture
    def manager(self, tmp_path):
        return SessionManager(base_dir=str(tmp_path / "sessions"))

    def test_create_session(self, manager, tmp_path):
        config = RunConfig(task="Build a test")
        session_id = manager.create_session(config)
        assert isinstance(session_id, str)
        assert (tmp_path / "sessions" / session_id).exists()
        meta = json.loads((tmp_path / "sessions" / session_id / "meta.json").read_text())
        assert meta["working_dir"]
        assert meta["budget_tokens"] == 0

    def test_create_session_avoids_collisions(self, manager, tmp_path):
        class FixedDateTime:
            @classmethod
            def now(cls):
                class FixedNow:
                    def strftime(self, fmt):
                        return "20260401_123450"

                    def isoformat(self):
                        return "2026-04-01T12:34:50"

                return FixedNow()

        config = RunConfig(task="Same task")
        with patch("tools.muscle.session_manager.datetime", FixedDateTime):
            first_session_id = manager.create_session(config)
            second_session_id = manager.create_session(config)

        assert first_session_id != second_session_id
        assert second_session_id.endswith("_2")
        assert (tmp_path / "sessions" / first_session_id).exists()
        assert (tmp_path / "sessions" / second_session_id).exists()

    def test_invalid_session_id(self, manager):
        with pytest.raises(ValueError, match="Invalid session ID"):
            manager._sanitize_session_id("...")

    def test_save_iteration(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        iteration = IterationResult(
            iteration=1,
            success=False,
            errors=["SyntaxError"],
            token_cost=100,
            duration_seconds=1.5,
        )
        manager.save_iteration(session_id, iteration)
        assert (tmp_path / "sessions" / session_id / "iterations.jsonl").exists()

    def test_list_sessions(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        sessions = manager.list_sessions()
        assert len(sessions) >= 1
        assert sessions[0]["session_id"] == session_id

    def test_load_session(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        loaded = manager.load_session(session_id)
        assert loaded is not None
        assert loaded["session_id"] == session_id

    def test_load_nonexistent_session(self, manager):
        assert manager.load_session("nonexistent-id-xyz") is None

    def test_delete_session(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        assert manager.delete_session(session_id) is True
        assert not (tmp_path / "sessions" / session_id).exists()

    def test_delete_nonexistent_session(self, manager):
        assert manager.delete_session("nonexistent") is False

    def test_update_meta(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        manager._update_meta(session_id, {"status": "running", "tokens": 5000})
        meta_file = tmp_path / "sessions" / session_id / "meta.json"
        content = json.loads(meta_file.read_text())
        assert content["status"] == "running"

    def test_corrupted_iterations_file(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        iterations_file = tmp_path / "sessions" / session_id / "iterations.json"
        iterations_file.write_text("not valid json{{{")
        _iterations = manager.save_iteration(
            session_id,
            IterationResult(
                iteration=1,
                success=False,
                errors=["SyntaxError"],
                token_cost=100,
                duration_seconds=1.5,
            ),
        )
        assert True

    def test_get_session_artifacts(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        artifacts = manager.get_session_artifacts(session_id)
        assert artifacts is not None

    def test_sanitize_session_id_valid(self, manager):
        assert manager._sanitize_session_id("valid_id_123") == "valid_id_123"
        assert manager._sanitize_session_id("20260331_ab12") == "20260331_ab12"

    def test_sanitize_session_id_with_special_chars_sanitized(self, manager):
        assert manager._sanitize_session_id("session/with/slashes") == "sessionwithslashes"
        assert manager._sanitize_session_id("session.with.dots") == "sessionwithdots"

    def test_sanitize_session_id_empty(self, manager):
        with pytest.raises(ValueError, match="Invalid session ID"):
            manager._sanitize_session_id("")
        with pytest.raises(ValueError, match="Invalid session ID"):
            manager._sanitize_session_id("   ")

    def test_sanitize_session_id_starts_with_dot(self, manager):
        assert manager._sanitize_session_id(".hidden") == "hidden"

    def test_save_final_context_invalid_session_id(self, manager):
        ctx = LoopContext(
            session_id="",
            config=RunConfig(task="Test"),
            stats=LoopStats(
                status=SessionStatus.SUCCESS,
                total_iterations=1,
                total_tokens=100,
                total_duration_seconds=10.0,
            ),
        )
        manager.save_final_context(ctx)

    def test_save_final_context_session_not_exists(self, manager):
        ctx = LoopContext(
            session_id="nonexistent_session_xyz",
            config=RunConfig(task="Test"),
            stats=LoopStats(
                status=SessionStatus.SUCCESS,
                total_iterations=1,
                total_tokens=100,
                total_duration_seconds=10.0,
            ),
        )
        manager.save_final_context(ctx)

    def test_update_meta_invalid_session_id(self, manager):
        manager._update_meta("", {"status": "running"})

    def test_update_meta_corrupted_meta_file(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        meta_file = tmp_path / "sessions" / session_id / "meta.json"
        meta_file.write_text("not valid json{{{")
        manager._update_meta(session_id, {"status": "updated"})

    def test_load_session_invalid_id(self, manager):
        result = manager.load_session("")
        assert result is None

    def test_load_session_meta_file_corrupted(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        meta_file = tmp_path / "sessions" / session_id / "meta.json"
        meta_file.write_text("not valid json{{{")
        result = manager.load_session(session_id)
        assert result is None

    def test_load_session_meta_file_not_dict(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        meta_file = tmp_path / "sessions" / session_id / "meta.json"
        meta_file.write_text('"just a string"')
        result = manager.load_session(session_id)
        assert result is None

    def test_load_evolved_strategy_file_not_found(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        result = manager.load_evolved_strategy(session_id)
        assert result is None

    def test_load_evolved_strategy_corrupted_file(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        context_file = tmp_path / "sessions" / session_id / "context.json"
        context_file.write_text("not valid json{{{")
        result = manager.load_evolved_strategy(session_id)
        assert result is None

    def test_load_iterations(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        manager.save_iteration(
            session_id,
            IterationResult(
                iteration=1,
                success=False,
                errors=["SyntaxError"],
                warnings=["warning"],
                token_cost=100,
                duration_seconds=1.5,
                evolved_strategy="Retry with smaller scope",
            ),
        )

        iterations = manager.load_iterations(session_id)

        assert len(iterations) == 1
        assert iterations[0].iteration == 1
        assert iterations[0].token_cost == 100
        assert iterations[0].evolved_strategy == "Retry with smaller scope"

    def test_load_resume_context_extends_max_iterations_and_resolves_output_dir(
        self, manager, tmp_path
    ):
        output_dir = tmp_path / "workspace" / "generated"
        output_dir.mkdir(parents=True)
        config = RunConfig(
            task="Test resume",
            output_dir="generated",
            max_iterations=2,
            timeout_seconds=90,
            budget_tokens=500,
            budget_mode=BudgetMode.FIXED,
        )
        session_id = manager.create_session(config)
        meta_file = tmp_path / "sessions" / session_id / "meta.json"
        meta = json.loads(meta_file.read_text())
        meta["working_dir"] = str(tmp_path / "workspace")
        meta["total_tokens"] = 150
        meta_file.write_text(json.dumps(meta))
        manager.save_iteration(
            session_id,
            IterationResult(
                iteration=1,
                success=False,
                token_cost=100,
                duration_seconds=1.0,
                evolved_strategy="First strategy",
            ),
        )
        manager.save_iteration(
            session_id,
            IterationResult(
                iteration=2,
                success=False,
                token_cost=50,
                duration_seconds=2.0,
                evolved_strategy="Second strategy",
            ),
        )

        resume_ctx = manager.load_resume_context(session_id)

        assert resume_ctx is not None
        assert resume_ctx.current_iteration == 2
        assert resume_ctx.config.max_iterations == 4
        assert resume_ctx.config.output_dir == str(output_dir.resolve())
        assert resume_ctx.stats.total_tokens == 150
        assert resume_ctx.evolved_strategy == "Second strategy"

    def test_mark_resumed_updates_metadata(self, manager, tmp_path):
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)

        manager.mark_resumed(session_id)

        meta = json.loads((tmp_path / "sessions" / session_id / "meta.json").read_text())
        assert meta["status"] == SessionStatus.RUNNING.value
        assert meta["resume_count"] == 1
        assert "resumed_at" in meta

    def test_delete_session_invalid_id(self, manager):
        result = manager.delete_session("")
        assert result is False


class TestSessionManagerErrorHandling:
    """Error handling edge cases for SessionManager."""

    @pytest.fixture
    def manager(self, tmp_path):
        return SessionManager(base_dir=str(tmp_path / "sessions"))

    def test_load_evolved_strategy_context_file_not_dict(self, manager, tmp_path):
        """Test load_evolved_strategy returns None when context.json is not a dict."""
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        context_file = tmp_path / "sessions" / session_id / "context.json"
        context_file.write_text('"just a string"')
        result = manager.load_evolved_strategy(session_id)
        assert result is None

    def test_load_evolved_strategy_context_file_missing_evolved_strategy_key(
        self, manager, tmp_path
    ):
        """Test load_evolved_strategy returns None when evolved_strategy key is missing."""
        config = RunConfig(task="Test")
        session_id = manager.create_session(config)
        context_file = tmp_path / "sessions" / session_id / "context.json"
        context_file.write_text('{"session_id": "test", "task": "test"}')
        result = manager.load_evolved_strategy(session_id)
        assert result is None
