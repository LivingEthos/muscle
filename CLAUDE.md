# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MUSCLE (MiniMax Unified Self-Correcting Learning Engine) is a self-learning code review tool that uses the MiniMax M2.7 model via an Anthropic-compatible API. It reviews code, traces root causes, auto-fixes issues, and evolves its review strategies over time through a per-project SQLite knowledge base.

## Build & Development Commands

```bash
# Install dependencies (uses uv package manager)
uv sync --dev

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/unit/test_cli.py -v

# Run a single test by name
uv run pytest tests/unit/test_cli.py -k "test_review_command" -v

# Quality gates (ALL must pass before merging)
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

### Core Pipeline (tools/muscle/)

The system follows a pipeline: **Review Controller -> Pattern Detector -> Skill/Agent Generator -> Memory Manager**.

| Module | Role |
|--------|------|
| `cli.py` | Click-based CLI entry point. All commands defined here. |
| `m27_client.py` | HTTP client for MiniMax M2.7 via Anthropic-compatible API. Handles streaming, retries, JSON recovery from truncated responses. |
| `loop_controller.py` | Orchestrates generate-evaluate-fix loops with event callbacks. |
| `session_manager.py` | SQLite-backed session persistence and resume. |
| `budget_manager.py` | Token/cost budget tracking and enforcement. |

### Code Review Subsystem (tools/muscle/code_review/)

| Module | Role |
|--------|------|
| `review_controller.py` | Orchestrates full review flow across modes (review, auto-fix, plan, hybrid, pressure). |
| `code_reviewer.py` | Sends code to M2.7 for analysis, parses structured findings. |
| `pattern_detector.py` | Identifies recurring patterns across reviews. |
| `memory_manager.py` | Manages CLAUDE.md/AGENT.md/MEMORY.md updates with structured rules. |
| `learning_pipeline.py` | Orchestrates self-learning after reviews (pattern detection -> strategy evolution -> memory update). |
| `skill_generator.py` | Generates project-specific Claude Code skills from detected patterns. |
| `agent_generator.py` | Creates specialized sub-agents for complex review tasks. |
| `shadow_broker.py` / `shadow_worker.py` | Background (shadow mode) review job queue and workers. |
| `nightly_runner.py` | Cron-based nightly analysis with morning reports. |
| `strategy_evolver.py` | Evolves review strategies based on validated effectiveness. |
| `fix_tracker.py` | Tracks fix attempts and their outcomes. |

### Other Subsystems

- **`evaluators/`** - Pluggable evaluators: compiler, linter, tester, assertions. Registered via `evaluator_registry.py`.
- **`adapters/`** - Git, GitHub, GitLab, Jenkins, MCP integrations.
- **`tui/`** - Rich-based terminal UI with views and project manager.

### Claude Code Plugin (`tools/muscle/plugin/`)

The plugin provides slash commands (`/muscle:review`, `/muscle:pressure`, etc.), subagents (rescue, verification), hooks, and skills. Commands shell out to the `muscle` CLI.

### Data Storage

- Per-project SQLite DB at `.muscle/project.db` - patterns, fixes, session history.
- Global config at `~/.muscle/global_config.yaml`.
- Strategy KB at `.muscle/strategy_kb.json`.

## Key Patterns

- **API Client**: `M27Client` uses the Anthropic SDK format but routes to MiniMax (`ANTHROPIC_BASE_URL`). It implements JSON recovery for truncated M2.7 responses using regex extraction.
- **Event-driven loops**: `LoopController` emits `LoopEvent` callbacks for streaming, evaluation, and iteration tracking.
- **Review modes**: `review`, `auto-fix`, `plan`, `hybrid`, `pressure` - each with different fix/report behavior configured via `RunConfig`.
- **Types**: Core types in `tools/muscle/types.py` use dataclasses (not Pydantic). Code review types in `tools/muscle/code_review/types.py`.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `MINIMAX_API_KEY` or `ANTHROPIC_API_KEY` | API authentication |
| `ANTHROPIC_BASE_URL` | API endpoint (default: `https://api.minimax.io/anthropic`) |

## Testing Conventions

- All tests in `tests/unit/` with `test_` prefix matching the module name.
- Heavy use of `unittest.mock` - shared fixtures in `tests/conftest.py` (mock_subprocess, mock_requests, mock_sqlite3, temp_project_dir).
- Uses `pytest-asyncio` with `asyncio_mode = "auto"`.
- Coverage source is `tools.muscle`, excluding `tools/scle/`.

## Tool Configuration

- **Ruff**: line-length 100, target Python 3.10, rules: E, F, W, I, N, UP, B, C4. E501 ignored.
- **Mypy**: strict (`disallow_untyped_defs`, `warn_return_any`).
- Python 3.10+ required.

## context-mode -- MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional -- they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session.

### BLOCKED commands -- do NOT attempt these

**curl / wget**: Intercepted and replaced with error. Use `ctx_fetch_and_index(url, source)` or `ctx_execute(language: "javascript", code: "const r = await fetch(...)")`.

**Inline HTTP**: Intercepted. Use `ctx_execute(language, code)` to run HTTP calls in sandbox.

**WebFetch**: Denied entirely. Use `ctx_fetch_and_index(url, source)` then `ctx_search(queries)`.

### REDIRECTED tools -- use sandbox equivalents

**Bash (>20 lines output)**: Use `ctx_batch_execute(commands, queries)` or `ctx_execute(language: "shell", code: "...")`.

**Read (for analysis)**: If reading to Edit, Read is correct. If reading to analyze/explore, use `ctx_execute_file(path, language, code)`.

### Tool selection hierarchy

1. `ctx_batch_execute(commands, queries)` -- run multiple commands + search in ONE call
2. `ctx_search(queries)` -- query indexed content
3. `ctx_execute(language, code)` / `ctx_execute_file(path, language, code)` -- sandbox execution
4. `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` -- web content
5. `ctx_index(content, source)` -- store content for later search
