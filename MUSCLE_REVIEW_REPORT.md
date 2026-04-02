# MUSCLE Review Report

Date: 2026-04-01

## Scope

Reviewed the current MUSCLE application with emphasis on production gaps that would not be caught by the existing green test suite. The main implemented fix in this pass targets session recovery and the `muscle resume` workflow.

## Findings

### Fixed

1. `muscle resume` was still a stub.
   The CLI loaded session metadata, printed a message, and exited without actually resuming work. This was a production-facing broken command because the app and plugin docs advertise resume support.

2. Session metadata was incomplete for safe recovery.
   Session persistence did not save enough run configuration to faithfully rebuild a previous run. Important resume inputs such as `budget_tokens`, `allow_warnings`, `interactive`, `kb_path`, `early_exit_on`, and the original working directory were not persisted.

3. Relative output paths were unsafe on resume.
   Sessions stored `output_dir` as provided. If a session was started with a relative path like `.`, resuming it from a different working directory could target the wrong files.

4. Resuming a session that had exhausted `max_iterations` would immediately fail again.
   Even with checkpoint loading, a resumed context would have hit the same total iteration cap unless the controller explicitly extended the limit.

5. Resume behavior had no direct test coverage.
   The existing suite covered `run`, `abort`, and session persistence, but not the end-to-end resume path.

### Not fixed in this pass

1. Integration-heavy adapters remain the largest residual risk.
   Existing coverage artifacts still show relatively low coverage in `github_integration.py`, `github.py`, `jenkins.py`, and some TUI runtime paths. Those areas deserve a separate hardening pass with higher-fidelity integration tests.

2. Resume currently restores core loop state, not every CLI-only runtime toggle.
   The implemented flow restores the run configuration needed for loop correctness. Optional runtime integrations like webhook destinations and git auto-push behavior are not yet persisted as first-class resume metadata.

## Fixes Implemented

### Real resume support

- Added checkpoint loading in `SessionManager`.
- Added iteration history parsing from `iterations.jsonl`.
- Added safe resume metadata handling, including stale PID cleanup and active-process detection.
- Added resume bookkeeping via `resume_count` and `resumed_at`.

### Safer state reconstruction

- Persisted resume-critical config fields when creating sessions.
- Persisted `working_dir` and now resolve relative `output_dir` values against the original launch directory.
- Rebuild evolved strategy from `context.json`, with fallback to the last saved iteration strategy.

### Controller support for continuation

- `LoopController.run()` now accepts an existing `LoopContext`.
- Resumed sessions reuse the original session ID and append to the same session history instead of creating a new session.
- When a prior run already hit its iteration cap, resume extends the total cap so the session can actually continue.

### Budget continuity

- `BudgetManager` now supports starting with already-consumed fixed-budget tokens so resumed sessions continue from the correct remaining budget.
- Resume blocks immediately if the session has already exhausted a fixed budget.

### Test coverage added

- Added resume-specific tests in:
  - `tests/unit/test_session_manager.py`
  - `tests/unit/test_loop_controller.py`
  - `tests/unit/test_cli.py`

## Files Changed

- `tools/muscle/session_manager.py`
- `tools/muscle/loop_controller.py`
- `tools/muscle/budget_manager.py`
- `tools/muscle/cli.py`
- `tests/unit/test_session_manager.py`
- `tests/unit/test_loop_controller.py`
- `tests/unit/test_cli.py`

## Validation

Executed successfully:

- `uv run mypy tools/muscle/`
- `uv run ruff check tools/muscle/`
- `uv run ruff format --check tools/muscle/`
- `uv run pytest tests/unit/test_session_manager.py tests/unit/test_loop_controller.py tests/unit/test_cli.py -v`
- `uv run pytest tests/ -q`

## Recommended Next Pass

1. Persist and restore optional runtime integrations for resume, especially webhook and git settings.
2. Add higher-fidelity integration coverage for GitHub, Jenkins, and TUI runtime flows.
3. Add one CLI integration test that creates a real on-disk failed session and resumes it without heavy mocking.
