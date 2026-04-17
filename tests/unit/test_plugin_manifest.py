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
import warnings
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "tools" / "muscle" / "plugin"
MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
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

    def test_commands_dir_exists(self) -> None:
        assert COMMANDS_DIR.is_dir(), f"Commands dir missing: {COMMANDS_DIR}"
        assert len(list(COMMANDS_DIR.glob("*.md"))) > 0

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
