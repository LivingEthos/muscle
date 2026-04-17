# PROJECT_INDEX.md

Navigational index for the MUSCLE repository. For maintainer guidance, see `CLAUDE.md`. For runtime/persistence design, see `docs/architecture.md`. For product roadmap, see `MUSCLE_PLAN.md`. For the active plugin overhaul, see `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`.

## Quick Links

| File | Role |
|------|------|
| `CLAUDE.md` | Maintainer guide — Claude Code working on this repo reads this first. |
| `AGENTS.md` | Cross-tool development guide (code style, CLI, tests). Hand-authored; not plugin-published. |
| `MUSCLE_PLAN.md` | Product roadmap and phase tracker. |
| `docs/architecture.md` | Runtime + persistence design (authoritative for actual state). |
| `docs/REMAINING_TODOS.md` | Open findings from the 2026-04-16 production audit. |
| `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md` | Active plan: Opus 4.7 delegation-first plugin + CLAUDE.md/AGENTS.md overhaul. |
| `README.md` | Public-facing overview. |

## Directory Map

### `tools/muscle/` — Active implementation

| Layer | Files |
|-------|-------|
| CLI entry | `cli.py`, `__main__.py` |
| Model client | `m27_client.py`, `cost_optimizer.py` |
| Core types | `types.py` |
| Code-gen loop | `loop_controller.py`, `code_generator.py`, `evaluator_registry.py`, `evolver.py`, `session_manager.py`, `budget_manager.py` |
| Project state | `project_manager.py`, `project_memory.py`, `project_memory_schema.py`, `project_memory_types.py`, `project_fingerprint.py`, `project_notes.py`, `system_db.py` |
| Learning + publishing | `learning_ingestor.py`, `memory_decision_engine.py`, `claude_publisher.py`, `lesson_resolver.py`, `audit_presenter.py`, `change_capture.py`, `legacy_importer.py`, `transferable_lesson_scrubber.py`, `backup_manager.py` |
| Model identity + packs | `model_identity.py`, `model_packs.py`, `model_pack_standard.py`, `model_pack_validation.py` |
| Knowledge base | `strategy_kb.py` |
| Migrations | `migrations/*.py` (schema evolution for `project_memory.db`) |

### `tools/muscle/code_review/` — Review subsystem

| Role | Files |
|------|-------|
| Controllers | `review_controller.py`, `review_workflows.py`, `review_scope.py` |
| Reviewers | `code_reviewer.py`, `committee_reviewer.py`, `pressure_reviewer.py`, `static_analyzer.py` |
| Fixes + verification | `fix_generator.py`, `fix_tracker.py`, `verification_loop.py`, `worktree_manager.py` |
| Artifacts + handoff | `handoff_generator.py`, `review_artifacts.py` |
| Learning loop | `learning_pipeline.py`, `pattern_detector.py`, `memory_manager.py`, `strategy_evolver.py` |
| Knowledge base | `review_kb.py`, `review_benchmark.py`, `agent_kb_fetcher.py` |
| Skills + agents | `skill_generator.py`, `agent_generator.py` |
| Background + shadow | `shadow_broker.py`, `shadow_worker.py`, `nightly_runner.py`, `long_eval_runner.py` |

### `tools/muscle/optimization/` — Context + session tooling

| Role | Files |
|------|-------|
| Context + prompt | `context_budgeter.py`, `prompt_optimizer.py`, `recorder.py` |
| External sessions | `importers.py` (Claude Code + Codex session imports), `optimizer.py` (WorkflowOptimizer) |

### `tools/muscle/adapters/` — External integrations

`git_adapter.py`, `github.py`, `gitlab.py`, `jenkins.py`, `mcp_client.py`. Modules exist; not all are first-class CLI workflows yet.

### `tools/muscle/evaluators/` — Pluggable evaluators

Compiler, linter, tester, assertion evaluators. Registered via `evaluator_registry.py`.

### `tools/muscle/tui/` — Terminal UI

`views.py`, `project_manager.py`. Live against `project_memory.db` for review runs, model identity, lesson usage.

### `tools/muscle/plugin/` — Claude Code plugin bundle

| Subdir | Role |
|--------|------|
| `.claude-plugin/plugin.json` | Plugin manifest. **Manually curated** — adding a slash command requires updating the manifest's `description` field. |
| `commands/` | 30+ slash-command `.md` files (`review.md`, `pressure.md`, `rescue.md`, `settings-model.md`, `model-pack-*.md`, etc.). |
| `skills/code-review/SKILL.md` | Primary code-review skill consumed by the host model. |
| `agents/` | Subagent docs: `rescue_agent.md`, `verification_agent.md`. |

### `tools/scle/` — Legacy (not maintained)

Do not edit except to remove.

### `tests/`

`tests/unit/` mirrors `tools/muscle/` modules. `tests/integration/` covers lifecycle + CLI end-to-end. Shared fixtures in `tests/conftest.py`.

## Data Storage

Per-project (`.muscle/`):
- **`project_memory.db`** — authoritative SQLite store (rules, learnings, shadow jobs, fix tracking, audit). Schema in `project_memory_schema.py`; migrations in `migrations/`.
- `config.yaml`, `sessions/`, `skills/`, `agents/`, `reports/`, `logs/`, `consolidation_audit.jsonl`
- Internal (non-authoritative): `CLAUDE.md`, `AGENT.md`, `MEMORY.md`
- Legacy/migrating: `strategy_kb.json`, `knowledge/strategies.db`, `review_kb/review_kb.db`

Global (`~/.muscle/`):
- `system.db` (fingerprints, aliases, model-pack cache), `cache/cache.db`, `improvement_log.json`, `prompts/`, `<session_id>.pid`

## Key Data Flow

Review completes → `LearningPipeline.learn_from_review()` → `project_memory.db` (via `LearningIngestor`) → `MemoryDecisionEngine` scores → `ClaudePublisher.publish()` writes root `CLAUDE.md` inside `MUSCLE_PUBLISHED_START/END` markers (size-capped, M2.7-consolidated on overflow). `MemoryManager` also mirrors to `.muscle/` internal markdowns.

## Testing

- Run: `uv run pytest tests/`
- Quality gates: `uv run mypy tools/muscle/`, `uv run ruff check tools/muscle/`, `uv run ruff format --check tools/muscle/`
- Coverage source: `tools.muscle` (excludes `tools/scle/`)
- `pytest-asyncio` with `asyncio_mode = "auto"`
- **Baseline as of 2026-04-17:** ruff + format clean; mypy has 4 pre-existing non-blocking errors (unused `type: ignore` at `code_review/review_workflows.py:17`, `tui/views.py:901`; `orjson` missing-stub at `cli.py:20`; `Any` return at `cli.py:1974`). Test suite: `test_cli.py::TestTuiCommand::test_tui_runs` fails in non-terminal test environments due to `readkey()` requiring real stdin — pre-existing environmental issue, not a code defect.

## Known Gaps

See `docs/REMAINING_TODOS.md` for the full 2026-04-16 audit findings. Key items overlap with the delegation plan:
- `AGENTS.md` publishing is **not yet implemented** — added by `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`.
- Host-docs optimizer (non-destructive reorganization of existing `CLAUDE.md`/`AGENTS.md`) is planned, not built.
- `ClaudePublisher.publish()` currently hardcodes a single output path (`self.project_path / "CLAUDE.md"` in `claude_publisher.py:75`) — multi-file publishing requires refactor.
