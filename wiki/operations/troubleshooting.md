# Troubleshooting

| Field | Value |
|---|---|
| Audience | Operators, support agents, and maintainers |
| Status | Practical current-runbook guide |
| Source of truth | [`tools/muscle/doctor.py`](../../tools/muscle/doctor.py), [`tools/muscle/host_runtime.py`](../../tools/muscle/host_runtime.py), [`docs/release-notes-2026-05-01-plugin-readiness.md`](../../docs/release-notes-2026-05-01-plugin-readiness.md), [`tests/unit/test_plugin_docs.py`](../../tests/unit/test_plugin_docs.py) |

Start with `doctor`. It checks project initialization, enablement, platform,
CLI path, API key presence, manifests, hooks, command-doc parity, assets,
active-review freshness, hook-runtime state, model identity, and importer
availability.

```bash
muscle doctor
muscle doctor --refresh
muscle doctor --json
```

## Common Problems

| Symptom | Likely cause | Next command |
|---|---|---|
| Review exits with missing key | `MINIMAX_API_KEY` or `ANTHROPIC_API_KEY` is absent | `muscle settings api-key` |
| Slash command exists but CLI command fails | Command doc drifted from `cli.py` | `uv run pytest tests/unit/test_plugin_docs.py -q` |
| Manifest advertises missing command | Manifest/filesystem parity drift | `uv run pytest tests/unit/test_plugin_manifest.py -q` |
| Hook behavior is silent | Hook digest has not changed, project is not initialized, or runtime failed open | `muscle doctor --refresh` |
| Codex validation cannot run | Local Codex build lacks plugin validator | Treat as skipped and use `muscle doctor --json` |
| Shadow result missing | Job not completed or project-local DB has no record | `muscle probe`, then `muscle diagnosis` |
| JSON review output has progress text | Regression in stdout/stderr routing | `uv run pytest tests/unit/test_cli_review.py -q` |
| Model pack not applying | Canonical model unresolved or pack mode off | `muscle model status`, `muscle settings model` |

## Plugin Install Issues

For Claude Code marketplace install:

```text
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

For local plugin development:

```bash
uv sync --extra dev
claude --plugin-dir ./tools/muscle/plugin
```

Validate with:

```bash
claude plugin validate tools/muscle/plugin/.claude-plugin/plugin.json
claude plugin validate tools/muscle/plugin/.claude-plugin/marketplace.json
claude plugin validate .claude-plugin/marketplace.json
```

## Shadow Job State

Current code stores shadow jobs in project-local `project_memory.db`. If an old
doc or operator note mentions `~/.muscle/shadow_jobs.json`, verify against
current `ShadowBroker` code before acting on it.

## Fresh Environment Problems

If lint, type, or test tools are missing:

```bash
uv sync --extra dev
```

Then rerun the failing gate.

