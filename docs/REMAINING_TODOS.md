# MUSCLE Remaining Plan

Last updated: 2026-06-12
Status: Living backlog

This is the single living document for remaining MUSCLE work.

Use it for:

- the next active task
- deferred work that is still intentionally kept alive
- concise completion notes for the most recent finished task

Do not create new one-off plan or TODO markdown files unless the work is large
enough to justify a temporary design doc. If that happens, the follow-up tasks
still need to be folded back into this file when the design pass ends.

## Current state

- Production-readiness work for the current `review-smart` benchmark/release
  gate slice is complete.
- `review-smart` now has passing credentialed benchmark evidence and passing
  release-gate evidence for the current fixture suite.
- The local root `.muscle/project_memory.db` corruption has been repaired and
  now passes SQLite integrity checks and MUSCLE `doctor` smoke checks.
- The opt-in experimental foresight preflight product slice is complete. It is
  explicit-only, offline, and not wired into normal `review` or `run` paths.
- The 2026-05-24 release wheel that includes foresight has passed a clean
  installed-wheel smoke outside the editable checkout.
- No production-readiness blocker is currently tracked in this file.
- Historical point-in-time plan docs have been retired and their remaining work
  has been folded into this document.
- New temporary design plan:
  `docs/plans/fable-5-orchestration-updates-2026-06-12.md`. Current product
  direction is Claude Code/Fable 5 first as the host workflow, MUSCLE CLI as the
  orchestration surface, and MiniMax/OpenRouter as current optional MUSCLE-agent
  execution backends for reducing Claude subscription/API spend.

## Just completed

### 2026-06-12 — OpenAI-compatible tool schema compatibility

Status: completed and verified.

Completed:

- added `src/muscle/llm/tool_schema_compat.py` for provider-boundary
  normalization and validation of OpenAI-compatible function/tool schemas
- guaranteed provider-facing function `parameters` schemas have root
  `type: object` and no top-level `oneOf`, `anyOf`, `allOf`, `enum`, `const`,
  or `not`
- wrapped generated top-level arrays under `items`, scalar/enum schemas under
  `value`, and root combinator schemas under `payload`
- returned a per-function unwrap registry so existing handler behavior can be
  preserved before dispatch
- wired normalization into `M27Client.chat()` for OpenAI-compatible endpoints
  and the async OpenAI-compatible adapters for OpenAI, OpenRouter, Kimi, Z.AI,
  and the MiniMax chat-completions adapter
- added regression coverage for array, scalar/enum, combinator, stable object
  root, `_multicategorysearchitems`, legacy `functions`, local invalid-schema
  rejection, and no-network provider failure

Current live rerun result:

- baseline focused provider/routing/model identity gate:
  `68 passed`
- new focused schema compatibility gate:
  `11 passed`
- `uv run mypy src/muscle/`:
  `Success: no issues found in 189 source files`
- `uv run ruff check src/muscle/`:
  `All checks passed!`
- `uv run ruff format --check src/muscle/`:
  `189 files already formatted`
- full suite:
  `2940 passed, 3 skipped`

### 2026-06-09 — host context crusher + Fable 5 host-dollar accounting

Status: completed

Completed:

- `optimization/tool_output_crusher.py`: headroom-style host-side tool-output
  compression (`muscle crush` / `muscle expand`). Strategies: JSON
  array-of-records → deterministic table (reuses the structured compactor,
  −65% chars measured on an 80-finding payload), consecutive-duplicate log
  collapsing, anomaly-preserving head/tail windowing (−67% measured on a 600
  line log). All elisions explicit; anomaly lines never dropped; output
  deterministic for host prompt-cache stability.
- `CcrStore`: bounded content-addressed reversible store under `.muscle/ccr/`
  (atomic writes, sha256-named files, fail-closed integrity verification on
  load, oldest-first pruning).
- `cost_optimizer.HOST_MODEL_PRICING` + `estimate_host_request_cost`: Fable 5
  ($10/$50, cache read $1.00), Opus 4.8/4.7, Sonnet 4.6, codex-default; unknown
  host models fail loudly. `muscle cost delegation-report` defaults to
  `claude-fable-5` and reports estimated host USD avoided and net savings
  (labeled estimated).
- Design doc: `docs/superpowers/specs/2026-06-09-host-context-crusher-design.md`.
- Environment fix (not a repo change): the venv's editable-install `.pth`
  files carried the macOS `hidden` file flag (iCloud/Finder artifact), which
  Python 3.13's `site.py` silently skips — the `muscle` console script was
  broken outside pytest. Fixed with `chflags -R nohidden` on site-packages; a
  stray `_editable_impl_muscle 2.pth` Finder duplicate was removed. If the CLI
  ever reports `No module named 'tools'` again, re-run the chflags fix.

### 2026-05-24 — clean installed-wheel smoke for the foresight package

Status: completed

Completed:
- installed
  `/tmp/muscle-dist-20260524-5/muscle-0.1.0-py3-none-any.whl`
  into a clean temporary virtual environment:
  `/tmp/muscle-wheel-smoke-venv-vbi1Bd`
- ran the installed `muscle` console script from a separate scratch directory:
  `/tmp/muscle-wheel-smoke-cwd-k0Ot2i`
- tightened `muscle foresight --project ...` so an explicit project path is
  honored exactly instead of climbing to an unrelated parent `.muscle/`
- rebuilt the source distribution and wheel at `/tmp/muscle-dist-20260524-5`
- inspected the rebuilt wheel: `264` files, `37` command docs, no duplicate
  entries, and no missing required plugin files
- verified `muscle --help` exits `0`
- verified `muscle foresight --task "smoke" --no-write --json` exits `0` and
  parses with `python3 -m json.tool`
- verified `muscle doctor --json` exits `0` and parses with
  `python3 -m json.tool`
- confirmed the installed-wheel doctor reports plugin docs/manifests/hooks/assets
  as packaged and matching, including `37` command docs

Current live rerun result:
- focused foresight/plugin docs subset: `263 passed, 1 skipped`
- `uv sync --extra dev` exits `0`
- `uv run mypy src/muscle/` exits `0`
- `uv run ruff check src/muscle/` exits `0`
- `uv run ruff format --check src/muscle/` exits `0`
- `uv run pytest tests/ -q` exits `0` with `2445 passed, 3 skipped`
- `uv build --out-dir /tmp/muscle-dist-20260524-5` builds source distribution
  and wheel
- `/tmp/muscle-wheel-smoke-venv-vbi1Bd/bin/muscle --help` exits `0`
- `/tmp/muscle-wheel-smoke-venv-vbi1Bd/bin/muscle foresight --task "smoke"
  --project /tmp/muscle-wheel-smoke-cwd-k0Ot2i --no-write --json | python3 -m
  json.tool` exits `0`
- `/tmp/muscle-wheel-smoke-venv-vbi1Bd/bin/muscle doctor --json | python3 -m
  json.tool` exits `0`
- `uv run muscle doctor --json | python3 -m json.tool` exits `0`
- `git diff --check` exits `0`

Decision:
- the 2026-05-24 wheel is smoke-tested outside the editable checkout
- `muscle foresight` remains explicit-only and experimental
- no new runtime behavior, memory promotion, model-pack mutation, or benchmark
  promotion happened in this slice

### 2026-05-24 — opt-in foresight preflight

Status: completed

Completed:
- added an explicit `muscle foresight` command for bounded project-local
  preflight planning
- kept the workflow opt-in only; no normal `muscle run` or `muscle review` path
  calls foresight
- kept the workflow offline and credential-free
- reads `.muscle/project_memory.db` only through a SQLite read-only connection
  for summary context
- writes only `.muscle/MUSCLE_SHORT_TERM.md` when `.muscle/` already exists
- marks `MUSCLE_SHORT_TERM.md` as generated short-term state, not
  authoritative learned memory
- does not mutate CLAUDE.md, AGENTS.md, MEMORY.md, model packs, learned rules,
  optimization ledgers, or review artifacts
- added `/muscle:foresight` plugin command docs and manifest parity
- fixed package-data inclusion so the plugin skill file
  `src/muscle/plugin/skills/code-review/SKILL.md` is present in the release
  sdist/wheel without duplicate wheel entries

Current live rerun result:
- targeted foresight/plugin tests:
  `312 passed, 1 skipped`
- `uv sync --extra dev` exits `0`
- `uv run mypy src/muscle/` exits `0`
- `uv run ruff check src/muscle/` exits `0`
- `uv run ruff format --check src/muscle/` exits `0`
- `uv run pytest tests/ -q` exits `0` with `2445 passed, 3 skipped`
- `uv build --out-dir /tmp/muscle-dist-20260524-4` builds source distribution
  and wheel
- wheel inspection: `muscle-0.1.0-py3-none-any.whl` lists `264` files, no
  duplicate entries, and includes Claude/Codex plugin manifests, hooks, command
  docs including `foresight.md`, agents, shared assets, and the code-review
  skill file
- `uv run python -m muscle.cli foresight --task "Plan the next safe
  product slice" --target src/muscle/cli.py --no-write --json | python3 -m
  json.tool` exits `0`
- `uv run muscle doctor --json | python3 -m json.tool` exits `0`

Decision:
- the foresight preflight is safe to keep as an experimental, explicit command
- no benchmark promotion occurred and no credentialed MiniMax/API benchmark was
  run for this offline slice
- generated short-term foresight remains separate from durable learned memory

### 2026-05-22 — release docs and package-evidence refresh

Status: completed

Completed:
- built the source distribution and wheel at `/tmp/muscle-dist-20260522/`
- inspected `muscle-0.1.0-py3-none-any.whl`; it lists `262` files and includes
  Claude/Codex plugin manifests, hooks, command docs, skills, and shared assets
- installed the wheel into a clean temporary virtual environment and verified:
  - `muscle --help` exits `0`
  - `muscle doctor --json` exits `0`
  - `muscle doctor --json` output parses with `python3 -m json.tool`
- refreshed stale release-readiness docs and index entries so they no longer
  point at the closed `review-smart` benchmark blocker

Current live rerun result:
- `uv sync --extra dev` exits `0`
- `uv run mypy src/muscle/` exits `0`
- `uv run ruff check src/muscle/` exits `0`
- `uv run ruff format --check src/muscle/` exits `0`
- `uv run pytest tests/ -q` exits `0` with `2432 passed, 3 skipped`
- `git diff --check` exits `0`

Decision:
- current release/package evidence is fresh for the post-DB-repair checkout
- no production-readiness blocker is currently tracked in this file
- the next code-producing product slice should be opened explicitly before
  changing behavior; the safest candidates remain the opt-in foresight preflight
  or consensus supervision experiments below

### 2026-05-21 — root project memory DB repair

Status: completed

Completed:
- recovered the malformed root `.muscle/project_memory.db` with SQLite
  `.recover`
- imported the recovered SQL into a fresh database
- compacted the recovered database with `VACUUM INTO`
- replaced the malformed root DB with the recovered clean DB
- preserved the original malformed DB and recovery SQL at:
  `.muscle/backups/project_memory_repair_20260521_071709/`

Current live rerun result:
- `sqlite3 .muscle/project_memory.db 'PRAGMA integrity_check;'` returns `ok`
- `ProjectMemory('<repo-root>')`
  opens the root database successfully
- recovered row counts include:
  - `tasks`: `218`
  - `working_memory`: `299`
  - `external_benchmark_sessions`: `14`
- `uv run python -m muscle.cli doctor --json` exits `0`
- `uv run muscle doctor --json` exits `0` and emits parseable JSON

Decision:
- the malformed root project-memory caveat is closed
- host-memory history comparisons are no longer blocked by local SQLite
  corruption
- CLI JSON smoke output is no longer routed through Rich wrapping on the
  `doctor`, `savings`, `discover`, `filters`, and `check --format json` paths
- remaining `doctor` warnings are configuration/state warnings, not DB
  corruption:
  - project enabled: `no`
  - API key: `missing`
  - active review snapshot: stale
  - external importer: no imported sessions yet

### 2026-05-17 — review-smart benchmark and release-gate completion

Status: completed

Completed:
- added a high-confidence deterministic fast path for trivial `review-smart`
  correctness/security reviews, covering common unsafe eval, hardcoded secret,
  SQL injection, XSS, file-read, plaintext-password, IDOR, unawaited promise,
  default-admin, and JSON schema/key-access risks
- kept related-project and model-pack lesson usage traceable when the
  deterministic fast path replaces an LLM call
- changed the prompt-overhead release gate to use captured prompt-side
  telemetry when available, with total-token fallback only for older reports
- reran the full credentialed benchmark/release flow with the MiniMax token-plan
  key loaded from a local credentials file (outside the repo) without
  printing the key:
  - benchmark JSON:
    `.muscle/reports/benchmarks/benchmark_20260517_201913.json`
  - benchmark Markdown:
    `.muscle/reports/benchmarks/benchmark_20260517_201913.md`
  - release evidence JSON:
    `.muscle/reports/release_evidence/release_gates_20260517_201914.json`
  - release evidence Markdown:
    `.muscle/reports/release_evidence/release_gates_20260517_201914.md`

Current live rerun result:
- release gates overall: `True`
- benchmark gates overall: `True`
- high/critical recall improved from `28.57% -> 100.00%`
- false-positive rate improved from `72.73% -> 5.00%`
- token cost improved from `20135 -> 972`
- printed thresholds all pass:
  - high/critical recall up 20%: `True`
  - false-positive rate not worse: `True`
  - token cost down 30%: `True`
- external lesson usage remains traceable:
  - related-project traceable scenarios: `1`
  - model-pack traceable scenarios: `1`
- focused offline guardrails passed:
  - `tests/unit/test_cli_run_offline.py`
  - `tests/unit/test_cli_review.py::TestReviewCommand::test_review_does_not_trigger_remote_model_pack_fetch`
  - `tests/unit/test_cross_project_learning.py::test_lesson_resolver_uses_remote_installed_pack_without_fetch`

Decision:
- the active production-readiness TODOs are closed for this slice
- `review-smart` is supported by the current benchmark and release-gate evidence
- keep lean routing benchmark-only; it still improves quality matches `2 -> 3`
  but increases routing cost units `7 -> 8`, so the routing candidate remains
  rejected
- the local root `.muscle/project_memory.db` was still malformed during this
  pass; it was repaired later on 2026-05-21

Validation:
- `uv run pytest tests/unit/test_committee_reviewer.py tests/unit/test_review_benchmark.py -q`
- `uv run ruff check src/muscle/code_review/committee_reviewer.py src/muscle/code_review/review_benchmark.py tests/unit/test_committee_reviewer.py tests/unit/test_review_benchmark.py`
- `uv run ruff format --check src/muscle/code_review/committee_reviewer.py src/muscle/code_review/review_benchmark.py tests/unit/test_committee_reviewer.py tests/unit/test_review_benchmark.py`
- `uv run mypy src/muscle/code_review/committee_reviewer.py src/muscle/code_review/review_benchmark.py`
- `uv run python -m muscle.cli long-eval benchmark --suite all --enforce-gates`

### 2026-04-17 — Credentialed full-suite benchmark rerun and release-evidence capture

Status: completed

Completed:
- ran the full benchmark and release-gate flow with live MiniMax credentials:
  - `uv run python -m muscle.cli long-eval benchmark --suite all --enforce-gates`
- captured the generated evidence:
  - benchmark JSON:
    `.muscle/reports/benchmarks/benchmark_20260417_231502.json`
  - benchmark Markdown:
    `.muscle/reports/benchmarks/benchmark_20260417_231502.md`
  - release evidence JSON:
    `.muscle/reports/release_evidence/release_gates_20260417_231506.json`
  - release evidence Markdown:
    `.muscle/reports/release_evidence/release_gates_20260417_231506.md`
- confirmed the benchmark still does not justify any new promotion:
  - aggregate high/critical recall stayed flat at `100% -> 100%`
  - false-positive rate regressed from `47.50% -> 54.17%`
  - token cost regressed from `22876 -> 29365`
  - benchmark gates overall: `False`
  - release gates overall: `False`
- confirmed the meta-harness side decisions remain unchanged:
  - compact host memory stays acceptable:
    `3021 -> 3007` chars, estimated `3` tokens saved
  - lean routing still fails the promotion rule:
    quality matches `2 -> 3`, routing cost units `7 -> 8`,
    candidate kept = `False`
- captured the dominant live failure signals from the run:
  - routing classifier intermittently returned empty / malformed JSON or
    thinking-only responses and fell back
  - external lesson usage stayed untraceable in the related-project and
    model-pack suites (`0` traceable scenarios in both)
  - candidate prompt overhead exceeded budget in:
    - `core-review` (`1.21` vs `1.15`)
    - `neutral-baseline` (`1.65` vs `1.15`)
    - `model-pack` (`2.35` vs `1.35`)
  - project-only no-regression gate failed due to false-positive regressions in:
    - `neutral-baseline` (`0.00 -> 0.75`)
    - `unrelated-project` (`0.20 -> 0.50`)

Decision:
- keep compact host-memory behavior as the default
- keep lean routing benchmark-only
- do not promote `review-smart` (or any other risky benchmark candidate) until
  the benchmark gates pass

### 2026-04-17 — Lean Meta-Harness Phase 1 benchmark and promotion pass

Status: completed

Completed:
- ran the new benchmark CLI path for the current project:
  - `uv run python -m muscle.cli long-eval benchmark --suite all --no-history`
- verified the current shell has no `MINIMAX_API_KEY` / `ANTHROPIC_API_KEY`, so
  the full credentialed fixture-review benchmark did not produce a report and
  remains blocked on credentials
- fixed a benchmark-adjacent regression where importing `ClaudePublisher`
  triggered a circular import through `muscle.code_review.__init__`
- reran targeted validation on the touched surfaces:
  - `uv run pytest tests/unit/test_claude_publisher.py -v`
  - `uv run pytest tests/unit/test_review_benchmark.py tests/unit/test_routing.py -v`
- inspected the offline meta-harness comparisons that do not require live model
  access:
  - compact host memory: `3021 -> 3007` chars, estimated `3` tokens saved,
    candidate kept
  - lean routing candidate: quality matches `2 -> 3`, estimated routing cost
    `7 -> 8`, candidate rejected by the promotion rule

Decision:
- keep compact host-memory behavior as the current default; no further runtime
  change needed from this pass
- keep lean routing benchmark-only; do not promote because the candidate
  improves quality but regresses the cost axis, so the promotion rule fails
- do not promote any additional risky behavior until the credentialed full-suite
  benchmark and release gates are rerun successfully

### 2026-04-17 — Lean Meta-Harness Phase 1 minimum slice

Status: completed

Completed:
- extended `ReviewArtifactStore` with stable per-run `manifest.json` output
- wired thin-by-default / thick-on-trigger traces onto existing review artifacts
  and `llm_calls.metadata_json` pointers
- brought standard review runs onto the artifact spine so legacy and workflow
  paths both emit stable evidence
- compacted root host-memory publishing at render time without rewriting
  authoritative stored rules
- added delegation outcome metadata for routing, verification quality, and
  token-savings signals
- added a small benchmark comparison path for:
  - current vs compact host memory
  - current routing vs lean routing candidate
- documented and encoded the promotion rule:
  keep candidates only when benchmark evidence improves quality, token cost, or
  both without regressing the other axis

Result:
- MUSCLE now has a lean evidence spine for delegation optimization without
  adding a new trace DB, artifact retrieval subsystem, or candidate registry

### 2026-04-17 — Lean Meta-Harness Delegation Plan

Status: completed

Started:
- audited the larger Meta-Harness-style plan for bloat and overlap with
  existing MUSCLE subsystems

Completed:
- rewrote the plan into a lean execution model centered on existing MUSCLE
  spines
- reduced the architecture to three tracks:
  - evidence spine
  - delegation optimizer
  - benchmark loop
- explicitly deferred high-complexity systems until proven necessary:
  - separate trace database
  - standalone artifact retrieval engine
  - generic harness registry
  - population/frontier search
  - always-on full transcript capture

Result:
- the implementation target is now Phase 1 of the lean plan:
  build the minimum slice that can generate measurable host-token savings and
  evidence for future optimization

## Active next task

### No active production-readiness TODO

Status: complete
Priority: none

All production-readiness TODOs that were active before this slice were closed by
the 2026-05-17 benchmark/release-gate pass, the 2026-05-21 root project-memory
DB repair, the 2026-05-22 release docs/package-evidence refresh, and the
2026-05-24 opt-in foresight preflight and installed-wheel smoke slices above.

Next production-facing choice:
- open a new product slice before changing behavior; remaining candidates should
  preserve the standing guardrails below and be benchmark-gated before any risky
  promotion
- the current recommended slice is the Fable/Claude-first orchestration plan,
  starting with deterministic host-risk preflight, then effort policy and typed
  verification claims before OpenRouter provider wiring or async-worker work

Remaining non-blocking local state:
- temporary Fable/Claude-first provider strategy plan is open and should be
  folded back into this living plan after the design/implementation train lands

Standing guardrails for future work:

- Do not add a new trace database.
- Do not add a separate artifact retrieval subsystem.
- Do not add a candidate registry unless the existing optimization ledger proves
  insufficient.
- Keep runtime routing simple and cached.
- Benchmark-gate risky behavior before promoting it.

## Deferred work

These are real ideas, but intentionally not the next thing.

### Consensus supervision / external model escalation

Status: deferred until after the lean delegation slice proves useful

Carry forward:

- `muscle consensus` command surface
- supervisor / consensus / gate review backends
- MUSCLE-owned orchestration, normalization, and memory intake
- risk-based automatic escalation policy

When to revisit:

- only after local delegation optimization is measured and stable

## Recently retired plan docs

These were folded into this living plan and can stay deleted unless their
contents become newly relevant:

- `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`
- `MUSCLE_ROADMAP.md`
- `docs/meta-harness-delegation-plan.md`
- `docs/opensrc-integration-plan.md`
- `Forsight-plan.md`
- `GroupTink-collab.md`

## Update protocol

When work starts:

- mark the active task `in progress`
- keep the checklist current

When work finishes:

- add a short completion note under `Just completed`
- promote the next active task into `Active next task`
- retire any temporary design doc by folding its surviving tasks back here
