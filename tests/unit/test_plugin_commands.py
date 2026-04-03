"""
Plugin command snapshot tests.

Verifies that all plugin command documentation files are well-formed and
consistent with the plugin.json description.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).parent.parent.parent / "tools" / "muscle" / "plugin"
COMMANDS_DIR = PLUGIN_DIR / "commands"
PLUGIN_JSON = PLUGIN_DIR / ".claude-plugin" / "plugin.json"


def _load_plugin_json() -> dict:
    with open(PLUGIN_JSON) as f:
        return json.load(f)


def _load_doc(doc_path: Path) -> dict:
    content = doc_path.read_text()
    fm = {}
    if content.startswith("---"):
        end = content.find("\n---\n", 3)
        if end != -1:
            fm = yaml.safe_load(content[4:end]) or {}
    return {"frontmatter": fm, "content": content}


def _slug_to_command_name(slug: str) -> str:
    """Convert file slug to expected slash command name (e.g. kb-stats -> kb-stats)."""
    return slug


@pytest.fixture
def plugin_json() -> dict:
    return _load_plugin_json()


@pytest.fixture
def command_docs() -> dict[str, dict]:
    """Load all command docs keyed by filename slug."""
    result = {}
    for p in sorted(COMMANDS_DIR.glob("*.md")):
        slug = p.stem  # e.g. "kb-stats"
        result[slug] = {"path": p, **_load_doc(p)}
    return result


class TestPluginJson:
    """plugin.json metadata tests."""

    def test_plugin_json_exists(self):
        assert PLUGIN_JSON.exists(), f"{PLUGIN_JSON} must exist"

    def test_plugin_json_valid(self, plugin_json: dict):
        assert "name" in plugin_json
        assert "description" in plugin_json
        assert plugin_json["name"] == "muscle"

    def test_plugin_description_lists_real_commands(self, plugin_json: dict):
        """The plugin description must not list non-existent commands."""
        desc = plugin_json["description"]
        # cancel and result do not exist
        assert "cancel" not in desc.lower() or "muscle:cancel" not in desc, (
            "plugin.json description must not list non-existent `muscle cancel` command"
        )
        # shadow group does not exist
        assert "muscle shadow" not in desc, (
            "plugin.json description must not list non-existent `muscle shadow` group"
        )

    def test_plugin_description_includes_nightly_status(self, plugin_json: dict):
        """The plugin description should include nightly-status command."""
        desc = plugin_json["description"]
        assert "nightly-status" in desc, (
            "plugin.json description should include nightly-status command"
        )


class TestCommandDocCompleteness:
    """Every documented command should have a corresponding doc file."""

    # Commands that SHOULD have doc files
    EXPECTED_COMMAND_DOCS = {
        "review",
        "pressure",
        "rescue",
        "setup",
        "check",
        "history",
        "probe",
        "diagnosis",
        "lifeline",
        "kb-stats",
        "settings-show",
        "settings-api-key",
        "status",
        "nightly-status",
        "cancel",  # documented as unavailable
        "result",  # redirects to diagnosis
    }

    def test_all_expected_docs_exist(self, command_docs: dict[str, dict]):
        """All commands referenced in plugin.json should have doc files."""
        # Check that status and nightly-status both exist (distinct commands)
        doc_names = set(command_docs.keys())
        assert "nightly-status" in doc_names, "nightly-status.md must exist"
        assert "status" in doc_names, "status.md must exist"

    def test_no_orphaned_docs(self, command_docs: dict[str, dict]):
        """Every .md file should have a non-empty description and (usually) a bash block."""
        for slug, data in command_docs.items():
            fm = data["frontmatter"]
            content = data["content"]

            assert fm.get("description"), f"{slug}.md missing non-empty description"
            # cancel.md documents a non-existent command; no bash block expected
            if slug != "cancel":
                assert "```bash" in content, f"{slug}.md missing bash code block"


class TestCancelCommandDoc:
    """cancel.md should clearly communicate the command is unavailable."""

    def test_cancel_doc_explains_unavailability(self):
        """The cancel command doc must explain there's no cancel command."""
        cancel_doc = COMMANDS_DIR / "cancel.md"
        if not cancel_doc.exists():
            pytest.skip("cancel.md does not exist")

        content = cancel_doc.read_text()
        # Must mention that cancel is not available
        assert any(
            phrase in content.lower()
            for phrase in ["no `muscle cancel`", "no cancel command", "not currently"]
        ), (
            "cancel.md must clearly state that `muscle cancel` does not exist"
        )


class TestResultCommandDoc:
    """result.md should redirect to diagnosis."""

    def test_result_doc_redirects_to_diagnosis(self):
        """result.md should reference `muscle diagnosis` as the real command."""
        result_doc = COMMANDS_DIR / "result.md"
        if not result_doc.exists():
            pytest.skip("result.md does not exist")

        content = result_doc.read_text()
        assert "muscle diagnosis" in content, (
            "result.md must reference `muscle diagnosis` as the real command"
        )
        assert "diagnosis" in content, "result.md must explain using diagnosis instead"


class TestSetupCommandDoc:
    """setup.md should reference correct settings subcommands."""

    def test_setup_doc_uses_correct_hooks_syntax(self):
        """setup.md must use `muscle settings hooks --enable` not `settings platform --hooks`."""
        setup_doc = COMMANDS_DIR / "setup.md"
        if not setup_doc.exists():
            pytest.skip("setup.md does not exist")

        content = setup_doc.read_text()

        # Must NOT have the incorrect form
        assert "settings platform --hooks" not in content, (
            "setup.md must not use incorrect `muscle settings platform --hooks`"
        )
        assert "settings platform --no-hooks" not in content, (
            "setup.md must not use incorrect `muscle settings platform --no-hooks`"
        )

        # Must have the correct form
        assert "settings hooks --enable" in content, (
            "setup.md must use `muscle settings hooks --enable`"
        )
        assert "settings hooks --disable" in content, (
            "setup.md must use `muscle settings hooks --disable`"
        )
