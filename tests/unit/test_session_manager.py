"""
Unit tests for session_manager.py
"""

import json

import pytest

from tools.muscle.session_manager import SessionManager
from tools.muscle.types import IterationResult, RunConfig


class TestSessionManager:
    @pytest.fixture
    def manager(self, tmp_path):
        return SessionManager(base_dir=str(tmp_path / "sessions"))

    def test_create_session(self, manager, tmp_path):
        config = RunConfig(task="Build a test")
        session_id = manager.create_session(config)
        assert isinstance(session_id, str)
        assert (tmp_path / "sessions" / session_id).exists()

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
        assert (tmp_path / "sessions" / session_id / "iterations.json").exists()

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
