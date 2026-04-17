"""
CLI documentation smoke tests for plugin command docs.

Verifies that all .md files in tools/muscle/plugin/commands/ reference real CLI
commands and do not document non-existent commands like `muscle shadow *`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

# Top-level CLI command names (from cli.py)
TOP_LEVEL_COMMANDS = {
    "init",
    "tui",
    "run",
    "review",
    "history",
    "resume",
    "abort",
    "check",
    "probe",
    "diagnosis",
    "lifeline",
    "uninstall",
    "enable",
    "disable",
    "status",
}

# CLI subcommand groups (from cli.py)
CLI_GROUPS = {
    "kb",
    "cost",
    "improve",
    "long-eval",
    "memory",
    "model",
    "settings",
}

# Known subcommands per group (verified from cli.py)
CLI_SUBCOMMANDS = {
    "kb": {"stats", "export", "import", "clear", "knowledge-add"},
    "cost": {"stats", "clear"},
    "improve": {"report", "export", "import", "clear", "prompt"},
    "long-eval": {"run", "reports", "cleanup", "benchmark"},
    "memory": {"status", "history", "related", "import-project", "linked", "unlink"},
    "model": {"status", "history", "select", "packs"},
    "settings": {"show", "api-key", "hooks", "platform", "reset", "review", "model"},
}

# Commands documented but known NOT to exist in CLI
NONEXISTENT_TOKENS = {
    "shadow",  # No shadow group exists
    "cancel",  # No cancel command (no top-level cancel)
    "result",  # No result command (diagnosis is the replacement)
}


def _extract_bash_commands(content: str) -> list[str]:
    """Extract all bash code blocks from markdown content."""
    commands = []
    pattern = re.compile(r"```bash\s*\n(.*?)\n```", re.DOTALL)
    for match in pattern.finditer(content):
        block = match.group(1).strip()
        for line in block.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                commands.append(line)
    return commands


def _parse_frontmatter(content: str) -> dict | None:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith("---"):
        return None
    end = content.find("\n---\n", 3)
    if end == -1:
        return None
    try:
        return yaml.safe_load(content[4:end])
    except Exception:
        return None


COMMANDS_DIR = Path(__file__).parent.parent.parent / "tools" / "muscle" / "plugin" / "commands"


class TestPluginDocsReferenceRealCommands:
    """Every bash code block in plugin docs must reference a real CLI command."""

    @pytest.mark.parametrize("doc_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_no_shadow_commands(self, doc_file: Path):
        """Docs must not reference `muscle shadow *` - shadow group does not exist."""
        content = doc_file.read_text()
        shadow_refs = re.findall(r"muscle\s+shadow\s+\w+", content)
        assert not shadow_refs, (
            f"{doc_file.name} references non-existent `muscle shadow` commands: "
            f"{shadow_refs}. Use `muscle probe` and `muscle diagnosis` instead."
        )

    @pytest.mark.parametrize("doc_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_no_nonexistent_commands(self, doc_file: Path):
        """Docs must not reference known-non-existent top-level commands."""
        content = doc_file.read_text()
        for token in NONEXISTENT_TOKENS:
            pattern = re.compile(rf"muscle\s+{token}\b")
            matches = pattern.findall(content)
            assert not matches, (
                f"{doc_file.name} references non-existent CLI command `muscle {token}`: {matches}"
            )

    @pytest.mark.parametrize("doc_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_all_cli_commands_exist(self, doc_file: Path):
        """Every `muscle <cmd>` invocation in docs must be a real CLI command."""
        content = doc_file.read_text()
        commands = _extract_bash_commands(content)

        errors = []
        for cmd in commands:
            # Strip leading `muscle ` and any flags/job-id args
            stripped = cmd.replace("muscle ", "").strip()
            parts = stripped.split()
            if not parts:
                continue

            top = parts[0]
            if top in NONEXISTENT_TOKENS:
                errors.append(f"`{cmd}` -> references non-existent command `{top}`")
                continue

            if top not in TOP_LEVEL_COMMANDS and top not in CLI_GROUPS:
                errors.append(f"`{cmd}` -> unknown top-level command or group `{top}`")
                continue

            # If it's a group subcommand, verify the subcommand exists
            if len(parts) > 1 and top in CLI_GROUPS:
                sub = parts[1]
                known = CLI_SUBCOMMANDS.get(top, set())
                if known and sub not in known:
                    errors.append(
                        f"`{cmd}` -> unknown subcommand `muscle {top} {sub}` "
                        f"(known: {sorted(known)})"
                    )

        assert not errors, f"{doc_file.name} has CLI command errors:\n" + "\n".join(errors)


class TestPluginDocsFrontmatter:
    """Plugin command docs must have valid frontmatter."""

    @pytest.mark.parametrize("doc_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_has_frontmatter(self, doc_file: Path):
        """Each command doc must have YAML frontmatter."""
        content = doc_file.read_text()
        assert content.startswith("---"), (
            f"{doc_file.name} missing YAML frontmatter (must start with ---)"
        )

    @pytest.mark.parametrize("doc_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_frontmatter_has_description(self, doc_file: Path):
        """Frontmatter must have a `description` field."""
        content = doc_file.read_text()
        fm = _parse_frontmatter(content)
        assert fm is not None, f"{doc_file.name} has invalid YAML frontmatter"
        assert "description" in fm, f"{doc_file.name} frontmatter missing `description` field"
        assert fm["description"], f"{doc_file.name} `description` must not be empty"

    @pytest.mark.parametrize("doc_file", sorted(COMMANDS_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_has_bash_code_block(self, doc_file: Path):
        """Each command doc must have at least one bash code block.

        Exception: cancel.md documents a non-existent command, so it has no bash block.
        """
        if doc_file.name == "cancel.md":
            pytest.skip("cancel.md documents a non-existent command; no bash block expected")
        content = doc_file.read_text()
        blocks = re.findall(r"```bash\s*\n.*?\n```", content, re.DOTALL)
        assert blocks, f"{doc_file.name} must have at least one ```bash code block"
