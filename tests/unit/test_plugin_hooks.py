"""
Hook configuration tests for Claude and Codex plugin bundles.
"""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "tools" / "muscle" / "plugin"
CLAUDE_HOOKS = PLUGIN_ROOT / "hooks" / "hooks.json"
CODEX_HOOKS = PLUGIN_ROOT / "hooks.json"


def test_claude_hooks_cover_expected_events() -> None:
    data = json.loads(CLAUDE_HOOKS.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})

    assert set(hooks.keys()) == {"SessionStart", "UserPromptSubmit", "Stop"}
    for event_name, entries in hooks.items():
        assert isinstance(entries, list)
        assert len(entries) == 1
        nested_hooks = entries[0].get("hooks", [])
        assert len(nested_hooks) == 1
        command_hook = nested_hooks[0]
        assert command_hook["type"] == "command"
        command = command_hook["command"]
        assert "muscle _host-hook --platform claude-code" in command
        if event_name == "SessionStart":
            assert "--event session_start" in command
            assert command_hook["timeout"] == 30
        elif event_name == "UserPromptSubmit":
            assert "--event user_prompt_submit" in command
            assert command_hook["timeout"] == 15
        else:
            assert "--event stop" in command
            assert command_hook["timeout"] == 150


def test_codex_hooks_only_cover_post_write() -> None:
    data = json.loads(CODEX_HOOKS.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})

    assert set(hooks.keys()) == {"PostToolUse"}
    entries = hooks["PostToolUse"]
    assert isinstance(entries, list)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["matcher"] == "Write|Edit"
    nested_hooks = entry.get("hooks", [])
    assert len(nested_hooks) == 1
    assert "muscle _host-hook --platform codex --event post_write" in nested_hooks[0]["command"]
