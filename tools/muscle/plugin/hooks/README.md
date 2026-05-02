# Plugin hook layout

This directory exists because **Claude Code** and **Codex** disagree on where
to look for the plugin's hook configuration:

- `tools/muscle/plugin/hooks/hooks.json` — read by **Claude Code** (subdir
  convention; lifecycle events: `SessionStart`, `UserPromptSubmit`, `Stop`).
- `tools/muscle/plugin/hooks.json` — read by **Codex** (top-level
  convention; `PostToolUse` matcher for Write/Edit).

Do not "dedupe" these into a single file. Each host expects its own location
and only loads from there. The `muscle doctor` command checks both
(`tools/muscle/doctor.py:CLAUDE_HOOKS_PATH` / `CODEX_HOOKS_PATH`).
