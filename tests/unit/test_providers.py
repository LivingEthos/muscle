"""Tests for provider profiles and resolution order."""
import json
from pathlib import Path
from unittest import mock

import pytest

from muscle.providers import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    resolve_provider,
)


class TestRegistry:
    def test_exactly_four_providers(self):
        assert set(PROVIDERS) == {
            "minimax-plan", "minimax-api", "claude-subscription", "anthropic-api",
        }

    def test_profiles_shape(self):
        assert PROVIDERS["minimax-plan"].kind == "minimax-http"
        assert PROVIDERS["minimax-plan"].billing == "plan-quota"
        assert PROVIDERS["minimax-api"].billing == "api-dollars"
        assert PROVIDERS["claude-subscription"].kind == "claude-cli"
        assert PROVIDERS["claude-subscription"].billing == "agent-sdk-credit"
        assert PROVIDERS["claude-subscription"].model == "claude-opus-4-8"
        assert PROVIDERS["anthropic-api"].kind == "anthropic-http"
        assert PROVIDERS["anthropic-api"].model == "claude-opus-4-8"

    def test_registry_is_immutable(self):
        with pytest.raises(TypeError):
            PROVIDERS["x"] = PROVIDERS["minimax-plan"]  # type: ignore[index]


class TestResolution:
    def test_default_when_nothing_configured(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", tmp_path / "none.json"):
            profile, source = resolve_provider(project_path=tmp_path)
        assert profile.name == DEFAULT_PROVIDER == "minimax-plan"
        assert source == "default"

    def test_env_wins_over_everything(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MUSCLE_PROVIDER", "anthropic-api")
        _write_project_provider(tmp_path, "minimax-api")
        gcfg = tmp_path / "g.json"
        gcfg.write_text(json.dumps({"provider": "claude-subscription"}))
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", gcfg):
            profile, source = resolve_provider(project_path=tmp_path)
        assert profile.name == "anthropic-api"
        assert source == "env"

    def test_project_beats_global(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
        _write_project_provider(tmp_path, "minimax-api")
        gcfg = tmp_path / "g.json"
        gcfg.write_text(json.dumps({"provider": "claude-subscription"}))
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", gcfg):
            profile, source = resolve_provider(project_path=tmp_path)
        assert profile.name == "minimax-api"
        assert source == "project"

    def test_global_when_no_project(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
        gcfg = tmp_path / "g.json"
        gcfg.write_text(json.dumps({"provider": "claude-subscription"}))
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", gcfg):
            profile, source = resolve_provider(project_path=tmp_path)
        assert profile.name == "claude-subscription"
        assert source == "global"

    def test_unknown_env_provider_raises(self, monkeypatch):
        monkeypatch.setenv("MUSCLE_PROVIDER", "gpt-12")
        with pytest.raises(ValueError, match="gpt-12"):
            resolve_provider()

    def test_unknown_project_provider_raises(self, tmp_path, monkeypatch):
        # Fail closed: a corrupt config must not silently fall back (Critical Rules).
        monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
        _write_project_provider(tmp_path, "bogus")
        with pytest.raises(ValueError, match="bogus"):
            resolve_provider(project_path=tmp_path)


class TestSetGlobalProvider:
    def test_writes_provider_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
        gcfg = tmp_path / "config.json"
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", gcfg):
            from muscle.providers import set_global_provider

            set_global_provider("minimax-api")
        data = json.loads(gcfg.read_text())
        assert data["provider"] == "minimax-api"

    def test_merges_into_existing_keys(self, tmp_path):
        gcfg = tmp_path / "config.json"
        gcfg.write_text(json.dumps({"other_key": "preserved", "provider": "minimax-plan"}))
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", gcfg):
            from muscle.providers import set_global_provider

            set_global_provider("anthropic-api")
        data = json.loads(gcfg.read_text())
        assert data["provider"] == "anthropic-api"
        assert data["other_key"] == "preserved"

    def test_unknown_name_raises_before_write(self, tmp_path):
        gcfg = tmp_path / "config.json"
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", gcfg):
            from muscle.providers import set_global_provider

            with pytest.raises(ValueError, match="bad-name"):
                set_global_provider("bad-name")
        assert not gcfg.exists()


class TestSetProjectProvider:
    def test_writes_provider_into_config(self, tmp_path):
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        config_path = muscle_dir / "config.yaml"
        config_path.write_text(
            json.dumps({"project": {"name": "t", "path": str(tmp_path)}})
        )
        from muscle.providers import set_project_provider

        set_project_provider(tmp_path, "minimax-api")
        data = json.loads(config_path.read_text())
        assert data["project"]["provider"] == "minimax-api"

    def test_raises_when_config_missing(self, tmp_path):
        from muscle.providers import ProviderError, set_project_provider

        with pytest.raises(ProviderError, match="muscle init"):
            set_project_provider(tmp_path, "minimax-api")


class TestProjectConfigRoundTrip:
    def test_provider_survives_save_load(self, tmp_path):
        from muscle.tui.project_manager import ProjectConfig, ProjectManager

        manager = ProjectManager(base_path=tmp_path)
        config = ProjectConfig(
            name="test-project",
            path=tmp_path,
            languages=["python"],
            provider="minimax-api",
        )
        assert manager.init_project(config)
        loaded = manager.load_config(tmp_path)
        assert loaded is not None
        assert loaded.provider == "minimax-api"

    def test_old_config_without_provider_yields_none(self, tmp_path):
        from muscle.tui.project_manager import ProjectConfig, ProjectManager

        manager = ProjectManager(base_path=tmp_path)
        # Init without provider (old-style config)
        config = ProjectConfig(
            name="test-project",
            path=tmp_path,
            languages=["python"],
        )
        assert manager.init_project(config)

        # Manually strip 'provider' key from saved config to simulate old format
        config_path = tmp_path / ".muscle" / "config.yaml"
        data = json.loads(config_path.read_text())
        data["project"].pop("provider", None)
        config_path.write_text(json.dumps(data))

        loaded = manager.load_config(tmp_path)
        assert loaded is not None
        assert loaded.provider is None


class TestProviderProfileFrozen:
    def test_profile_is_frozen(self):
        from dataclasses import FrozenInstanceError

        with pytest.raises(FrozenInstanceError):
            PROVIDERS["minimax-plan"].name = "tampered"  # type: ignore[misc]


class TestYamlProjectConfig:
    def test_yaml_format_config_resolves_provider(self, tmp_path, monkeypatch):
        """A genuine-YAML config (not JSON) must resolve the provider correctly."""
        monkeypatch.delenv("MUSCLE_PROVIDER", raising=False)
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        (muscle_dir / "config.yaml").write_text(
            "project:\n  name: t\n  provider: minimax-api\n"
        )
        with mock.patch("muscle.providers.GLOBAL_CONFIG_PATH", tmp_path / "none.json"):
            profile, source = resolve_provider(project_path=tmp_path)
        assert profile.name == "minimax-api"
        assert source == "project"


def _write_project_provider(project_path: Path, name: str) -> None:
    muscle_dir = project_path / ".muscle"
    muscle_dir.mkdir(exist_ok=True)
    (muscle_dir / "config.yaml").write_text(
        json.dumps({"project": {"name": "t", "path": str(project_path), "provider": name}})
    )
