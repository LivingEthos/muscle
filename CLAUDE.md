# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MUSCLE (MiniMax Unified Self-Correcting Learning Engine) is a local-first code review and iterative code-generation tool that uses MiniMax M-series models via an Anthropic-compatible API. The default model is **MiniMax-M3** (1M-token context, request-time thinking toggle); set `ANTHROPIC_MODEL` to pin a different MiniMax model (e.g. `MiniMax-M2.7`).

Current reality in this repo:

- `tools/muscle/` is the active implementation.
- The strongest working path today is `muscle review` plus its post-review learning pipeline.
- Runtime learning currently writes to `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, and `.muscle/MEMORY.md`.
- The root `CLAUDE.md` file you are reading is a maintainer guide for Claude Code working in this repository.
- When editing this repository, treat MUSCLE as the product under development, not as a required development assistant or workflow dependency.

## Build & Development Commands

```bash
# Install dependencies (uses uv package manager)
uv sync --dev

# Release / CI builds — use frozen lockfile for reproducible installs (PKG-02)
uv sync --frozen --extra dev

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/unit/test_cli.py -v

# Run a single test by name
uv run pytest tests/unit/test_cli.py -k "test_review_command" -v

# Quality gates (ALL must pass before merging)
# IMPORTANT: always invoke mypy via `uv run` — running a globally installed mypy
# can produce false positives/negatives due to stub version mismatches (PKG-03)
uv run mypy tools/muscle/
uv run ruff check tools/muscle/
uv run ruff format --check tools/muscle/
uv run pytest tests/

# Auto-fix lint/format issues
uv run ruff check tools/muscle/ --fix
uv run ruff format tools/muscle/
```

## Architecture

### Package Tree

- **`tools/muscle/`** - The MUSCLE package, installed as the `muscle` CLI via `pyproject.toml` entry point (`tools.muscle.cli:main`). (The legacy `tools/scle/` predecessor was removed in the 2026-06 cleanup; references in historical docs are informational only.)

### Core Runtime Flows (tools/muscle/)

The active package has two main runtime flows:

1. `muscle run`: **LoopController -> CodeGenerator -> EvaluatorRegistry -> Evolver**
2. `muscle review`: **ReviewController -> StaticAnalyzer -> CodeReviewer -> LearningPipeline**

| Module | Role |
|--------|------|
| `cli.py` | Click-based CLI entry point. All commands defined here. |
| `m27_client.py` | HTTP client for MiniMax M3 via Anthropic-compatible API. Streaming, retries, JSON recovery from truncated responses. |
| `loop_controller.py` | Orchestrates generate-evaluate-fix loops with event callbacks. |
| `session_manager.py` | File-based session persistence and resume under `.muscle/sessions/<session_id>/`. |
| `budget_manager.py` | Token/cost budget tracking and enforcement. |
| `code_generator.py` | Prompts M3 for code, parses fenced code blocks, writes generated files. |
| `evaluator_registry.py` | Picks compiler/test/lint evaluators by language and aggregates results. |
| `evolver.py` | Turns failures into an improved next strategy, with optional StrategyKB lookup. |
| `project_manager.py` | Per-project bootstrap, config, and `.muscle/` layout management. |
| `project_memory.py` / `project_memory_schema.py` / `project_memory_types.py` | Project-local SQLite store (`project_memory.db`) — the **source of truth** for rules, learnings, shadow jobs, fix tracking, and audit trail. See `migrations/`. |
| `project_fingerprint.py` | Computes project identity and relatedness signals for cross-project learning. |
| `project_notes.py` | User notes persisted in `project_memory.db`. |
| `system_db.py` | Global SQLite store (`~/.muscle/system.db`) for fingerprints, aliases, model-pack cache. |
| `learning_ingestor.py` | Ingests and validates learning signals from completed reviews. |
| `memory_decision_engine.py` | Scores and promotes findings from `project_memory.db` into publishable rules. |
| `claude_publisher.py` | Publishes DB-backed content into root `CLAUDE.md` via `MUSCLE_PUBLISHED_START/END` markers. Enforces per-section size caps and M3 consolidation. |
| `lesson_resolver.py` | Resolves the effective lesson set (project + related projects + model pack). |
| `model_identity.py` / `model_packs.py` / `model_pack_standard.py` / `model_pack_validation.py` | Canonical model identity and model-pack overlay system. |
| `audit_presenter.py` | Formats audit/trace output for CLI + TUI consumption. |
| `change_capture.py` | Captures repo-side changes for learning signals. |
| `legacy_importer.py` | Imports legacy markdown / JSON formats into `project_memory.db`. |
| `transferable_lesson_scrubber.py` | Scrubs project-specific details from lessons before export. |
| `backup_manager.py` | Backup/restore for managed files prior to writes (used by publisher and by the host-docs optimizer). |
| `cost_optimizer.py` | Cost tracking and budget-aware optimization helpers, including host-model pricing (`HOST_MODEL_PRICING`, `estimate_host_request_cost`) for Fable 5 / Opus 4.8 / Codex dollar accounting. |
| `optimization/` | Context budgeting, prompt optimization, session recording, and external-session importers (Claude Code + Codex). See `optimization/importers.py`. |
| `optimization/tool_output_crusher.py` | Host-side tool-output compression (`muscle crush` / `muscle expand`): JSON-records → deterministic tables, log dedupe, anomaly-preserving windowing, with a bounded content-addressed reversible store under `.muscle/ccr/`. |

### Code Review Subsystem (tools/muscle/code_review/)

| Module | Role |
|--------|------|
| `review_controller.py` | Orchestrates full review flow across modes (review, auto-fix, plan, hybrid, pressure). |
| `code_reviewer.py` | Sends code to M3 for analysis, parses structured findings. |
| `static_analyzer.py` | Runs local analyzers like Ruff, ESLint, TSC, Clippy, and normalizes findings. |
| `fix_generator.py` | Applies suggested code replacements for auto-fixable issues. |
| `handoff_generator.py` | Produces markdown handoff plans for manual follow-up. |
| `learning_pipeline.py` | Runs after reviews and updates memory files plus recurring-pattern learning hooks. |
| `pattern_detector.py` | Identifies recurring patterns across reviews. |
| `memory_manager.py` | Manages `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, and `.muscle/MEMORY.md` with structured rules. |
| `skill_generator.py` | Generates project-specific Claude Code skills from detected patterns. |
| `agent_generator.py` | Creates specialized sub-agents for complex review tasks. |
| `shadow_broker.py` / `shadow_worker.py` | Background (shadow mode) review job queue and workers. |
| `long_eval_runner.py` | Manual deep evaluation runner and report generation. |
| `strategy_evolver.py` | Evolves review strategies based on validated effectiveness. |
| `fix_tracker.py` | Tracks fix attempts and their outcomes. |
| `committee_reviewer.py` | De-duplicating multi-pass semantic + deterministic review orchestrator. |
| `verification_loop.py` | Codex-style verify-before-learn pattern: apply fix → validate → only record if verification passes. |
| `review_controller.py` / `review_workflows.py` / `review_scope.py` | Review mode orchestration and file-scope selection. |
| `review_kb.py` / `review_artifacts.py` / `review_benchmark.py` | Review knowledge base, structured artifacts, and benchmarking. |
| `nightly_runner.py` | Background nightly review orchestration. |
| `worktree_manager.py` | Isolated git worktree management for auto-fix / hybrid review flows. |
| `agent_kb_fetcher.py` | Fetches example agents from remote knowledge bases. |
| `review_controller.py` | Orchestrates full review flow across modes (review, auto-fix, plan, hybrid, pressure). |

### Other Subsystems

- **`evaluators/`** - Pluggable evaluators: compiler, linter, tester, assertions. Registered via `evaluator_registry.py`.
- **`adapters/`** - Git, GitHub, GitLab, Jenkins, MCP integrations.
- **`tui/`** - Rich-based terminal UI with views and project manager.

### Claude Code Plugin (`tools/muscle/plugin/`)

The plugin bundle contains slash-command definitions, hooks, skills, and subagent docs for the MUSCLE product. When working on this repository, edit and verify those files as source artifacts rather than assuming the plugin workflow itself is part of your development loop.

### Data Storage

**Architecture:** DB-first. `project_memory.db` is the **authoritative source of truth** for per-project rules, learnings, fix tracking, shadow jobs, and audit trail. Root `CLAUDE.md` is published from DB-backed decisions via `claude_publisher.py` (marker region). Internal markdown artifacts (`.muscle/CLAUDE.md`, etc.) are bounded, non-authoritative mirrors.

Per-project state:

- `.muscle/project_memory.db` — **authoritative per-project SQLite store** (rules, learnings, shadow jobs, fix tracking, audit trail). Schema in `project_memory_schema.py`; migrations in `migrations/`.
- `.muscle/config.yaml` — JSON content written by `ProjectManager`.
- `.muscle/strategy_kb.json` — bootstrap strategy metadata (legacy, being migrated).
- `.muscle/knowledge/strategies.db` — StrategyKB SQLite database.
- `.muscle/review_kb/review_kb.db` — ReviewKB SQLite database.
- `.muscle/sessions/<session_id>/` — `meta.json`, `iterations.jsonl`, `report.json`, `context.json`, artifacts.
- `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, `.muscle/MEMORY.md` — internal artifacts (not authoritative).
- `.muscle/skills/`, `.muscle/agents/`, `.muscle/reports/`, `.muscle/logs/`, `.muscle/consolidation_audit.jsonl`.

Global state:

- `~/.muscle/system.db` — system-level SQLite (fingerprints, aliases, model-pack cache).
- `~/.muscle/cache/cache.db` — response cache.
- `~/.muscle/improvement_log.json` — global improvement signals.
- `~/.muscle/prompts/`, `~/.muscle/global/strategies.db`, `~/.muscle/global_review/review_kb.db`.
- `~/.muscle/<session_id>.pid` — PID lock files.
- `~/.muscle/shadow_jobs.json` — **legacy**; shadow jobs now live in per-project `project_memory.db` (migration `_0005_shadow_jobs.py`).

## Current Maturity Notes

- `tools/muscle/` is the sole package tree (the legacy `tools/scle/` predecessor was removed).
- DB-first architecture is wired: `project_memory.db` is authoritative for rules and learnings; `claude_publisher.py` publishes DB-backed content to root `CLAUDE.md`.
- The TUI is live against `project_memory.db` for review runs, model-identity history, and lesson-usage history. Some advanced panels still render lighter/placeholder data per `docs/architecture.md`.
- GitHub, GitLab, Jenkins, and MCP adapters exist as modules, but not all are first-class CLI workflows yet.
- `LearningPipeline` is wired after reviews and memory-file updates are real today. The deeper recurring-pattern ecosystem is present and still maturing.
- Codex-side session imports exist via `optimization/importers.py` (reads `$CODEX_HOME/sessions`). Host-doc publishing follow-up, including `AGENTS.md` coverage, is tracked in `docs/REMAINING_TODOS.md`.
- Some plugin docs are currently stale. In particular, do not rely on `muscle shadow ...` examples or `muscle settings platform --hooks`; use the actual CLI help instead.

## Host Model Contract (Opus 4.8 / Codex)

MUSCLE's plugin output is consumed by either **Claude Code (Opus 4.8)** or **Codex**. The plugin itself never needs an Anthropic API key — it authenticates to **MiniMax M3** via `MINIMAX_API_KEY` (or the legacy alias `ANTHROPIC_API_KEY`, which points to MiniMax's Anthropic-compatible endpoint, **not** real Anthropic).

Guidance for editing MUSCLE prompts and plugin artifacts:

- **Plan-then-hand-off division of labor.** Opus 4.8 / Codex keep the planning, synthesis, and user-interaction roles. MUSCLE's M3 agents are the execution muscle (bulk multi-file review, test/lint sweeps, fix-candidate generation, pattern scans) — ~5–10× cheaper per token. Write prompt templates that reinforce this split, not the reverse.
- **Opus 4.8 interprets prompts literally.** Use positive, directive phrasing; name tools and commands explicitly; avoid negative "don't do X" framings when a positive equivalent exists.
- **Opus 4.8 spawns fewer subagents / tool calls by default.** If a prompt requires a specific delegation (rescue agent, verification agent), spell out the trigger conditions.
- **Auto mode is in scope.** Delegation hand-offs must work without inter-step confirmation when the user is in auto mode.
- **Do not add an Anthropic fallback in `m27_client.py`** without first stripping `temperature`, `top_p`, `top_k` (400 errors on Opus 4.8). MUSCLE calls MiniMax; keep it that way unless there's a concrete reason to change. Note: MiniMax-M3 keeps the same parameter contract as M2.x — `temperature` (range [0,2]) and `top_p` are honored while `top_k` and `stop_sequences` are **ignored** — so the existing strip is still correct. (M3's `top_p` default is 0.95 vs 0.9 on M2.x.)

## Delegation Economics

- Claude Fable 5 ≈ **$10 / $50 per MTok** (the current top host model); Claude Code (Opus 4.8) ≈ **$5 / $25 per MTok**; Codex hosts are in the Opus range. MiniMax M3 is ~**8–20× cheaper** for equivalent review-scoped reasoning (≈ **$0.60 / $2.40 per MTok** at the ≤512K-input tier, **doubling to $1.20 / $4.80 above 512K input**). M3's base rate is ~2× M2.7's, but it remains roughly an order of magnitude below the host models, so the delegation rationale is unchanged — and twice as strong on a Fable 5 host. Host pricing lives in `cost_optimizer.HOST_MODEL_PRICING`; `muscle cost delegation-report` defaults to `claude-fable-5` and reports estimated host dollars avoided.
- **Host-side context compression:** large tool outputs (search results, logs, analyzer JSON) should be piped through `muscle crush` before they enter the host model's context (~50–70% smaller, anomaly lines always preserved, original retrievable via `muscle expand <ccr:handle>`). This is the headroom-style lever for host token cost; it composes with delegation rather than replacing it.
- MUSCLE's active backlog (`docs/REMAINING_TODOS.md`) tracks the pinned **Methodology + Delegation Protocol + Effort Guidance** work for reviewed-project host docs so the host model hands bulk execution off to MUSCLE's M3 agents (`/muscle:review`, `/muscle:rescue`, `/muscle:pressure`, verification agent) while keeping planning and synthesis with itself.
- The plugin manifest at `tools/muscle/plugin/.claude-plugin/plugin.json` is **manually curated** — new slash commands require updating the manifest's `description` field as well as adding the command file.

## MiniMax-M3 Feature Wiring

How MUSCLE exploits M3 over M2.7 (design doc: `docs/plans/m3-thinking-toggle-scope.md`):

- **Request-time thinking toggle.** `m27_client._apply_thinking_param` injects the per-endpoint shape (`thinking: {type: ...}` on the Anthropic path, boolean `reasoning_split` on the OpenAI path). `chat()`/`chat_structured()`/`chat_streaming()` take a `thinking` kwarg (default `None` = byte-identical legacy request). Per-stage policy lives in `code_review/thinking_policy.py`: analysis stages (semantic/committee/verification/fix/pattern) use `adaptive`; formatting/summarization stages (memory/handoff/skill/agent/strategy) use `disabled`. Override all stages with `MUSCLE_THINKING_MODE`. Both modes cost the same — this is a latency/quality lever, not a cost lever.
- **Prompt caching is automatic.** MiniMax-M3 passively prefix-caches (order: tool list → system → user) for calls ≥512 input tokens at $0.12/MTok (80% off). No `cache_control` is sent or needed; MUSCLE already places the stable system prompt first. Do **not** add explicit cache markers.
- **Tiered pricing.** `cost_optimizer.estimate_request_cost(model, in, out, cached_input_tokens=)` applies M3's input-length tiers (>512K input doubles both rates) and the cache-hit rate. `estimate_cost()` reports `model` + `pricing_tier`.
- **Model-aware caps.** Output ceiling is model-keyed (`MODEL_MAX_OUTPUT_TOKENS`: M3=32768 vs 8192 default). The escalated whole-file review slice scales for M3's 1M window (`ContextBudgeter.escalation_line_budget`, set in `cli._build_context_budgeter`); the compact base budget is unchanged.
- **`response_format`** is plumbed through `chat()` as an opt-in passthrough (default off); the proven text-parse path in `chat_structured()` remains the default.

## Key Patterns

- **API Client**: `M27Client` uses direct HTTP calls against MiniMax's Anthropic-compatible API and includes retry, rate limiting, and JSON recovery behavior.
- **Event-driven loops**: `LoopController` emits `LoopEvent` callbacks for streaming, evaluation, and iteration tracking.
- **Review modes**: `review`, `auto-fix`, `plan`, `hybrid`, `pressure` are defined in `tools/muscle/code_review/types.py`.
- **Types**: Core types in `tools/muscle/types.py` use dataclasses, not Pydantic.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `MINIMAX_API_KEY` (or legacy alias `ANTHROPIC_API_KEY`) | **MiniMax** credential. Despite the alias name, this is **not** a real Anthropic key — it authenticates MiniMax's Anthropic-compatible endpoint. |
| `ANTHROPIC_BASE_URL` | API endpoint (default: `https://api.minimax.io/anthropic`) |
| `ANTHROPIC_MODEL` | Override MUSCLE's canonical MiniMax model (used by `cli.py`). |
| `MUSCLE_THINKING_MODE` | Override the per-stage M3 thinking policy for **all** review stages. One of `disabled`, `adaptive`, `enabled` (invalid/unset falls back to the per-stage policy in `code_review/thinking_policy.py`). |
| `CODEX_HOME` | Codex session root for `optimization/importers.py` (default: `~/.codex`). |

## Testing Conventions

- All tests in `tests/unit/` with `test_` prefix matching the module name.
- Heavy use of `unittest.mock` - shared fixtures in `tests/conftest.py` (mock_subprocess, mock_requests, mock_sqlite3, temp_project_dir).
- Uses `pytest-asyncio` with `asyncio_mode = "auto"`.
- Coverage source is `tools.muscle`.

## Tool Configuration

- **Ruff**: line-length 100, target Python 3.10, rules: E, F, W, I, N, UP, B, C4. E501 ignored.
- **Mypy**: strict (`disallow_untyped_defs`, `warn_return_any`).
- Python 3.10+ required.

<!-- MUSCLE_PUBLISHED_START -->
### Methodology
- Think before coding: state assumptions; if multiple interpretations fit, surface them.
- Simplicity first: ship the minimum code that solves the problem.
- Surgical changes: touch only what the task requires; match existing style.
- Goal-driven execution: define the verification check first, then loop until it passes.

### Delegation Protocol (Plan-Then-Hand-Off)
You (Claude Code / Codex) are the planner and synthesizer. MUSCLE's MiniMax M2.7 agents are the execution muscle — they do bulk, mechanical work at ~5–10× lower token cost per equivalent pass.

Division of labor:
- **You do:** understand intent, form the approach, make architectural and UX calls, write a focused plan, integrate results, present to the user.
- **MUSCLE does:** execute that plan — bulk code reviews across many files, generating fix candidates, running test/type-check sweeps, collecting diagnostics, validating changes, pattern scans.

Once you've decided what needs to happen, write a concise plan and hand execution to MUSCLE:
- Multi-file code review, bug hunting, security audit → `/muscle:review` with a targeted scope and focus.
- Deep investigation of a specific failure → MUSCLE rescue agent (`/muscle:rescue`).
- Validating a fix, running tests / type-checks / linters → MUSCLE verification agent.
- Pressure-testing a design you've proposed → `/muscle:pressure`.

Keep the planning with you. Do not ask MUSCLE to plan the work. Do not do the bulk execution yourself. When MUSCLE reports back, integrate and decide — cite the MUSCLE session id so follow-ups stay linked. If MUSCLE's output is clearly off-target on a novel problem (empty pattern memory, low confidence across findings), fall back to direct reasoning.

_These commands require the MUSCLE plugin bundle to be active in this project (for example, the Claude or Codex plugin bundle under `tools/muscle/plugin`). Without it, reason directly._

### Effort & Tool Guidance
- On Claude Code (Opus 4.8): run MUSCLE fix-application flows at `xhigh` effort; summarization-only at `high`. In auto mode, proceed through delegations without confirmation prompts.
- Opus 4.8 interprets instructions literally. If a MUSCLE finding is ambiguous, ask the user before generalizing.
- Opus 4.8 provides its own progress updates — do not add interim summary instructions.

### Critical Rules
- Silent fallback to 'adaptive' for unknown stages hides typos and masks quality regressions — Either (a) raise KeyError for unknown stages so refactors fail loudly at the first call site, or (b) at minimum emit a warnings.warn(..., RuntimeWarning) or structured log entry each time an unknown stage is resolved. If a default must be kept, it should be the cheapest mode (disabled), not the most expensive, to fail safe toward lower resource consumption. (score: 16.5, validated: 1x)
- Locking is partial: update uses file lock but prune and consolidate do read-then-write — Route ALL file mutations through update_text_file_locked or a sibling helper with the same locking contract. Add an integration test that fires 100 concurrent writers plus 1 pruner plus 1 consolidator and asserts no lost entries. (score: 16.5, validated: 1x)
- consolidate_memories lets an LLM silently delete entries with no audit and no rollback — Write to a temp file, compare counts against the original, abort if the new set is less than 50% the old size or missing timestamp prefixes. Take a backup (filepath.with_suffix(.bak)) before overwrite. Return a structured result (original_count, new_count, removed_ids) so callers can detect anomalies. Fix the always-returns-0 bug. (score: 16.5, validated: 1x)
- Telemetry sink race condition on shared m27_client — Wire a per-scenario sink through constructor injection or a context manager that does not mutate shared client state. Hold a process-wide lock around set/restore or, better, instantiate a dedicated M27Client per scenario so no shared mutable sink exists. (score: 16.5, validated: 1x)
- Unvalidated path traversal via fixture manifest — After every resolve() assert resolved.is_relative_to(self.fixture_root) and reject otherwise. Use shutil.copytree(symlinks=False) plus a pre-walk that rejects any symlink. Treat the manifest as untrusted input and validate it against a JSON schema before use. (score: 16.5, validated: 1x)
- Evidence threshold and DB checks silently bypassed when ProjectMemory unavailable — Fail closed. If ProjectMemory is None, raise RuntimeError or return False with reason 'safety subsystem unavailable'. Never default to permissive behavior on a security boundary. (score: 16.5, validated: 1x)
- Non-atomic write of LLM-generated content overwrites agent file with no rollback — Write to a sibling temp file (agent_path.with_suffix('.md.tmp')), fsync, then os.replace() to atomically swap. On failure, the original is untouched. Verify the temp file contains the expected length before swapping. (score: 16.5, validated: 1x)
- TOCTOU race between agent_path.exists() and write_text() — Use a process-level lock (fcntl.flock on a sentinel file in the agents dir) keyed by agent_name. Or make the existence check + write atomic via temp-file rename with O_EXCL. Or enforce uniqueness at the DB layer with a UNIQUE constraint on (project_path, name) and catch IntegrityError. (score: 16.5, validated: 1x)
- Successful fetch data clobbered when subsequent fetch fails — Per-source state isolation: keep results in local variables per fetch method and accumulate into instance attributes only at the end. On per-source failure, log clearly and use cached data for THAT source only without touching other sources' results. Add a 'stale' flag to results so downstream code knows freshness. (score: 16.5, validated: 1x)
- Untrusted upstream content embedded into templates enables prompt injection — Pin to specific commit SHAs and verify content hashes match expected values. Use a curated allowlist of known-safe patterns. Sanitize and escape descriptions before embedding: strip non-printable chars, escape markdown and HTML, reject any template containing suspicious patterns (shell commands, URLs, instruction-like text). Never use untrusted community content directly as template source. (score: 16.5, validated: 1x)
- Cache file has no integrity verification enabling trivial cache poisoning — Sign the cache file with HMAC using a key derived from a per-project secret, or store SHA256 hashes alongside entries and verify on load. Use atomic writes (write to temp file, fsync, rename) to prevent partial writes. Set restrictive file permissions (0600) on cache files. Validate schema and reject unknown fields on load. Consider keeping a chain of custody signed by the upstream commit hash. (score: 16.5, validated: 1x)
- Eager import of 14 submodules makes the entire facade hostage to a single failure — Either (a) split the facade into a thin re-export layer with try/except around each import, logging failures and substituting a stub that raises a more informative error on use, or (b) move all 14 submodules to lazy `__getattr__` access like the existing `ReviewBenchmarkRunner` pattern, so the package is always importable. Option (b) is more uniform and avoids the asymmetric design that the current code already partially adopts. (score: 16.5, validated: 1x)
- Exclude pattern matching is dangerously broad and ambiguous — Use a single, well-defined matching algorithm. Document the pattern syntax clearly. Consider using gitignore-style patterns for familiarity. (score: 16.5, validated: 1x)
- File names starting with dash interpreted as command-line options — Use a -- separator before positional arguments (cmd.append('--'); cmd.extend(files)), or validate file names to reject those starting with a dash. (score: 16.5, validated: 1x)
- Silent exception swallowing masks agent crashes as clean reviews — Track failed agents in a separate dict mapping agent_name to exception class and message. Log at WARNING with full traceback. Return a typed ReviewResult with findings, failed_agents, and partial flag. Refuse to mark a review complete if any required agent failed. (score: 16.5, validated: 1x)
- Synthesize fuzzy-bucketing silently merges semantically distinct issues — Bucket by (file_path, line_number, category, cwe_id) and only dedupe when all four match. Restrict fuzzy title merging to issues from the same source_agent or with the same cwe_id. Preserve all distinct suggested_fix values as a list. Never merge across different IssueCategory values. (score: 16.5, validated: 1x)
- TOCTOU race in path containment check undermines all downstream file ops — Canonicalize all input paths up front and pass resolved Path objects through the entire pipeline. Use O_NOFOLLOW for sensitive reads, and re-validate at each trust boundary. (score: 16.5, validated: 1x)
- Worktree delta apply is non-atomic; partial corruption of main worktree is unrecoverable — Use a journal/staging pattern: apply delta to a temp directory, fsync, then rename atomically per file. Maintain a reverse-delta for rollback. Verify the resulting tree before committing the apply. (score: 16.5, validated: 1x)
- Global MUSCLE_THINKING_MODE override is a footgun and a privilege-escalation vector — Either (a) restrict the override to a safe subset of stages (e.g., only the 'disabled'-by-default formatting stages) and refuse to override 'adaptive'-by-default stages; (b) require an explicit per-stage override syntax (e.g., MUSCLE_THINKING_MODE_OVERRIDE=fix_generation:disabled,verification:adaptive); or (c) at minimum emit a loud warning at startup if the env var is set, and log every call site that is affected. The override should never be fully silent. (score: 10.899999999999999, validated: 1x)
- THINKING_POLICY is a module-level mutable dict with no immutability guarantee — Use types.MappingProxyType({...}) to make the dict read-only at runtime while preserving dict-lookup syntax. Alternatively, store the policy in a frozen dataclass, a NamedTuple, or just use an if/elif chain with hardcoded values. The current design is mutable for no benefit. (score: 10.899999999999999, validated: 1x)
- No validation that THINKING_POLICY values are in VALID_THINKING_MODES, drift is silent — Add a module-level assertion or post-import sanity check: 'for stage, mode in THINKING_POLICY.items(): assert mode in VALID_THINKING_MODES, f"stage {stage} has invalid mode {mode}"'. This runs once at import time and fails fast. Alternatively, build THINKING_POLICY dynamically from VALID_THINKING_MODES. (score: 10.899999999999999, validated: 1x)
- Architectural schizophrenia: DB-first claim enforced only by comments — Either truly delete the read paths and make this class write-only into a dead-letter audit log, or invert the architecture: the class becomes a thin facade that ONLY reads/writes DB and markdown is generated as a derived artifact. Pick one. (score: 10.899999999999999, validated: 1x)
- Prompt injection from user-controlled entry into LLM calls that produce authoritative output — Strip or escape markdown control characters in entries. Use a strict schema-validated parser (e.g., Pydantic) for LLM JSON responses, not json.loads. For consolidate_memories, never blindly trust the LLM ordering; re-validate each returned entry by checking it parses as a real memory line (timestamp prefix, category, etc.). Cap prompt size with an explicit assertion. Consider running the LLM with a system prompt that explicitly forbids including content from user messages in the output. (score: 10.899999999999999, validated: 1x)
- Silent LLM fallback hides quality degradation; caller cannot distinguish no-LLM from LLM-garbage — Return a structured result that distinguishes LLM-succeeded, LLM-failed-used-fallback, and no-LLM-configured. Emit a counter or metric on fallback. For _m27_summarize_entry, refuse to truncate mid-word or mid-tag; find a clean break point or drop the entry entirely. Add a circuit breaker: after N consecutive fallback events, refuse to write rather than write garbage. (score: 10.899999999999999, validated: 1x)
- Empty or zero-scenario benchmark silently passes every gate — Refuse to run when len(scenarios) == 0 for any suite value, or require a minimum scenario count per suite as a hard precondition. Distinguish 'no scenarios' (hard fail) from 'scenarios present but quiet' (real result). (score: 10.899999999999999, validated: 1x)
- Telemetry recorder closed while results may still be read — Defer recorder.close() until after all summaries are computed, or use a context manager scoped to the data-extraction phase rather than the controller-run phase. Snapshot the events into plain Python objects inside the try block. (score: 10.899999999999999, validated: 1x)
- Reports directory is shared mutable state created in __init__ — Write to a temp file in the same directory, fsync, then os.replace to the final name. Include a timestamped suffix or a per-run subdirectory. Make mkdir lazy and tied to the actual write call rather than to construction. (score: 10.899999999999999, validated: 1x)
- Stable substring matchers weaken the oracle and hide regressions — Combine exact-text anchors for must-contain tokens with severity gates. Use a small DSL (regex with anchored groups) and a per-finding required-and-forbidden token set, plus a property-based fuzzer that flips one word at a time and asserts the matcher still distinguishes pass/fail. (score: 10.899999999999999, validated: 1x)
- Agent name derived from untrusted pattern with no defense-in-depth sanitization — After constructing the candidate path, call Path.resolve() and verify it is still within self.agents_dir.resolve(). Reject any path that escapes. Additionally, apply a strict allowlist regex (e.g., ^[a-z0-9_-]+$) and reject anything else. Never trust the LLM's output as a filename. (score: 10.899999999999999, validated: 1x)
- can_create_agent() and generate_agent() are not atomic — eviction race — Wrap the entire check+evict+create sequence in a single transaction or file lock. Better: have generate_agent() call can_create_agent() as the single source of truth, and treat the capacity check in generate_agent() as redundant (or remove it). The list_agents() call is also potentially racy with DB writes. (score: 10.899999999999999, validated: 1x)
- Backup failures are logged and ignored — proceed with destructive operation — Make backup a precondition. If backup fails, abort the operation and surface a hard error. At minimum, the user should be able to opt into a 'destructive mode' explicitly. Never silently degrade a safety guarantee. (score: 10.899999999999999, validated: 1x)
- DB updates and file writes are not transactional — partial state on failure — Stage the new content as a pending revision in the DB first, then atomically swap the file (via os.replace), then mark the revision as committed in the DB. If the swap fails, the DB knows there is a pending revision and can recover. (score: 10.899999999999999, validated: 1x)
- Race condition in cache writes and reads causes inconsistent state under concurrent use — Use atomic write pattern: write to a temp file in the same directory, fsync, then os.replace() to the final path. Use file locking (fcntl.flock) around the read-modify-write cycle. Add JSON schema validation on load and on save. Consider a version field in the cache to detect concurrent writers. (score: 10.899999999999999, validated: 1x)
- Fragile regex parser breaks silently on upstream README format changes — Use a proper markdown parser (e.g., mistune, markdown-it-py) rather than regex. Validate that the parsed result is structurally reasonable (minimum expected number of agents). Log a warning when parse yield drops below a threshold compared to the cache. Have a canary entry check. Document the expected README format and version-pin to a specific format version. (score: 10.899999999999999, validated: 1x)
- Hardcoded /main branch assumption fails when repos rename or move default branch — Query the GitHub API to discover the default branch (one extra HTTP call, cached). Or attempt both main and master with a fallback strategy. Better: pin to specific commit SHAs and update them via a controlled release process. This is a known-good vendoring pattern that trades freshness for reliability. (score: 10.899999999999999, validated: 1x)
- Asymmetric lazy loading: `ReviewBenchmarkRunner` is special-cased while 13 siblings are eagerly loaded — Standardize on one of two patterns: either move everything to lazy `__getattr__` (and drop the explicit imports + the explicit `__all__` literal of classes), or remove the lazy escape hatch and use explicit deferred loading only in the modules that genuinely need it. Whichever you pick, the rationale should be documented, and the choice should not be ad hoc per class. (score: 10.899999999999999, validated: 1x)
- `__all__` and `__getattr__` are inconsistent, and `__all__` controls wildcard import security in surprising ways — Make the explicit list the single source of truth. Either add `ReviewBenchmarkRunner` to `__all__` (and accept the cost of the explicit import) or remove the lazy special case entirely. The two surfaces (wildcard imports and attribute access) should agree. (score: 10.899999999999999, validated: 1x)
- Bandit command conflicts with explicit file list causing unpredictable scanning — Remove the -r flag when passing explicit files, or use a single directory argument. Better yet, detect the tool's expected invocation pattern and adapt the file-passing logic accordingly. (score: 10.899999999999999, validated: 1x)
- Parallel tool execution can corrupt shared cache files — Run each tool in an isolated temporary directory with copies of the target files, or use per-tool working directories. At minimum, disable caching for tools that support it. (score: 10.899999999999999, validated: 1x)
- Hard 300-second timeout silently drops all findings — Capture partial output from the subprocess before it times out. Store the partial output in the evidence. Distinguish between tool timed out and tool found no issues in the result. (score: 10.899999999999999, validated: 1x)
- Tool output parsing trusts tool exit codes blindly — Validate parsed output against expected schema. Distinguish between tool found issues and tool encountered an error based on the actual output content. (score: 10.899999999999999, validated: 1x)
- No retry or fallback when tools are missing — Log a WARNING (not INFO) when a tool is missing. Consider falling back to an alternative tool if available. For critical security tools, make their absence a hard failure. (score: 10.899999999999999, validated: 1x)
- Tool output is stored in full including potentially sensitive data — Sanitize tool output before storage. Redact patterns that look like secrets. Limit the size of stored output. (score: 10.899999999999999, validated: 1x)
- Token accounting has write/read race and destructive consume pattern — Acquire self._token_lock inside _record_agent_tokens for every write. Replace pop with a non-destructive get that resets the counter, or use a per-agent deque of usage events drained by exactly one consumer under the lock. Document the threading contract explicitly. (score: 10.899999999999999, validated: 1x)
- Deterministic fast-path skips LLM based on regex false-positives — Never skip the LLM based on a positive finding. Use deterministic findings to AUGMENT the LLM review, not replace it. If cost reduction is the goal, run deterministic in parallel and let synthesis merge. Require the file to be in an allow-list of safe patterns before the fast path triggers. (score: 10.899999999999999, validated: 1x)
- Hardcoded secret regex captures the secret value in findings — Redact the matched value in code_snippet (e.g., replace with a length-and-prefix marker). Never include the literal secret in any field that crosses a trust boundary. Add a post-processing step that scrubs known secret patterns from all output fields. Hash the value to a short fingerprint for recurring detection without storage. (score: 10.899999999999999, validated: 1x)
- Prompt injection via attacker-controlled target_path and static_issues — Treat all external strings as untrusted. Sanitize before logging. Never include raw user content in LLM prompts without explicit delimiters and an instruction to ignore instructions within the content. Use structured input schemas with whitelisted fields. Log a hash or length of input rather than content itself. (score: 10.899999999999999, validated: 1x)
- _fix_locks dict leaks unboundedly and is not shared across controller instances — For multi-process safety use OS-level file locks (fcntl.flock, portalocker). For in-process use, register locks in a WeakValueDictionary. Document that the lock is in-process only. (score: 10.899999999999999, validated: 1x)
- Silent fallback to hybrid mode masks invalid configuration — Validate config.mode in __init__ and add an explicit else branch that raises ValueError. Use an exhaustive match-statement that the type checker enforces. (score: 10.899999999999999, validated: 1x)
- event_callback exceptions abort the review silently and leave partial state — Wrap event_callback in a try/except that logs the failure and continues. Treat event emission as fire-and-forget for observability. (score: 10.899999999999999, validated: 1x)
<!-- MUSCLE_PUBLISHED_END -->
