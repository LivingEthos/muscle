# MUSCLE Plugin Lifecycle, Codex, and Operator Hardening

## Summary
- This is the exact replacement content for `docs/plans/muscle-plugin-lifecycle-hardening.md`; do not create a second overlapping plan doc.
- Keep MUSCLE DB-first: `project_memory.db`, `.muscle/packs/`, existing review artifacts, and existing published memory remain authoritative.
- Borrow only the useful ideas from `oh-my-claudecode`: better diagnostics, better lifecycle hooks, better plugin packaging metadata, and better operator visibility.
- Do not borrow OMC’s broader orchestration scope. No `team`, tmux workers, autopilot, wiki, or general-purpose multi-agent runtime changes belong in this plan.
- Replace the old plan’s repo-local `.codex/` workspace-assets idea with an actual Codex plugin bundle inside `tools/muscle/plugin`, because the local Codex plugin examples use `.codex-plugin/plugin.json` plus plugin-root `hooks.json`.

## Public Interfaces
- Add CLI `muscle doctor [--json] [--refresh]`.
- Add CLI `muscle status --refresh`.
- Add hidden CLI `muscle _host-hook --platform <claude-code|codex> --event <session_start|user_prompt_submit|post_write|stop> [--project-path <path>]`.
- Add `codex` to every platform choice and display path that currently accepts `auto|opencode|claude-code`.
- Add Claude plugin command doc `/muscle:doctor`.
- Add Codex plugin manifest at `tools/muscle/plugin/.codex-plugin/plugin.json`.
- Add Claude marketplace manifest at `tools/muscle/plugin/.claude-plugin/marketplace.json`.
- Add generated snapshot file `.muscle/active-review.md`; it is generated only, never hand-edited, never authoritative.

## Locked Decisions
- Do not create repo-root planning, findings, or progress files.
- Do not make `.muscle/active-review.md` a write path for findings, tasks, or decisions.
- Do not uninstall or mutate user-global `~/.codex/`; Codex support is plugin-bundle based, not workspace-asset based.
- Do not redesign OpenCode integration in this pass; preserve current behavior.
- Claude hook expansion is limited to `SessionStart`, `UserPromptSubmit`, and `Stop`.
- Codex hook expansion is limited to plugin-root `PostToolUse` with matcher `Write|Edit`, routed internally as `post_write`.
- `muscle doctor` is report-and-refresh only in this pass; do not add `--fix`.

## Phase 1: Package and Metadata Hardening
- Keep `tools/muscle/plugin` as the single cross-host plugin bundle.
- Add `tools/muscle/plugin/.claude-plugin/marketplace.json` so the existing README install path is backed by committed metadata.
- Add `tools/muscle/plugin/.codex-plugin/plugin.json` modeled on the local minimal Codex plugin fixture. Include `skills: "./skills/"`, Codex `interface` metadata, and new small shared assets under `tools/muscle/plugin/assets/`.
- Add Codex plugin-root `tools/muscle/plugin/hooks.json`; keep existing Claude file at `tools/muscle/plugin/hooks/hooks.json`.
- Reuse the existing `commands/`, `agents/`, and `skills/` trees for both hosts; do not fork separate Codex copies.
- Update `tools/muscle/plugin/.claude-plugin/plugin.json` description to advertise `/muscle:doctor` once the doc exists.
- Add tests that validate both manifests exist, parse, and stay aligned with the actual bundle contents.

## Phase 2: Platform Plumbing
- In `tools/muscle/tui/project_manager.py` and `tools/muscle/cli.py`, add `codex` to platform enums, init options, settings options, config load/store, and status output.
- Change platform auto-detection precedence to: `MUSCLE_FORCE_PLATFORM` first, then `OPENCODE_SESSION`, then `CLAUDE_CODE`, then Codex markers. Treat `CODEX_SHELL`, `CODEX_THREAD_ID`, or `CODEX_INTERNAL_ORIGINATOR_OVERRIDE` starting with `Codex` as Codex markers.
- `muscle init --platform codex` should only persist the platform, initialize `.muscle/`, refresh the active-review snapshot, and print Codex plugin-bundle guidance. It must not create a repo-local `.codex/` tree.
- `muscle uninstall` continues removing `.muscle/` and `.opencode/`; do not add `.codex/` deletion logic.

## Phase 3: Active Review Snapshot
- Add a small read-only generator module, preferably `tools/muscle/active_review.py`, with one main helper `refresh_active_review(project_path: str, reason: str) -> ActiveReviewUpdate`.
- Generate `.muscle/active-review.md` from current config and DB state. Use exact sections: generated header with authoritative-source note, `Current State`, `Latest Review`, `Shadow Jobs`, `Verification`, `External Catchup`, and `Recommended Actions`.
- Keep content bounded and summary-only: counts, IDs, timestamps, one-line summaries, and next commands. Never dump raw transcript bodies, long finding text, or copied markdown memory files.
- Compute a stable digest from semantic content only. Exclude generated timestamp, absolute paths, and other volatile fields so deduplication is meaningful.
- Refresh this snapshot after successful `init`, `enable`, `disable`, platform/settings changes, `optimize import`, review completion, diagnosis retrieval, and `status --refresh`.
- If `project_memory.py` lacks convenient read helpers for latest review, latest verification, or active shadow jobs, add small read-only helper methods there instead of embedding SQL in multiple callers.

## Phase 4: External Catchup Reuse
- Reuse `tools/muscle/optimization/importers.py`; do not build a second transcript store.
- Extend the importer so host integrations can get delta information, not just counts. The simplest contract is a new helper that returns newly inserted external-turn row IDs per provider plus session/turn counts.
- Track sync markers in `automation_state` using stable project-scoped keys: `host.active_review.digest`, `host.emit.<platform>.<event>.digest`, `host.sync.<provider>.last_turn_id`, and `host.catchup.last_summary.digest`.
- Build a catchup summarizer that reads only newly inserted external-turn rows with IDs greater than the last synced marker, produces a short MUSCLE-authored summary, stores its digest in automation state, and feeds only the summary into `.muscle/active-review.md`.
- On Claude `session_start`, import Claude and Codex external sessions for the current project, summarize only new rows, advance markers, then refresh the snapshot.
- On Codex, rely on `status --refresh`, `doctor --refresh`, and `post_write` refreshes until a Codex session-start hook is locally verified.

## Phase 5: Shared Host Runtime
- Add a new runtime module, preferably `tools/muscle/host_runtime.py`, with one entry function `run_host_hook(platform, event, project_path, tool_name=None) -> HostHookResult`.
- `HostHookResult` should contain `message`, `digest`, `changed`, and `ok`; the runtime always fails open and prints nothing on degraded state unless a concise warning is useful.
- `session_start`: run catchup import, refresh snapshot, emit a one-screen MUSCLE state banner only if the per-platform/event digest changed.
- `user_prompt_submit`: read the current snapshot digest and emit only a short “active review / next action” reminder when that digest differs from `host.emit.<platform>.user_prompt_submit.digest`.
- `post_write`: refresh the snapshot after write/edit activity and emit nothing unless the semantic digest changed materially.
- `stop`: preserve current low-severity auto-review behavior for Claude Code, then refresh the snapshot and append next-step guidance derived from current state.
- Add hidden CLI `_host-hook` that only bridges CLI args to `run_host_hook`; plugin hook files must invoke this command rather than importing Python modules directly.

## Phase 6: Host Wiring
- Expand `tools/muscle/plugin/hooks/hooks.json` from Stop-only to `SessionStart`, `UserPromptSubmit`, and `Stop`, all invoking `muscle _host-hook --platform claude-code --event ...`.
- Keep the existing Stop review behavior, but route it through the shared runtime so refresh, dedup, and next-step messaging are centralized.
- Add `tools/muscle/plugin/hooks.json` for Codex with one `PostToolUse` matcher `Write|Edit` that invokes `muscle _host-hook --platform codex --event post_write`.
- Do not add Codex `Stop`, `SessionStart`, or `UserPromptSubmit` hooks in this pass unless a locally installed Codex plugin example or current official docs prove the exact event names and schema during implementation.

## Phase 7: Doctor and Status UX
- Add a new CLI helper module, preferably `tools/muscle/doctor.py`, plus top-level `muscle doctor`.
- `muscle doctor` should report: project initialized/enabled, selected platform, CLI path, API key presence, Claude manifest presence, Claude marketplace manifest presence, Codex manifest presence, Claude/Codex hook file presence, `.muscle/active-review.md` existence and freshness, model identity resolved/unresolved, and recent external importer availability.
- `muscle doctor --refresh` must refresh catchup and active-review before reporting; `--json` should emit structured output for automation.
- Add `/muscle:doctor` doc that runs `muscle doctor`, mentions `--refresh`, and keeps results organized by status.
- Add `--refresh` to `muscle status`; it should call the same refresh helper used by doctor, then render the normal status table plus snapshot freshness and last catchup-summary presence.
- Update `/muscle:setup`, `/muscle:status`, and `/muscle:settings-show` docs so setup mentions doctor, status mentions `--refresh`, and settings-show remains config-only.

## Phase 8: Documentation Cleanup
- Update README plugin/install sections to mention that the bundle now includes both Claude and Codex plugin manifests, but do not invent a Codex installation command unless it is locally verifiable during implementation.
- Update `tools/muscle/code_review/host_memory_templates.py` to remove the stale `muscle install` wording and replace it with host-accurate plugin-activation wording.
- Keep MUSCLE-specific language; do not borrow OMC branding, workflow names, or tmux/team terminology.
- Explicitly document that `.muscle/active-review.md` is generated convenience output and that `project_memory.db` remains authoritative.

## Test Plan
- Unit tests: platform detection for Codex markers, active-review rendering and digest stability, catchup delta summarization, host runtime dedup logic, doctor report generation, and both plugin manifest schemas.
- Integration tests: `muscle init --platform codex`, `muscle settings platform --platform codex`, `muscle status --refresh`, `muscle doctor`, `muscle uninstall --force --keep-config` still leaves `~/.codex` alone, and OpenCode init/uninstall behavior remains unchanged.
- Plugin-doc tests: add `doctor` to expected command docs, CLI command tables, and manifest parity checks; ensure new marketplace manifest is present if tests are extended to check it.
- Hook tests: Claude hook config contains exactly `SessionStart`, `UserPromptSubmit`, and `Stop`; Codex `hooks.json` contains only `PostToolUse` with matcher `Write|Edit`; both route to `_host-hook`.
- Catchup tests: importer remains idempotent, only new external turns are summarized, and raw transcript text never appears in `.muscle/active-review.md`.

## Assumptions
- The merged plan replaces `docs/plans/muscle-plugin-lifecycle-hardening.md` instead of creating a second plan doc.
- The old plan’s `.codex/` workspace-asset requirement is intentionally superseded by a Codex plugin-bundle approach because local Codex plugin examples use `.codex-plugin/plugin.json` and plugin-root `hooks.json`.
- This pass improves plugin lifecycle, packaging, and visibility; it does not broaden MUSCLE into a general multi-agent orchestration framework.
