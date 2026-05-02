# MUSCLE Release Notes: Plugin Readiness and Evidence Surfaces

Release date: 2026-05-01

This release-readiness pass hardens the Claude/Codex plugin bundle after the
RTK-inspired evidence, savings, discovery, filter, and plugin-doctor work.

## What Changed

- command execution now records compact `CommandEvidence` artifacts with
  command identity, exit state, parser tier, output digests, retained excerpts,
  and token-saving estimates
- parser results expose explicit tiers so consumers can distinguish full
  structured parses from degraded parses and passthrough fallbacks
- static analyzer and evaluator paths now carry command evidence alongside
  their normal findings and command results
- `muscle savings` summarizes local token-savings ledgers, cache impact,
  prompt-compaction savings, command-output compaction savings, and parser-tier
  counts
- `muscle discover` reports repeated missed MUSCLE review/check opportunities
  from imported host sessions without writing project memory
- `muscle filters` verifies built-in and explicitly trusted project-local
  command-output filters, with inline tests and digest-based trust checks
- `muscle doctor` now reports plugin manifest digests, hook digests,
  command-doc parity, Codex assets, hook-runtime state, active-review snapshot
  freshness, model identity, and external importer availability
- the packaged plugin bundle includes Claude and Codex manifests, root and
  nested hook files, Codex assets, and the new command docs for savings,
  discovery, filters, and doctor diagnostics
- `muscle review --format json` now keeps stdout as machine-parseable JSON by
  suppressing progress text and routing incidental review-runtime stdout to
  stderr
- the repository-level Claude marketplace manifest now points at the plugin
  subdirectory with the same `muscle@muscle-marketplace` shape used by the
  install docs
- public README, privacy, security, terms, and license files were refreshed so
  the GitHub presentation matches the plugin bundle and release evidence

## Product Rules

- command evidence is local diagnostic evidence; it is not a public telemetry
  claim
- project-local memory remains authoritative
- project-local filters are ignored until explicitly trusted by digest
- discovery is read-only and does not mutate memory
- doctor is observational by default; refresh updates local active-review state
  only when requested
- Codex plugin validation is treated as skipped unless a local Codex validator
  command exists

## Operator Checks

Recommended release gates for this plugin bundle:

1. `uv sync --extra dev`
2. `uv run mypy tools/muscle/`
3. `uv run ruff check tools/muscle/`
4. `uv run ruff format --check tools/muscle/`
5. `uv run pytest tests/ -v`
6. `uv run pytest tests/unit/test_plugin_manifest.py tests/unit/test_plugin_docs.py tests/unit/test_plugin_hooks.py tests/unit/test_active_review_runtime.py tests/integration/test_install_lifecycle.py -q`
7. `uv build --out-dir /tmp/muscle-dist`
8. inspect the wheel for Claude/Codex plugin manifests, hooks, assets, and new
   command docs
9. run `uv run muscle doctor --json`

## Validation Snapshot

Current checkout validation on 2026-05-01:

- `uv sync --extra dev`: passed
- `uv run mypy tools/muscle/`: passed
- `uv run ruff check tools/muscle/`: passed
- `uv run ruff format --check tools/muscle/`: passed
- `uv run pytest tests/ -v`: `2213 passed, 3 skipped`
- targeted plugin gate: `345 passed, 1 skipped`
- `uv build --out-dir /tmp/muscle-dist`: built source distribution and wheel
- wheel inspection: requested Claude/Codex manifests, hooks, assets, and new
  command docs were present
- Claude plugin, nested marketplace, and repository-level marketplace manifest
  validation: passed with local `claude plugin validate`
- Codex plugin manifest validation: skipped because the local Codex CLI exposes
  plugin marketplace management but no plugin validator command
- live API smoke: passed with `MINIMAX_API_KEY` supplied through the environment
  in a throwaway project; `muscle review --target smoke.py
  --language python --mode review --format json` exited 0, stdout parsed as
  JSON from the first character, and the intentionally unsafe `eval()` path was
  reported as a critical issue
- keyed `uv run muscle doctor --json`: API key status, plugin manifest digests,
  hook digests, command-doc parity, plugin assets, active-review snapshot, and
  model identity were OK; warnings were local-state-only
