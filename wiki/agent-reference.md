# Agent Reference

| Field | Value |
|---|---|
| Audience | Coding agents continuing MUSCLE plugin work |
| Status | Current checkout orientation |
| Source of truth | [`tools/muscle/`](../tools/muscle/), [`tools/muscle/plugin/`](../tools/muscle/plugin/), [`tests/unit/test_plugin_manifest.py`](../tests/unit/test_plugin_manifest.py), [`tests/unit/test_plugin_docs.py`](../tests/unit/test_plugin_docs.py), [`tests/unit/test_plugin_hooks.py`](../tests/unit/test_plugin_hooks.py) |

Use this page when you need to continue plugin, docs, release, or runtime work
without re-learning the repo from scratch.

## First Principles

- The active package is `tools/muscle/`.
- The plugin is a wrapper around the CLI. Slash commands should map to real
  `muscle` commands.
- Project-local memory is authoritative. Related-project lessons and model packs
  are overlays.
- `project_memory.db` is the DB-first source of project evidence.
- `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, `.muscle/MEMORY.md`, and
  `.muscle/active-review.md` are bounded generated or compatibility surfaces.
- `tools/scle/` is legacy and should not drive current conclusions.

## Fast Orientation Order

1. Read [`README.md`](../README.md) for product and install surfaces.
2. Read [`docs/architecture.md`](../docs/architecture.md) for the current
   runtime map, then verify important claims against code.
3. Inspect [`tools/muscle/plugin/`](../tools/muscle/plugin/) for manifest,
   hooks, commands, agents, skills, and assets.
4. Inspect [`tools/muscle/cli.py`](../tools/muscle/cli.py) for command truth.
5. Inspect tests for guardrails:
   [`test_plugin_manifest.py`](../tests/unit/test_plugin_manifest.py),
   [`test_plugin_docs.py`](../tests/unit/test_plugin_docs.py),
   [`test_plugin_hooks.py`](../tests/unit/test_plugin_hooks.py).

## Command Choice

| Goal | Prefer |
|---|---|
| Standard semantic plus static review | `/muscle:review` or `muscle review --target <path> --mode review` |
| Adversarial design/failure review | `/muscle:pressure` or `muscle review --mode pressure` |
| Debug a specific failure | `/muscle:rescue` or `muscle lifeline --target <path> --prompt "<issue>"` |
| Validate compiler/linter/test state | `/muscle:check` or `muscle check --target <path>` |
| Inspect plugin/runtime health | `/muscle:doctor` or `muscle doctor --json` |
| Review background work | `/muscle:probe` and `/muscle:diagnosis` |
| Inspect project learning | `muscle memory status`, `muscle memory history`, `muscle kb stats` |
| Tune overlays | `muscle settings model`, `muscle model status`, `muscle model packs ...` |
| Run release gates | `muscle long-eval benchmark --enforce-gates` plus test suite |

## Write Boundaries

- Do not edit user files outside requested scope.
- Do not rewrite existing dirty worktree changes unless asked.
- Do not hand-edit generated `.muscle/active-review.md`.
- Do not store or print API key values.
- Do not add new plugin commands without updating manifest parity, command docs,
  tests, and this wiki's command catalog.

## Known Documentation Caveat

Current code stores shadow job state through project-local `project_memory.db`.
Some older docs still mention `~/.muscle/shadow_jobs.json`. When documenting or
debugging current behavior, trust [`ShadowBroker`](../tools/muscle/code_review/shadow_broker.py)
and its tests over the older text.

