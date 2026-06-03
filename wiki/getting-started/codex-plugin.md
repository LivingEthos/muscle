# Codex Plugin Bundle

| Field | Value |
|---|---|
| Audience | Codex plugin operators and maintainers |
| Status | Bundle reference; install command intentionally host-dependent |
| Source of truth | [`tools/muscle/plugin/.codex-plugin/plugin.json`](../../tools/muscle/plugin/.codex-plugin/plugin.json), [`tools/muscle/plugin/hooks.json`](../../tools/muscle/plugin/hooks.json), [`tools/muscle/host_runtime.py`](../../tools/muscle/host_runtime.py) |

MUSCLE ships Codex plugin metadata in the same bundle as the Claude Code plugin.
The repo currently documents the bundle and validation path, not a universal
Codex install command.

## Bundle Files

```text
tools/muscle/plugin/.codex-plugin/plugin.json
tools/muscle/plugin/hooks.json
tools/muscle/plugin/assets/muscle-mark.svg
tools/muscle/plugin/commands/
tools/muscle/plugin/skills/
tools/muscle/plugin/agents/
```

## Codex Manifest

The manifest defines:

- `name`: `muscle`
- `version`: `0.1.0`
- `skills`: `./skills/`
- UI metadata under `interface`
- `Interactive` and `Write` capabilities
- icon and logo paths that point to `assets/muscle-mark.svg`

## Codex Hook

The root plugin hook file contains one event:

| Event | Matcher | Runtime command |
|---|---|---|
| `PostToolUse` | `Write|Edit` | `muscle _host-hook --platform codex --event post_write` |

This hook refreshes the generated active-review snapshot after write/edit
activity. It is intentionally narrower than the Claude hook set.

## Validation

If the local Codex build exposes a plugin validator, validate the Codex manifest
and root hook file directly. If it only exposes marketplace management, treat
Codex validation as skipped and use:

```bash
uv run pytest tests/unit/test_plugin_manifest.py tests/unit/test_plugin_hooks.py -q
uv run muscle doctor --json
```

Do not document a Codex install command until it is verified against the target
Codex release.

