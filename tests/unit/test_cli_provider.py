"""Tests for the ``muscle provider`` group and ``muscle setup`` command.

Covers provider listing, status display (without leaking secret values),
persistence at global and project scope, unknown-name rejection, and the
``setup`` command in both non-interactive and interactive modes.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from muscle.cli import cli


def _init_project(root: Path) -> None:
    """Create the minimal ``.muscle/config.yaml`` that project scope requires."""
    muscle_dir = root / ".muscle"
    muscle_dir.mkdir(parents=True, exist_ok=True)
    (muscle_dir / "config.yaml").write_text(json.dumps({"project": {}}), encoding="utf-8")


def test_list_shows_registered_providers_with_billing_labels() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["provider", "list"])
    assert result.exit_code == 0, result.output
    for name in (
        "minimax-plan",
        "minimax-api",
        "claude-subscription",
        "codex-subscription",
        "anthropic-api",
        "openrouter-api",
    ):
        assert name in result.output
    assert "plan quota, $0 marginal" in result.output
    assert "MiniMax API dollars" in result.output
    assert "Agent SDK credit" in result.output
    assert "ChatGPT Codex subscription allowance" in result.output
    assert "Anthropic API dollars" in result.output
    assert "OpenRouter API dollars" in result.output
    assert "user-selected-gateway" in result.output


def test_show_displays_name_source_and_credential_presence_without_secret() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["provider", "show"],
            env={"MINIMAX_API_KEY": "super-secret-xyz"},
        )
    assert result.exit_code == 0, result.output
    assert "minimax-plan" in result.output
    assert "default" in result.output
    assert "present" in result.output
    assert "super-secret-xyz" not in result.output


def test_show_reports_missing_minimax_credential() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["provider", "show"],
            env={"MINIMAX_API_KEY": "", "ANTHROPIC_API_KEY": ""},
        )
    assert result.exit_code == 0, result.output
    assert "missing" in result.output
    assert "MINIMAX_API_KEY" in result.output


def test_use_global_persists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "global-config.json"
    monkeypatch.setattr("muscle.providers.GLOBAL_CONFIG_PATH", config_path)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["provider", "use", "anthropic-api", "--global"])
        assert result.exit_code == 0, result.output
        assert config_path.exists()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data["provider"] == "anthropic-api"

        from muscle.providers import resolve_provider

        profile, source = resolve_provider(Path.cwd())
        assert profile.name == "anthropic-api"
        assert source == "global"


def test_use_project_requires_muscle_dir() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["provider", "use", "minimax-api", "--project"])
    assert result.exit_code != 0
    assert "config.yaml" in result.output or "muscle init" in result.output
    assert "--global" in result.output


def test_use_project_persists_when_initialized() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        _init_project(Path.cwd())
        result = runner.invoke(cli, ["provider", "use", "minimax-api", "--project"])
        assert result.exit_code == 0, result.output
        data = json.loads((Path.cwd() / ".muscle" / "config.yaml").read_text(encoding="utf-8"))
        assert data["project"]["provider"] == "minimax-api"


def test_use_rejects_unknown_name() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["provider", "use", "does-not-exist"])
    assert result.exit_code != 0
    assert "minimax-plan" in result.output


def test_setup_non_interactive_global_writes_config_and_credential_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "global-config.json"
    monkeypatch.setattr("muscle.providers.GLOBAL_CONFIG_PATH", config_path)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["setup", "--non-interactive", "--provider", "anthropic-api", "--global"],
        )
    assert result.exit_code == 0, result.output
    assert config_path.exists()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["provider"] == "anthropic-api"
    # Credential status line is printed (no ANTHROPIC_API_KEY env -> missing).
    assert "ANTHROPIC_API_KEY" in result.output


def test_setup_non_interactive_without_provider_errors() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["setup", "--non-interactive", "--global"])
    assert result.exit_code != 0
    assert "provider" in result.output.lower()


def test_setup_without_project_config_falls_back_to_global_with_note(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "global-config.json"
    monkeypatch.setattr("muscle.providers.GLOBAL_CONFIG_PATH", config_path)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["setup", "--non-interactive", "--provider", "anthropic-api"],
        )
        assert not (Path.cwd() / ".muscle" / "config.yaml").exists()

    assert result.exit_code == 0, result.output
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["provider"] == "anthropic-api"
    assert "global scope" in result.output
    assert "muscle init" in result.output


def test_provider_setup_without_project_config_still_fails_project_scope() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["provider", "setup", "--non-interactive", "--provider", "anthropic-api"],
        )

    assert result.exit_code != 0
    assert "config.yaml" in result.output


def test_setup_codex_subscription_recommends_login_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "global-config.json"
    monkeypatch.setattr("muscle.providers.GLOBAL_CONFIG_PATH", config_path)
    runner = CliRunner()
    with (
        runner.isolated_filesystem(),
        patch("muscle.cli.provider.shutil.which", return_value=None),
    ):
        result = runner.invoke(
            cli,
            ["setup", "--non-interactive", "--provider", "codex-subscription", "--global"],
        )
    assert result.exit_code == 0, result.output
    assert "codex-subscription" in result.output
    assert "muscle provider login codex-subscription" in result.output


def test_provider_setup_alias_uses_same_provider_selection_flow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "global-config.json"
    monkeypatch.setattr("muscle.providers.GLOBAL_CONFIG_PATH", config_path)
    runner = CliRunner()
    with (
        runner.isolated_filesystem(),
        patch("muscle.cli.provider.shutil.which", return_value=None),
    ):
        result = runner.invoke(
            cli,
            [
                "provider",
                "setup",
                "--non-interactive",
                "--provider",
                "codex-subscription",
                "--global",
            ],
        )
    assert result.exit_code == 0, result.output
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["provider"] == "codex-subscription"
    assert "muscle provider login codex-subscription" in result.output


def test_provider_show_reports_codex_chatgpt_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSCLE_PROVIDER", "codex-subscription")
    runner = CliRunner()
    with (
        runner.isolated_filesystem(),
        patch("muscle.cli.provider.shutil.which", return_value="/usr/bin/codex"),
        patch("muscle.cli.provider.codex_login_status", return_value="Logged in using ChatGPT"),
    ):
        result = runner.invoke(cli, ["provider", "show"])
    assert result.exit_code == 0, result.output
    assert "codex-subscription" in result.output
    assert "ChatGPT login active" in result.output


def test_provider_login_codex_runs_official_login() -> None:
    runner = CliRunner()
    completed = subprocess.CompletedProcess(args=["codex", "login"], returncode=0)
    with (
        runner.isolated_filesystem(),
        patch("muscle.cli.provider.shutil.which", return_value="/usr/bin/codex"),
        patch("muscle.cli.provider.subprocess.run", return_value=completed) as mock_run,
        patch("muscle.cli.provider.codex_login_status", return_value="Logged in using ChatGPT"),
    ):
        result = runner.invoke(cli, ["provider", "login", "codex-subscription"])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once_with(["/usr/bin/codex", "login"])
    assert "ChatGPT login active" in result.output


def test_provider_login_codex_rejects_api_key_status() -> None:
    runner = CliRunner()
    completed = subprocess.CompletedProcess(args=["codex", "login"], returncode=0)
    with (
        runner.isolated_filesystem(),
        patch("muscle.cli.provider.shutil.which", return_value="/usr/bin/codex"),
        patch("muscle.cli.provider.subprocess.run", return_value=completed),
        patch("muscle.cli.provider.codex_login_status", return_value="Logged in using API key"),
    ):
        result = runner.invoke(cli, ["provider", "login", "codex-subscription"])
    assert result.exit_code != 0
    assert "API key" in result.output


def test_provider_login_codex_missing_binary_errors() -> None:
    runner = CliRunner()
    with (
        runner.isolated_filesystem(),
        patch("muscle.cli.provider.shutil.which", return_value=None),
    ):
        result = runner.invoke(cli, ["provider", "login", "codex-subscription"])
    assert result.exit_code != 0
    assert "codex" in result.output.lower()


def test_setup_interactive_selects_third_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "global-config.json"
    monkeypatch.setattr("muscle.providers.GLOBAL_CONFIG_PATH", config_path)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["setup", "--global"], input="3\n")
    assert result.exit_code == 0, result.output
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["provider"] == "claude-subscription"


def test_show_reports_cyber_safeguard_friction_for_opus_provider() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["provider", "show"], env={"MUSCLE_PROVIDER": "claude-subscription"}
        )
    assert result.exit_code == 0, result.output
    # "cyber-safeguard" is the distinctive prefix of the note; anchor on it alone.
    assert "cyber-safeguard" in result.output.lower()


def test_show_omits_cyber_safeguard_note_for_minimax_provider() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["provider", "show"], env={"MUSCLE_PROVIDER": "minimax-plan"})
    assert result.exit_code == 0, result.output
    assert "cyber-safeguard" not in result.output.lower()
    assert "friction" not in result.output.lower()
