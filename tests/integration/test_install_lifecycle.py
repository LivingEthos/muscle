"""
Integration tests for install, init, and uninstall lifecycle.

Tests CLI init command, ProjectManager.init_project,
settings reset, and the uninstall command.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from tools.muscle.cli import cli
from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager


class TestProjectManagerInit:
    """Tests ProjectManager.init_project with real filesystem."""

    def test_init_creates_muscle_directory(self, tmp_path: Path):
        """init_project should create .muscle/ with all subdirectories."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test-project", path=tmp_path, languages=["Python"])

        result = manager.init_project(config)

        assert result is True
        assert (tmp_path / ".muscle").is_dir()
        assert (tmp_path / ".muscle" / "skills").is_dir()
        assert (tmp_path / ".muscle" / "logs").is_dir()
        assert (tmp_path / ".muscle" / "config.yaml").exists()
        assert (tmp_path / ".muscle" / "CLAUDE.md").exists()
        assert (tmp_path / ".muscle" / "AGENT.md").exists()
        assert (tmp_path / ".muscle" / "MEMORY.md").exists()
        assert (tmp_path / ".muscle" / "strategy_kb.json").exists()

    def test_init_config_is_valid_json(self, tmp_path: Path):
        """config.yaml should contain valid JSON with project settings."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(
            name="my-project",
            path=tmp_path,
            languages=["Python", "TypeScript"],
            automation_level="hybrid",
            review_gate="warn",
            hooks_enabled=True,
            platform="claude-code",
        )

        manager.init_project(config)

        config_path = tmp_path / ".muscle" / "config.yaml"
        data = json.loads(config_path.read_text())
        assert data["project"]["name"] == "my-project"
        assert data["project"]["languages"] == ["Python", "TypeScript"]
        assert data["project"]["automation_level"] == "hybrid"
        assert data["project"]["review_gate"] == "warn"
        assert data["project"]["hooks_enabled"] is True
        assert data["project"]["platform"] == "claude-code"

    def test_init_memory_files_have_markers(self, tmp_path: Path):
        """Memory files should contain MUSCLE markers for safe update."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test", path=tmp_path)

        manager.init_project(config)

        claude_md = (tmp_path / ".muscle" / "CLAUDE.md").read_text()
        assert "MUSCLE_LEARNED_START" in claude_md
        assert "MUSCLE_LEARNED_END" in claude_md

        memory_md = (tmp_path / ".muscle" / "MEMORY.md").read_text()
        assert "MUSCLE_MEMORY_START" in memory_md
        assert "MUSCLE_MEMORY_END" in memory_md

    def test_init_strategy_kb_is_valid(self, tmp_path: Path):
        """strategy_kb.json should be a valid JSON with expected structure."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test", path=tmp_path)

        manager.init_project(config)

        kb_path = tmp_path / ".muscle" / "strategy_kb.json"
        data = json.loads(kb_path.read_text())
        assert data["version"] == "1.0"
        assert isinstance(data["strategies"], list)
        assert isinstance(data["evolution_history"], list)

    def test_init_idempotent(self, tmp_path: Path):
        """Running init twice should not overwrite existing files."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test", path=tmp_path)

        manager.init_project(config)

        # Write something to CLAUDE.md
        claude_md = tmp_path / ".muscle" / "CLAUDE.md"
        original = claude_md.read_text()
        claude_md.write_text(original + "\n# My custom content\n")

        # Init again
        manager.init_project(config)

        # Custom content should be preserved (init doesn't overwrite existing)
        content = claude_md.read_text()
        assert "My custom content" in content

    def test_init_sets_initialized_flag(self, tmp_path: Path):
        """ProjectConfig.initialized should be True after init."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test", path=tmp_path)

        assert config.initialized is False
        manager.init_project(config)
        assert config.initialized is True


class TestProjectManagerLoadConfig:
    """Tests loading config back from filesystem."""

    def test_load_config_roundtrip(self, tmp_path: Path):
        """Config should survive write -> load roundtrip."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(
            name="roundtrip-project",
            path=tmp_path,
            languages=["Go", "Rust"],
            automation_level="propose",
            review_gate="block-all",
            triggers=["review-gate", "pre-commit"],
            hooks_enabled=False,
            platform="opencode",
            cli_path="/usr/local/bin/muscle",
        )

        manager.init_project(config)
        loaded = manager.load_config(tmp_path)

        assert loaded is not None
        assert loaded.name == "roundtrip-project"
        assert loaded.languages == ["Go", "Rust"]
        assert loaded.automation_level == "propose"
        assert loaded.review_gate == "block-all"
        assert loaded.hooks_enabled is False
        assert loaded.platform == "opencode"
        assert loaded.cli_path == "/usr/local/bin/muscle"
        assert loaded.initialized is True

    def test_load_config_missing_project(self, tmp_path: Path):
        """Loading from a dir without .muscle/ should return None."""
        manager = ProjectManager(tmp_path)
        assert manager.load_config(tmp_path) is None

    def test_load_config_corrupt_json(self, tmp_path: Path):
        """Loading corrupt config should return None, not crash."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        (muscle_dir / "config.yaml").write_text("not valid json {{{")

        manager = ProjectManager(tmp_path)
        assert manager.load_config(tmp_path) is None


class TestProjectManagerUpdateConfig:
    """Tests updating config settings."""

    def test_update_hooks_enabled(self, tmp_path: Path):
        """update_muscle_config should persist hooks_enabled change."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test", path=tmp_path, hooks_enabled=True)
        manager.init_project(config)

        manager.update_muscle_config(tmp_path, hooks_enabled=False)

        loaded = manager.load_config(tmp_path)
        assert loaded is not None
        assert loaded.hooks_enabled is False

    def test_update_platform(self, tmp_path: Path):
        """update_muscle_config should persist platform change."""
        manager = ProjectManager(tmp_path)
        config = ProjectConfig(name="test", path=tmp_path, platform="auto")
        manager.init_project(config)

        manager.update_muscle_config(tmp_path, platform="claude-code")

        loaded = manager.load_config(tmp_path)
        assert loaded is not None
        assert loaded.platform == "claude-code"

    def test_update_nonexistent_config(self, tmp_path: Path):
        """update_muscle_config on missing .muscle/ should return False."""
        manager = ProjectManager(tmp_path)
        result = manager.update_muscle_config(tmp_path, platform="opencode")
        assert result is False


class TestProjectManagerDetection:
    """Tests project and CLI auto-detection."""

    def test_detect_python_project(self, tmp_path: Path):
        """Should detect Python from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        (tmp_path / ".git").mkdir()

        manager = ProjectManager(tmp_path)
        project = manager.detect_project()

        assert project is not None
        assert "Python" in project.languages

    def test_detect_javascript_project(self, tmp_path: Path):
        """Should detect JavaScript from package.json."""
        (tmp_path / "package.json").write_text('{"name": "test"}')
        (tmp_path / ".git").mkdir()

        manager = ProjectManager(tmp_path)
        project = manager.detect_project()

        assert project is not None
        assert any(lang in project.languages for lang in ["JavaScript", "TypeScript"])

    def test_detect_cli_location_from_env(self):
        """Should use MINIMAX_MUSCLE_PATH if set."""
        with patch.dict(os.environ, {"MINIMAX_MUSCLE_PATH": "/usr/bin/muscle"}):
            with patch("pathlib.Path.exists", return_value=True):
                result = ProjectManager.detect_cli_location()
                assert result == "/usr/bin/muscle"

    def test_detect_platform_opencode(self):
        """Should detect OpenCode from OPENCODE_SESSION env."""
        with patch.dict(os.environ, {"OPENCODE_SESSION": "1"}, clear=False):
            assert ProjectManager.detect_platform() == "opencode"

    def test_detect_platform_claude_code(self):
        """Should detect Claude Code from CLAUDE_CODE env."""
        env = os.environ.copy()
        env.pop("OPENCODE_SESSION", None)
        env["CLAUDE_CODE"] = "1"
        with patch.dict(os.environ, env, clear=True):
            assert ProjectManager.detect_platform() == "claude-code"


class TestCLIInitCommand:
    """Tests the `muscle init` CLI command."""

    def test_init_non_interactive(self, tmp_path: Path):
        """muscle init --non-interactive should complete without prompts."""
        runner = CliRunner()

        with patch("tools.muscle.tui.project_manager.ProjectManager.detect_project") as mock_detect:
            mock_detect.return_value = ProjectConfig(
                name="test-init",
                path=tmp_path,
                languages=["Python"],
            )

            result = runner.invoke(
                cli,
                ["init", "--non-interactive"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "initialized" in result.output.lower() or "MUSCLE" in result.output

    def test_init_creates_files(self, tmp_path: Path):
        """muscle init should create .muscle/ directory structure."""
        runner = CliRunner()

        with patch("tools.muscle.tui.project_manager.ProjectManager.detect_project") as mock_detect:
            mock_detect.return_value = ProjectConfig(
                name="file-test",
                path=tmp_path,
                languages=[],
            )

            result = runner.invoke(
                cli,
                ["init", "--non-interactive"],
            )

        assert result.exit_code == 0
        assert (tmp_path / ".muscle").exists()


class TestCLIUninstallCommand:
    """Tests the `muscle uninstall` CLI command."""

    def test_uninstall_removes_muscle_dir(self, tmp_path: Path):
        """muscle uninstall --force should remove .muscle/ directory."""
        runner = CliRunner()

        # Set up a project with .muscle/
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        (muscle_dir / "config.yaml").write_text("{}")
        (muscle_dir / "CLAUDE.md").write_text("# test")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("pathlib.Path.home", return_value=tmp_path / "home"):
                result = runner.invoke(
                    cli,
                    ["uninstall", "--force"],
                )

        assert result.exit_code == 0
        assert not muscle_dir.exists()

    def test_uninstall_keep_data(self, tmp_path: Path):
        """muscle uninstall --force --keep-data should preserve .muscle/."""
        runner = CliRunner()

        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        (muscle_dir / "config.yaml").write_text("{}")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("pathlib.Path.home", return_value=tmp_path / "home"):
                result = runner.invoke(
                    cli,
                    ["uninstall", "--force", "--keep-data"],
                )

        assert result.exit_code == 0
        assert muscle_dir.exists()  # Should be preserved

    def test_uninstall_removes_opencode_dir(self, tmp_path: Path):
        """muscle uninstall should also remove .opencode/ directory."""
        runner = CliRunner()

        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        opencode_dir = tmp_path / ".opencode"
        opencode_dir.mkdir()
        (opencode_dir / "opencode.json").write_text("{}")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("pathlib.Path.home", return_value=tmp_path / "home"):
                result = runner.invoke(
                    cli,
                    ["uninstall", "--force"],
                )

        assert result.exit_code == 0
        assert not opencode_dir.exists()

    def test_uninstall_no_installation(self, tmp_path: Path):
        """Uninstall on a dir without MUSCLE should warn gracefully."""
        runner = CliRunner()

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(cli, ["uninstall", "--force"])

        assert result.exit_code == 0
        assert "No MUSCLE installation" in result.output

    def test_uninstall_abort_without_force(self, tmp_path: Path):
        """Uninstall without --force should prompt and abort on 'n'."""
        runner = CliRunner()

        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            runner.invoke(
                cli,
                ["uninstall"],
                input="n\n",
            )

        assert muscle_dir.exists()  # Should NOT be removed


class TestCLISettingsReset:
    """Tests the settings reset command."""

    def test_settings_reset_with_force(self, tmp_path: Path):
        """settings reset --force should reset to defaults."""
        runner = CliRunner()

        manager = ProjectManager(tmp_path)
        config = ProjectConfig(
            name="test",
            path=tmp_path,
            platform="opencode",
            hooks_enabled=False,
        )
        manager.init_project(config)

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = runner.invoke(cli, ["settings", "reset", "--force"])

        assert result.exit_code == 0

        loaded = manager.load_config(tmp_path)
        assert loaded is not None
        assert loaded.platform == "auto"
        assert loaded.hooks_enabled is True


class TestInitUninstallRoundtrip:
    """Tests the full init -> use -> uninstall lifecycle."""

    def test_full_lifecycle(self, tmp_path: Path):
        """Init, verify structure, update settings, then uninstall."""
        runner = CliRunner()

        # Step 1: Init
        with patch("tools.muscle.tui.project_manager.ProjectManager.detect_project") as mock_det:
            mock_det.return_value = ProjectConfig(
                name="lifecycle-test",
                path=tmp_path,
                languages=["Python"],
            )
            result = runner.invoke(cli, ["init", "--non-interactive"])
            assert result.exit_code == 0

        # Step 2: Verify structure
        assert (tmp_path / ".muscle").exists()
        assert (tmp_path / ".muscle" / "config.yaml").exists()
        assert (tmp_path / ".muscle" / "CLAUDE.md").exists()

        # Step 3: Update settings
        manager = ProjectManager(tmp_path)
        manager.update_muscle_config(tmp_path, platform="claude-code")
        loaded = manager.load_config(tmp_path)
        assert loaded is not None
        assert loaded.platform == "claude-code"

        # Step 4: Uninstall
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            with patch("pathlib.Path.home", return_value=tmp_path / "home"):
                result = runner.invoke(cli, ["uninstall", "--force", "--keep-config"])
                assert result.exit_code == 0

        # Step 5: Verify cleaned up
        assert not (tmp_path / ".muscle").exists()
