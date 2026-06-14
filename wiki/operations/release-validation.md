# Release Validation

| Field | Value |
|---|---|
| Audience | Release operators and maintainers |
| Status | Current release-gate checklist |
| Source of truth | [`docs/release-notes-2026-05-01-plugin-readiness.md`](../../docs/release-notes-2026-05-01-plugin-readiness.md), [`pyproject.toml`](../../pyproject.toml), [`tests/unit/test_plugin_manifest.py`](../../tests/unit/test_plugin_manifest.py), [`tests/unit/test_plugin_docs.py`](../../tests/unit/test_plugin_docs.py), [`tests/unit/test_plugin_hooks.py`](../../tests/unit/test_plugin_hooks.py) |

Run the full release gate before claiming the plugin bundle is ready.

## Core Gates

```bash
uv sync --extra dev
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
uv run pytest tests/ -v
```

## Focused Plugin Gates

```bash
uv run pytest tests/unit/test_plugin_manifest.py tests/unit/test_plugin_docs.py tests/unit/test_plugin_hooks.py tests/unit/test_active_review_runtime.py tests/integration/test_install_lifecycle.py -q
```

## Build And Inspect

```bash
uv build --out-dir /tmp/muscle-dist
python -m zipfile -l /tmp/muscle-dist/*.whl | rg 'plugin|savings|discover|filters'
```

Confirm that the wheel contains:

- Claude manifest and marketplace manifest.
- Codex manifest.
- Claude nested hooks and Codex root hook file.
- Plugin commands, agents, skills, and assets.

## Host Validators

If Claude Code is installed:

```bash
claude plugin validate src/muscle/plugin/.claude-plugin/plugin.json
claude plugin validate src/muscle/plugin/.claude-plugin/marketplace.json
claude plugin validate .claude-plugin/marketplace.json
```

If the local Codex build exposes plugin validation, run it against:

```text
src/muscle/plugin/.codex-plugin/plugin.json
src/muscle/plugin/hooks.json
```

If Codex has no validator, record Codex validation as skipped and use
`muscle doctor --json` plus unit tests for local evidence.

## Runtime Diagnostic Gate

```bash
uv run muscle doctor --json
```

For a live smoke, use a throwaway project with `MINIMAX_API_KEY` supplied by the
environment and verify that JSON review output starts with JSON on stdout:

```bash
uv run muscle review --target smoke.py --language python --mode review --format json
```

## Release Evidence To Record

- Commit or branch under validation.
- Full gate command results.
- Targeted plugin gate command results.
- Build artifact paths.
- Manifest/hook validation results.
- Wheel inspection summary.
- Live API smoke status, if run.
- Known skipped gates and why they were skipped.

