"""
Unit tests for tui/project_manager.py
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager


class TestProjectConfig:
    def test_defaults(self):
        config = ProjectConfig(
            name="test-project",
            path=Path("/fake/path"),
            languages=["python"],
            triggers=["*.py"],
        )
        assert config.name == "test-project"
        assert config.automation_level == "auto-fix"
        assert config.github_enabled is False


class TestProjectManager:
    @pytest.fixture
    def manager(self, tmp_path):
        return ProjectManager(base_path=tmp_path)

    def test_detect_project_no_git(self, manager, tmp_path):
        with patch.object(Path, "exists", return_value=False):
            result = manager.detect_project()
        assert result is None

    def test_init_project(self, manager, tmp_path):
        config = ProjectConfig(
            name="test-project",
            path=tmp_path,
            languages=["python"],
            triggers=["*.py"],
        )
        result = manager.init_project(config)
        assert result is True
        assert (tmp_path / ".muscle").exists()
        assert (tmp_path / ".muscle" / "skills").exists()
        assert (tmp_path / ".muscle" / "logs").exists()
        assert (tmp_path / ".muscle" / "config.yaml").exists()

    def test_create_memory_files(self, manager, tmp_path):
        muscle_dir = tmp_path / ".muscle"
        with patch.object(Path, "mkdir"):
            with patch.object(Path, "write_text"):
                manager._create_memory_files(muscle_dir)

    def test_init_knowledge_base(self, manager, tmp_path):
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir(exist_ok=True)
        manager._init_knowledge_base(muscle_dir)
        strategy_path = muscle_dir / "strategy_kb.json"
        assert strategy_path.exists()

        data = json.loads(strategy_path.read_text())
        assert data["version"] == "1.0"
        assert data["strategies"] == []

    def test_get_current_project(self, manager):
        with patch.object(Path, "exists", return_value=False):
            result = manager.get_current_project()
        assert result is None

    def test_load_config_missing(self, manager, tmp_path):
        with patch.object(Path, "exists", return_value=False):
            result = manager.load_config(tmp_path)
        assert result is None

    def test_find_all_projects(self, manager, tmp_path):
        with patch.object(Path, "home", return_value=tmp_path):
            with patch.object(Path, "exists", return_value=False):
                projects = manager.find_all_projects()
        assert isinstance(projects, list)

    def test_language_detection_python(self, manager, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "rglob", return_value=[tmp_path / "main.py"]):
                langs = manager._detect_languages(tmp_path)
        assert "Python" in langs

    def test_language_detection_javascript(self, manager, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        langs = manager._detect_languages(tmp_path)
        assert "JavaScript" in langs
