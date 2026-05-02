"""
Unit tests for the MUSCLE Claude Code plugin manifest (PL-03).

These tests enforce "filesystem is truth": the set of /muscle:<name>
commands advertised in plugin.json's ``description`` field must match
the set of ``*.md`` files under ``plugin/commands/`` exactly, with one
tolerated exception for ``optimize-host-docs`` which may be added by a
parallel Phase A change.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "tools" / "muscle" / "plugin"
ROOT_MARKETPLACE_PATH = Path(__file__).resolve().parents[2] / ".claude-plugin" / "marketplace.json"
MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_PATH = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
CLAUDE_HOOKS_PATH = PLUGIN_ROOT / "hooks" / "hooks.json"
CODEX_HOOKS_PATH = PLUGIN_ROOT / "hooks.json"
COMMANDS_DIR = PLUGIN_ROOT / "commands"

# Commands that may be introduced by a parallel (Phase A) change. If the
# filesystem does not yet have them, we emit a warning rather than fail.
TOLERATED_MISSING_COMMANDS: frozenset[str] = frozenset({"optimize-host-docs"})

_COMMAND_PATTERN = re.compile(r"/muscle:([a-z0-9][a-z0-9\-]*)")


def _filesystem_commands() -> set[str]:
    """Return the stems of every ``*.md`` under ``plugin/commands/``."""
    return {path.stem for path in COMMANDS_DIR.glob("*.md")}


def _manifest_commands() -> set[str]:
    """Return the set of /muscle:<name> stems listed in the manifest description."""
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    description = manifest.get("description", "")
    return set(_COMMAND_PATTERN.findall(description))


class TestPluginManifest:
    def test_manifest_exists_and_is_valid_json(self) -> None:
        assert MANIFEST_PATH.exists(), f"Manifest missing: {MANIFEST_PATH}"
        with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        assert "description" in manifest
        assert isinstance(manifest["description"], str)
        assert "install" not in manifest

    def test_claude_plugin_manifest_validates_with_claude_code(self) -> None:
        """Claude Code should accept the plugin manifest and nested hook bundle."""
        claude = shutil.which("claude")
        if claude is None:
            pytest.skip("Claude Code CLI is not installed")

        result = subprocess.run(
            [claude, "plugin", "validate", str(MANIFEST_PATH)],
            cwd=PLUGIN_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        assert result.returncode == 0, result.stdout

    def test_commands_dir_exists(self) -> None:
        assert COMMANDS_DIR.is_dir(), f"Commands dir missing: {COMMANDS_DIR}"
        assert len(list(COMMANDS_DIR.glob("*.md"))) > 0

    def test_marketplace_manifest_exists_and_is_valid_json(self) -> None:
        assert MARKETPLACE_PATH.exists(), f"Marketplace manifest missing: {MARKETPLACE_PATH}"
        with MARKETPLACE_PATH.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        assert manifest.get("name") == "muscle-marketplace"
        assert manifest.get("owner") == {
            "name": "MUSCLE Team",
            "email": "muscle@minimax.io",
        }
        assert manifest.get("metadata", {}).get("description")
        assert isinstance(manifest.get("plugins"), list)
        assert manifest["plugins"] == [
            {
                "name": "muscle",
                "description": (
                    "Self-learning code review for real projects: static analysis, semantic "
                    "review, project-local memory, doctor diagnostics, savings reports, "
                    "discovery, filters, model routing, context packs, and release-gate "
                    "evidence."
                ),
                "version": "0.1.0",
                "category": "development",
                "source": "./",
            }
        ]

    def test_root_marketplace_manifest_points_to_plugin_subdir(self) -> None:
        """The repository-level marketplace must install the plugin subdirectory."""
        assert ROOT_MARKETPLACE_PATH.exists(), (
            f"Root marketplace manifest missing: {ROOT_MARKETPLACE_PATH}"
        )
        with ROOT_MARKETPLACE_PATH.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)

        assert manifest.get("name") == "muscle-marketplace"
        plugins = manifest.get("plugins")
        assert isinstance(plugins, list)
        assert len(plugins) == 1
        plugin = plugins[0]
        assert plugin.get("name") == "muscle"
        assert plugin.get("source") == {
            "source": "git-subdir",
            "url": "https://github.com/LivingEthos/muscle.git",
            "path": "tools/muscle/plugin",
        }
        assert "savings" in plugin.get("description", "")
        assert "discovery" in plugin.get("description", "")
        assert "filters" in plugin.get("description", "")

    def test_root_marketplace_manifest_validates_with_claude_code(self) -> None:
        """Claude Code should accept the repository-level marketplace manifest."""
        claude = shutil.which("claude")
        if claude is None:
            pytest.skip("Claude Code CLI is not installed")

        result = subprocess.run(
            [claude, "plugin", "validate", str(ROOT_MARKETPLACE_PATH)],
            cwd=ROOT_MARKETPLACE_PATH.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        assert result.returncode == 0, result.stdout

    def test_claude_marketplace_manifest_validates_with_claude_code(self) -> None:
        """Claude Code should accept the marketplace manifest."""
        claude = shutil.which("claude")
        if claude is None:
            pytest.skip("Claude Code CLI is not installed")

        result = subprocess.run(
            [claude, "plugin", "validate", str(MARKETPLACE_PATH)],
            cwd=PLUGIN_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        assert result.returncode == 0, result.stdout

    def test_codex_manifest_exists_and_is_valid_json(self) -> None:
        assert CODEX_MANIFEST_PATH.exists(), f"Codex manifest missing: {CODEX_MANIFEST_PATH}"
        with CODEX_MANIFEST_PATH.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        assert manifest.get("name") == "muscle"
        assert manifest.get("skills") == "./skills/"
        interface = manifest.get("interface", {})
        assert interface.get("displayName") == "MUSCLE"
        assert interface.get("privacyPolicyURL", "").endswith("/docs/PRIVACY.md")
        assert interface.get("termsOfServiceURL", "").endswith("/docs/TERMS.md")
        for asset_key in ("composerIcon", "logo"):
            asset_path = PLUGIN_ROOT / str(interface.get(asset_key) or "")
            assert asset_path.exists(), f"Codex asset missing for {asset_key}: {asset_path}"

    def test_hook_files_exist(self) -> None:
        assert CLAUDE_HOOKS_PATH.exists(), f"Claude hooks missing: {CLAUDE_HOOKS_PATH}"
        assert CODEX_HOOKS_PATH.exists(), f"Codex hooks missing: {CODEX_HOOKS_PATH}"

    def test_every_manifest_command_has_a_file(self) -> None:
        """Every /muscle:<name> in the manifest must have a matching .md file.

        ``optimize-host-docs`` is tolerated if missing (Phase A parallel work).
        """
        fs_commands = _filesystem_commands()
        manifest_commands = _manifest_commands()

        missing = manifest_commands - fs_commands
        tolerated = missing & TOLERATED_MISSING_COMMANDS
        hard_missing = missing - TOLERATED_MISSING_COMMANDS

        if tolerated:
            warnings.warn(
                f"Manifest advertises {sorted(tolerated)} but the command "
                f"file(s) do not yet exist under {COMMANDS_DIR}. This is "
                "tolerated while Phase A is in flight.",
                stacklevel=2,
            )

        assert not hard_missing, (
            f"Manifest description advertises commands that do not exist on "
            f"the filesystem: {sorted(hard_missing)}"
        )

    def test_every_file_is_advertised_in_manifest(self) -> None:
        """Every ``*.md`` under ``plugin/commands/`` must appear in the manifest."""
        fs_commands = _filesystem_commands()
        manifest_commands = _manifest_commands()

        unadvertised = fs_commands - manifest_commands
        assert not unadvertised, (
            f"Command file(s) exist but are not advertised in the manifest "
            f"description: {sorted(unadvertised)}"
        )

    def test_no_stale_init_enable_disable_references(self) -> None:
        """init/enable/disable were removed; make sure they do not reappear."""
        manifest_commands = _manifest_commands()
        assert "init" not in manifest_commands
        assert "enable" not in manifest_commands
        assert "disable" not in manifest_commands


@pytest.mark.parametrize("command_stem", sorted(_filesystem_commands()))
def test_filesystem_command_is_advertised(command_stem: str) -> None:
    """Parametrized: each filesystem command appears in the manifest description."""
    manifest_commands = _manifest_commands()
    assert command_stem in manifest_commands, (
        f"/muscle:{command_stem} exists as {command_stem}.md but is not "
        "advertised in plugin.json description."
    )
