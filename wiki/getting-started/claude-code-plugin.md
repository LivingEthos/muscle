# Claude Code Plugin

| Field | Value |
|---|---|
| Audience | Claude Code users and plugin maintainers |
| Status | Current bundle behavior |
| Source of truth | [`src/muscle/plugin/.claude-plugin/plugin.json`](../../src/muscle/plugin/.claude-plugin/plugin.json), [`src/muscle/plugin/.claude-plugin/marketplace.json`](../../src/muscle/plugin/.claude-plugin/marketplace.json), [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json), [`src/muscle/plugin/hooks/hooks.json`](../../src/muscle/plugin/hooks/hooks.json) |

The Claude Code plugin exposes `/muscle:*` slash commands, a code-review skill,
two helper agents, and lifecycle hooks. The plugin files live under
[`src/muscle/plugin/`](../../src/muscle/plugin/).

## Marketplace Install

Inside Claude Code:

```text
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

The repository-level marketplace manifest points at the `src/muscle/plugin`
git subdirectory. The nested marketplace manifest supports local bundle
validation and plugin development from the plugin root.

## Local Development

From a local checkout:

```bash
uv sync --extra dev
claude --plugin-dir ./src/muscle/plugin
```

## Claude Hook Events

| Event | Runtime command | Timeout |
|---|---|---|
| `SessionStart` | `muscle _host-hook --platform claude-code --event session_start` | 30s |
| `UserPromptSubmit` | `muscle _host-hook --platform claude-code --event user_prompt_submit` | 15s |
| `Stop` | `muscle _host-hook --platform claude-code --event stop` | 150s |

The hook runtime fails open so degraded hook behavior does not block Claude Code.

## Validation

Use the local Claude validator when available:

```bash
claude plugin validate src/muscle/plugin/.claude-plugin/plugin.json
claude plugin validate src/muscle/plugin/.claude-plugin/marketplace.json
claude plugin validate .claude-plugin/marketplace.json
```

Then run:

```bash
uv run pytest tests/unit/test_plugin_manifest.py tests/unit/test_plugin_docs.py tests/unit/test_plugin_hooks.py -q
uv run muscle doctor --json
```

