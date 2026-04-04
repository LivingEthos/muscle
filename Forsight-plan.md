# Experimental Foresight Preflight + Shared Short-Term Memory

## Summary

- Add an opt-in experimental `foresight` workflow that lets MUSCLE do a lightweight preflight before a Claude Code task runs.
- Support both forms the user chose:
  - one-shot: `/foresight <task>`
  - session mode: `/foresight on|off|status`
- Write a temporary `Foresight` section into the root `CLAUDE.md`, then remove it when that MUSCLE-managed task tree completes.
- Add a shared short-term memory file at `.muscle/MUSCLE_SHORT_TERM.md`, capped at 50 non-empty lines, for immediate cross-agent notes that all M2.7 helpers can read.
- Keep this feature strictly separate from long-term learning: preflight may read/rank/summarize, but it must not promote new long-term rules on its own.

## Key Changes

- Add a new CLI group in `tools/muscle/cli.py`:
  - `muscle foresight run --prompt <text> [--scope main|subagent] [--task-id ...]`
  - `muscle foresight enable`
  - `muscle foresight disable`
  - `muscle foresight status`
  - `muscle foresight refresh-short-term`
- Extend project config in `tools/muscle/tui/project_manager.py` with:
  - `foresight_enabled: bool`
  - `foresight_experimental: bool`
  - `foresight_use_root_claude: bool`
  - `foresight_use_shared_short_term: bool`
- Add a new runtime module such as `tools/muscle/foresight_manager.py` that owns:
  - prompt intake
  - candidate retrieval from `ProjectMemory`, `.muscle/CLAUDE.md` rules, project notes, recent conversation events, and `.muscle/MUSCLE_SHORT_TERM.md`
  - one bounded M2.7 ranking/summarization call with fallback keyword ranking
  - temporary root `CLAUDE.md` injection and cleanup
  - task-tree reference counting so parent + child subagents share one foresight run
- Add a new shared-memory module such as `tools/muscle/short_term_memory.py` that owns:
  - `.muscle/MUSCLE_SHORT_TERM.md` creation
  - 50-line pruning
  - dedupe and freshness rules
  - optional refresh from recent high-confidence notes/events
- Add a new plugin slash command file `tools/muscle/plugin/commands/foresight.md`:
  - `/foresight <task>` runs one-shot preflight, then instructs Claude Code to continue the task with foresight active
  - `/foresight on|off|status` maps to the CLI enable/disable/status commands
- Add new root `CLAUDE.md` markers managed only by the runtime:
  - `<!-- MUSCLE_FORESIGHT_START -->`
  - `<!-- MUSCLE_FORESIGHT_END -->`
- Do not reuse `ClaudePublisher` for this path; keep temporary foresight isolated from published long-term sections so experimental writes cannot pollute the regular learning pipeline.

## Foresight Runtime Behavior

- `muscle foresight run` creates a `foresight_run_id`, logs a `conversation_event`, and gathers candidate context from:
  - relevant learned rules
  - recent project notes
  - recent task/review events
  - shared short-term memory
  - active skills/agents if they are directly relevant
- The preflight agent answers two bounded questions only:
  - what crucial context should Claude see first
  - what should Claude check or do before making changes
- The preflight agent does not execute prep work automatically in v1; it only injects concise guidance.
- The injected `Foresight` section should contain:
  - run id and owner task tree id
  - 3-8 compact bullets of crucial context
  - 1 short "check first" list if needed
  - 1 short "ignore for this task" list when stale or irrelevant context was intentionally excluded
- Cleanup occurs in `finally` for the owning task tree and only removes the managed foresight region.
- If a subagent participates, it reuses the parent `foresight_run_id`; cleanup waits until the tree refcount reaches zero.
- If cleanup fails or the process crashes, the next `foresight run` performs stale-marker recovery before injecting new content.
- If M2.7 ranking fails, fall back to deterministic keyword scoring and continue; foresight must never block normal work.

## Shared Short-Term Memory

- Create `.muscle/MUSCLE_SHORT_TERM.md` as the shared immediate notepad for all MUSCLE agents.
- Keep it file-first, with optional refresh from DB-backed notes/events; the markdown file is the canonical read target for agents.
- Format it as a tiny curated document with markers and strict limits:
  - max 50 non-empty lines
  - newest/most actionable items first
  - no long prose, no duplicated bullets, no archival history
- Allowed contents:
  - current repo-wide gotchas
  - active workflow reminders for stop hooks or task cleanup
  - validated "immediately useful" facts from recent runs
  - active coordination notes for MUSCLE-managed task trees
- Disallowed contents:
  - speculative lessons
  - verbose logs
  - stale completed-task chatter
  - anything already represented better in long-term `AGENT.md` or `CLAUDE.md`
- The foresight agent reads this file first and may include a small subset of its bullets in the temporary `Foresight` section.

## Multi-Agent Implementation Breakdown

- Worker 1: CLI + plugin surface
  - Own `tools/muscle/cli.py`, `tools/muscle/tui/project_manager.py`, and `tools/muscle/plugin/commands/foresight.md`
  - Add config flags, command handlers, status output, and slash-command wiring
- Worker 2: foresight runtime + root CLAUDE mutation safety
  - Own `tools/muscle/foresight_manager.py`
  - Implement run lifecycle, marker insertion/replacement/removal, lock/refcount handling, stale cleanup, and event logging
- Worker 3: retrieval + shared short-term memory
  - Own `tools/muscle/short_term_memory.py` plus any small retrieval helpers
  - Implement candidate selection from `ProjectMemory`, note refresh rules, line-cap pruning, and foresight prompt assembly inputs
- Worker 4: tests + docs
  - Own new tests under `tests/unit/` and plugin/docs updates
  - Add coverage for CLI behavior, marker lifecycle, recovery, shared-memory pruning, and session-mode boundaries

## Test Plan

- Unit tests for `muscle foresight run` create and remove the temporary foresight section on success and on simulated failure.
- Unit tests for stale cleanup recover from an orphaned `MUSCLE_FORESIGHT` block left behind by a crashed prior run.
- Unit tests for nested task trees keep the foresight section until the last subagent completes.
- Unit tests for `.muscle/MUSCLE_SHORT_TERM.md` enforce the 50-line cap, dedupe, and ordering.
- Unit tests for retrieval fallback verify deterministic behavior when M2.7 is unavailable.
- Plugin command tests verify `/foresight <task>` maps to one-shot run semantics and `/foresight on|off|status` maps to config/state commands.
- Regression tests confirm long-term learning paths and stop-hook review behavior still work unchanged.
- Manual acceptance checks:
  - one-shot foresight enriches a task and leaves no residue
  - session mode only applies to MUSCLE-managed flows
  - stop hooks can read shared short-term memory but do not overwrite it with noisy raw findings

## Assumptions And Defaults

- Root `CLAUDE.md` is the temporary injection target because that is what the user selected, but this remains experimental because it will dirty the worktree during active runs.
- Session mode is limited to MUSCLE-managed commands and subagent flows; it does not magically intercept every arbitrary future Claude Code user message unless the platform later exposes a generic pre-send hook.
- Preflight is read/rank/summarize only; it does not persist long-term memory, auto-run preparatory shell work, or rewrite existing long-term guidance.
- The shared notepad is additive to existing `.muscle/AGENT.md`; `AGENT.md` stays agent-specific and longer-lived, while `MUSCLE_SHORT_TERM.md` is shared, immediate, and aggressively pruned.
- If root `CLAUDE.md` mutation proves too noisy in practice, the fallback path is to keep the same retrieval/runtime design but swap the injection target to a dedicated `.muscle` temp file without changing the shared-memory model.
