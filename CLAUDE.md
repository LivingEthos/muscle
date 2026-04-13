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

### Core Runtime Flows (tools/muscle/)

The active package has two main runtime flows:

1. `muscle run`: **LoopController -> CodeGenerator -> EvaluatorRegistry -> Evolver**
2. `muscle review`: **ReviewController -> StaticAnalyzer -> CodeReviewer -> LearningPipeline**

| Module | Role |
|--------|------|
| `cli.py` | Click-based CLI entry point. All commands defined here. |
| `m27_client.py` | HTTP client for MiniMax M2.7 via Anthropic-compatible API. Handles streaming, retries, JSON recovery from truncated responses. |
| `loop_controller.py` | Orchestrates generate-evaluate-fix loops with event callbacks. |
| `session_manager.py` | File-based session persistence and resume under `.muscle/sessions/<session_id>/`. |
| `budget_manager.py` | Token/cost budget tracking and enforcement. |
| `code_generator.py` | Prompts M2.7 for code, parses fenced code blocks, and writes generated files. |
| `evaluator_registry.py` | Picks compiler/test/lint evaluators by language and aggregates results. |
| `evolver.py` | Turns failures into an improved next strategy, with optional StrategyKB lookup. |

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

### Other Subsystems

- **`evaluators/`** - Pluggable evaluators: compiler, linter, tester, assertions. Registered via `evaluator_registry.py`.
- **`adapters/`** - Git, GitHub, GitLab, Jenkins, MCP integrations.
- **`tui/`** - Rich-based terminal UI with views and project manager.

### Claude Code Plugin (`tools/muscle/plugin/`)

The plugin bundle contains slash-command definitions, hooks, skills, and subagent docs for the MUSCLE product. When working on this repository, edit and verify those files as source artifacts rather than assuming the plugin workflow itself is part of your development loop.

### Data Storage

Per-project state:

- `.muscle/config.yaml` - JSON content written by `ProjectManager`
- `.muscle/strategy_kb.json` - bootstrap strategy metadata file
- `.muscle/knowledge/strategies.db` - StrategyKB SQLite database
- `.muscle/review_kb/review_kb.db` - ReviewKB SQLite database
- `.muscle/sessions/<session_id>/` - `meta.json`, `iterations.jsonl`, `report.json`, `context.json`, artifacts
- `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, `.muscle/MEMORY.md`
- `.muscle/skills/`, `.muscle/agents/`, `.muscle/reports/`, `.muscle/logs/`

Global state:

- `~/.muscle/cache/cache.db`
- `~/.muscle/shadow_jobs.json`
- `~/.muscle/improvement_log.json`
- `~/.muscle/prompts/`
- `~/.muscle/global/strategies.db`
- `~/.muscle/global_review/review_kb.db`
- `~/.muscle/<session_id>.pid`

## Current Maturity Notes

- `tools/muscle/` is the active package tree. `tools/scle/` is legacy.
- The TUI is a working shell, but several views still render placeholder/sample data.
- GitHub, GitLab, Jenkins, and MCP adapters exist as modules, but not all are first-class CLI workflows yet.
- `LearningPipeline` is wired after reviews and memory-file updates are real today. The deeper recurring-pattern ecosystem is present and still maturing.
- Some plugin docs are currently stale. In particular, do not rely on `muscle shadow ...` examples or `muscle settings platform --hooks`; use the actual CLI help instead.

## Key Patterns

- **API Client**: `M27Client` uses direct HTTP calls against MiniMax's Anthropic-compatible API and includes retry, rate limiting, and JSON recovery behavior.
- **Event-driven loops**: `LoopController` emits `LoopEvent` callbacks for streaming, evaluation, and iteration tracking.
- **Review modes**: `review`, `auto-fix`, `plan`, `hybrid`, `pressure` are defined in `tools/muscle/code_review/types.py`.
- **Types**: Core types in `tools/muscle/types.py` use dataclasses, not Pydantic.

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

<!-- MUSCLE_PUBLISHED_START -->
### Critical Rules

### Frequent Mistakes

### Active Agent Calls

### Active Skill Calls

### Tooling Notes

<!-- MUSCLE_PUBLISHED_END -->
