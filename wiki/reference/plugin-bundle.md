# Plugin Bundle

| Field | Value |
|---|---|
| Audience | Plugin maintainers and release operators |
| Status | Current bundle inventory |
| Source of truth | [`src/muscle/plugin/`](../../src/muscle/plugin/), [`tests/unit/test_plugin_manifest.py`](../../tests/unit/test_plugin_manifest.py), [`tests/unit/test_plugin_docs.py`](../../tests/unit/test_plugin_docs.py), [`tests/unit/test_plugin_hooks.py`](../../tests/unit/test_plugin_hooks.py) |

The plugin bundle is shared across Claude Code and Codex-style hosts. Both hosts
reuse the same commands, agents, skills, and assets.

## Bundle Tree

```text
src/muscle/plugin/
  .claude-plugin/
    plugin.json
    marketplace.json
  .codex-plugin/
    plugin.json
  commands/
  agents/
    rescue_agent.md
    verification_agent.md
  skills/
    code-review/
      SKILL.md
  hooks/
    hooks.json
  hooks.json
  assets/
    muscle-mark.svg
```

## Claude Files

| File | Purpose |
|---|---|
| `.claude-plugin/plugin.json` | Claude plugin manifest and advertised command list. |
| `.claude-plugin/marketplace.json` | Nested marketplace manifest with local `source: "./"`. |
| `hooks/hooks.json` | Claude hook events and timeouts. |
| repository `.claude-plugin/marketplace.json` | Git-subdir marketplace entry for `src/muscle/plugin`. |

## Codex Files

| File | Purpose |
|---|---|
| `.codex-plugin/plugin.json` | Codex manifest, interface metadata, skill path, capabilities, asset references. |
| `hooks.json` | Codex root hook file for `PostToolUse` write/edit refresh. |
| `assets/muscle-mark.svg` | Shared composer icon and logo. |

## Shared Files

| Directory | Purpose |
|---|---|
| `commands/` | Slash command markdown docs. |
| `agents/` | Rescue and verification helper agents. |
| `skills/code-review/` | Model-invoked code review skill. |

## Bundle Validation

```bash
uv run pytest tests/unit/test_plugin_manifest.py tests/unit/test_plugin_docs.py tests/unit/test_plugin_hooks.py -q
uv build --out-dir /tmp/muscle-dist
python -m zipfile -l /tmp/muscle-dist/*.whl | rg 'plugin|savings|discover|filters'
uv run muscle doctor --json
```

If Claude Code is installed:

```bash
claude plugin validate src/muscle/plugin/.claude-plugin/plugin.json
claude plugin validate src/muscle/plugin/.claude-plugin/marketplace.json
claude plugin validate .claude-plugin/marketplace.json
```

