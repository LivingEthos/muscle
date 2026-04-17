# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MUSCLE (MiniMax Unified Self-Correcting Learning Engine) is a local-first code review and iterative code-generation tool that uses the MiniMax M2.7 model via an Anthropic-compatible API.

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

### Two Package Trees

- **`tools/muscle/`** - Active development. The main MUSCLE package, installed as the `muscle` CLI via `pyproject.toml` entry point (`tools.muscle.cli:main`).
- **`tools/scle/`** - Legacy predecessor ("SCLE"). Shares similar structure but is not actively developed. Do not confuse the two.

### Core Runtime Flows (tools/muscle/)

The active package has two main runtime flows:

1. `muscle run`: **LoopController -> CodeGenerator -> EvaluatorRegistry -> Evolver**
2. `muscle review`: **ReviewController -> StaticAnalyzer -> CodeReviewer -> LearningPipeline**

| Module | Role |
|--------|------|
| `cli.py` | Click-based CLI entry point. All commands defined here. |
| `m27_client.py` | HTTP client for MiniMax M2.7 via Anthropic-compatible API. Streaming, retries, JSON recovery from truncated responses. |
| `loop_controller.py` | Orchestrates generate-evaluate-fix loops with event callbacks. |
| `session_manager.py` | File-based session persistence and resume under `.muscle/sessions/<session_id>/`. |
| `budget_manager.py` | Token/cost budget tracking and enforcement. |
| `code_generator.py` | Prompts M2.7 for code, parses fenced code blocks, writes generated files. |
| `evaluator_registry.py` | Picks compiler/test/lint evaluators by language and aggregates results. |
| `evolver.py` | Turns failures into an improved next strategy, with optional StrategyKB lookup. |
| `project_manager.py` | Per-project bootstrap, config, and `.muscle/` layout management. |
| `project_memory.py` / `project_memory_schema.py` / `project_memory_types.py` | Project-local SQLite store (`project_memory.db`) — the **source of truth** for rules, learnings, shadow jobs, fix tracking, and audit trail. See `migrations/`. |
| `project_fingerprint.py` | Computes project identity and relatedness signals for cross-project learning. |
| `project_notes.py` | User notes persisted in `project_memory.db`. |
| `system_db.py` | Global SQLite store (`~/.muscle/system.db`) for fingerprints, aliases, model-pack cache. |
| `learning_ingestor.py` | Ingests and validates learning signals from completed reviews. |
| `memory_decision_engine.py` | Scores and promotes findings from `project_memory.db` into publishable rules. |
| `claude_publisher.py` | Publishes DB-backed content into root `CLAUDE.md` via `MUSCLE_PUBLISHED_START/END` markers. Enforces per-section size caps and M2.7 consolidation. |
| `lesson_resolver.py` | Resolves the effective lesson set (project + related projects + model pack). |
| `model_identity.py` / `model_packs.py` / `model_pack_standard.py` / `model_pack_validation.py` | Canonical model identity and model-pack overlay system. |
| `audit_presenter.py` | Formats audit/trace output for CLI + TUI consumption. |
| `change_capture.py` | Captures repo-side changes for learning signals. |
| `legacy_importer.py` | Imports legacy markdown / JSON formats into `project_memory.db`. |
| `transferable_lesson_scrubber.py` | Scrubs project-specific details from lessons before export. |
| `backup_manager.py` | Backup/restore for managed files prior to writes (used by publisher and by the host-docs optimizer). |
| `cost_optimizer.py` | Cost tracking and budget-aware optimization helpers. |
| `optimization/` | Context budgeting, prompt optimization, session recording, and external-session importers (Claude Code + Codex). See `optimization/importers.py`. |

### Code Review Subsystem (tools/muscle/code_review/)

| Module | Role |
|--------|------|
| `review_controller.py` | Orchestrates full review flow across modes (review, auto-fix, plan, hybrid, pressure). |
| `code_reviewer.py` | Sends code to M2.7 for analysis, parses structured findings. |
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

- `tools/muscle/` is the active package tree. `tools/scle/` is legacy.
- DB-first architecture is wired: `project_memory.db` is authoritative for rules and learnings; `claude_publisher.py` publishes DB-backed content to root `CLAUDE.md`.
- The TUI is live against `project_memory.db` for review runs, model-identity history, and lesson-usage history. Some advanced panels still render lighter/placeholder data per `docs/architecture.md`.
- GitHub, GitLab, Jenkins, and MCP adapters exist as modules, but not all are first-class CLI workflows yet.
- `LearningPipeline` is wired after reviews and memory-file updates are real today. The deeper recurring-pattern ecosystem is present and still maturing.
- Codex-side session imports exist via `optimization/importers.py` (reads `$CODEX_HOME/sessions`). No `AGENTS.md` publishing exists today — added by the delegation-overhaul plan (`PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`).
- Some plugin docs are currently stale. In particular, do not rely on `muscle shadow ...` examples or `muscle settings platform --hooks`; use the actual CLI help instead.

## Host Model Contract (Opus 4.7 / Codex)

MUSCLE's plugin output is consumed by either **Claude Code (Opus 4.7)** or **Codex**. The plugin itself never needs an Anthropic API key — it authenticates to **MiniMax M2.7** via `MINIMAX_API_KEY` (or the legacy alias `ANTHROPIC_API_KEY`, which points to MiniMax's Anthropic-compatible endpoint, **not** real Anthropic).

Guidance for editing MUSCLE prompts and plugin artifacts:

- **Plan-then-hand-off division of labor.** Opus 4.7 / Codex keep the planning, synthesis, and user-interaction roles. MUSCLE's M2.7 agents are the execution muscle (bulk multi-file review, test/lint sweeps, fix-candidate generation, pattern scans) — ~5–10× cheaper per token. Write prompt templates that reinforce this split, not the reverse.
- **Opus 4.7 interprets prompts literally.** Use positive, directive phrasing; name tools and commands explicitly; avoid negative "don't do X" framings when a positive equivalent exists.
- **Opus 4.7 spawns fewer subagents / tool calls by default.** If a prompt requires a specific delegation (rescue agent, verification agent), spell out the trigger conditions.
- **Auto mode is in scope.** Delegation hand-offs must work without inter-step confirmation when the user is in auto mode.
- **Do not add an Anthropic fallback in `m27_client.py`** without first stripping `temperature`, `top_p`, `top_k` (400 errors on Opus 4.7). MUSCLE calls MiniMax; keep it that way unless there's a concrete reason to change.

## Delegation Economics

- Claude Code (Opus 4.7) ≈ **$5 / $25 per MTok**; Codex hosts are in a similar range. MiniMax M2.7 is ~**5–10× cheaper** for equivalent review-scoped reasoning.
- MUSCLE's plan (see `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`) writes a pinned **Methodology + Delegation Protocol + Effort Guidance** section into every reviewed project's `CLAUDE.md` and `AGENTS.md` so the host model hands bulk execution off to MUSCLE's M2.7 agents (`/muscle:review`, `/muscle:rescue`, `/muscle:pressure`, verification agent) while keeping planning and synthesis with itself.
- The plugin manifest at `tools/muscle/plugin/.claude-plugin/plugin.json` is **manually curated** — new slash commands require updating the manifest's `description` field as well as adding the command file.

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
| `CODEX_HOME` | Codex session root for `optimization/importers.py` (default: `~/.codex`). |

## Testing Conventions

- All tests in `tests/unit/` with `test_` prefix matching the module name.
- Heavy use of `unittest.mock` - shared fixtures in `tests/conftest.py` (mock_subprocess, mock_requests, mock_sqlite3, temp_project_dir).
- Uses `pytest-asyncio` with `asyncio_mode = "auto"`.
- Coverage source is `tools.muscle`, excluding `tools/scle/`.

## Tool Configuration

- **Ruff**: line-length 100, target Python 3.10, rules: E, F, W, I, N, UP, B, C4. E501 ignored.
- **Mypy**: strict (`disallow_untyped_defs`, `warn_return_any`).
- Python 3.10+ required.

<!-- MUSCLE_PUBLISHED_START -->
### Critical Rules

### Frequent Mistakes

### Active Agent Calls

### Active Skill Calls

### Tooling Notes

<!-- MUSCLE_PUBLISHED_END -->
