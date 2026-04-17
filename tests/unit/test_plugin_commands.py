"""
Plugin command snapshot tests.

Verifies that all plugin command documentation files are well-formed and
consistent with the plugin.json description.
"""

from __future__ import annotations

import json
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
        """The plugin description must not list non-existent command groups.

        Command-level checks (cancel, result, etc.) are handled by
        test_plugin_manifest.py which enforces filesystem-truth — every
        /muscle:<name> in the manifest must have a matching .md file and
        vice versa.
        """
        desc = plugin_json["description"]
        # shadow group does not exist
        assert "muscle shadow" not in desc, (
            "plugin.json description must not list non-existent `muscle shadow` group"
        )

    def test_plugin_description_includes_long_eval(self, plugin_json: dict):
        """The plugin description should include long-eval-reports command."""
        desc = plugin_json["description"]
        assert "long-eval-reports" in desc, (
            "plugin.json description should include long-eval-reports command"
        )

    def test_plugin_description_includes_new_review_controls(self, plugin_json: dict):
        """The plugin description should include settings-review and long-eval-benchmark."""
        desc = plugin_json["description"]
        assert "settings-review" in desc
        assert "settings-model" in desc
        assert "long-eval-benchmark" in desc
        assert "memory-related" in desc
        assert "memory-import-project" in desc
        assert "memory-history" in desc
        assert "model-status" in desc
        assert "model-history" in desc
        assert "model-select" in desc
        assert "model-pack-install" in desc
        assert "model-pack-submit" in desc

    def test_plugin_description_repeats_project_local_authority(self, plugin_json: dict):
        """The plugin description should keep the project-first memory rule visible."""
        desc = plugin_json["description"].lower()
        assert "project-local memory always stays primary" in desc


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
        "settings-review",
        "settings-model",
        "memory-related",
        "memory-import-project",
        "memory-history",
        "model-status",
        "model-history",
        "model-select",
        "model-pack-install",
        "model-pack-submit",
        "status",
        "long-eval-benchmark",
        "long-eval-reports",
        "cancel",  # documented as unavailable
        "result",  # redirects to diagnosis
    }

    def test_all_expected_docs_exist(self, command_docs: dict[str, dict]):
        """All commands referenced in plugin.json should have doc files."""
        doc_names = set(command_docs.keys())
        missing = self.EXPECTED_COMMAND_DOCS - doc_names
        assert not missing, f"Missing expected plugin docs: {sorted(missing)}"

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
        ), "cancel.md must clearly state that `muscle cancel` does not exist"


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

    def test_setup_doc_describes_guided_growth_and_model_setup(self):
        """setup.md should describe guided init, conservative defaults, and model selection."""
        setup_doc = COMMANDS_DIR / "setup.md"
        if not setup_doc.exists():
            pytest.skip("setup.md does not exist")

        content = setup_doc.read_text()
        assert "muscle init" in content
        assert "--related-mode suggest" in content
        assert "--pack-mode suggest" in content
        assert "--canonical-model" in content
        assert "never auto-imported" in content or "never auto-imported" in content.lower()
        assert "defaults to `suggest`, not `auto`" in content


class TestSettingsShowCommandDoc:
    """settings-show.md should describe the expanded model and memory settings surface."""

    def test_settings_show_doc_mentions_model_and_related_fields(self):
        settings_doc = COMMANDS_DIR / "settings-show.md"
        if not settings_doc.exists():
            pytest.skip("settings-show.md does not exist")

        content = settings_doc.read_text()
        assert "related-project mode" in content.lower()
        assert "model-pack mode" in content.lower()
        assert "manual model override" in content.lower()
        assert "canonical model" in content.lower()
        assert "model identity source" in content.lower()


class TestNewParityDocs:
    """New plugin docs should cover the main post-discovery action paths."""

    def test_settings_model_doc_mentions_related_and_pack_modes(self):
        content = (COMMANDS_DIR / "settings-model.md").read_text()
        assert "--canonical-model" in content
        assert "--related-mode suggest" in content
        assert "--pack-mode suggest" in content
        assert "--clear" in content
        assert "project-local memory remains authoritative" in content.lower()

    def test_memory_import_project_doc_mentions_attach_and_unlink(self):
        content = (COMMANDS_DIR / "memory-import-project.md").read_text()
        assert "memory import-project" in content
        assert "--mode snapshot" in content
        assert "--mode attach" in content
        assert "memory linked" in content
        assert "memory unlink" in content

    def test_model_pack_install_doc_mentions_install_list_and_update(self):
        content = (COMMANDS_DIR / "model-pack-install.md").read_text()
        assert "model packs install" in content
        assert "--canonical-model" in content
        assert "--bundle-path" in content
        assert "model packs list" in content
        assert "model packs update" in content

    def test_memory_history_doc_mentions_recent_usage_and_related_context(self):
        content = (COMMANDS_DIR / "memory-history.md").read_text()
        assert "memory history" in content
        assert "lesson-usage" in content.lower() or "lesson usage" in content.lower()
        assert "memory related" in content

    def test_model_history_doc_mentions_recent_identity_events(self):
        content = (COMMANDS_DIR / "model-history.md").read_text()
        assert "model history" in content
        assert "manual override" in content.lower()
        assert "model status" in content
