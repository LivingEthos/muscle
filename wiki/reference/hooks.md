# Hooks

| Field | Value |
|---|---|
| Audience | Plugin maintainers and operators debugging host integration |
| Status | Current hook contract |
| Source of truth | [`tools/muscle/plugin/hooks/hooks.json`](../../tools/muscle/plugin/hooks/hooks.json), [`tools/muscle/plugin/hooks.json`](../../tools/muscle/plugin/hooks.json), [`tools/muscle/host_runtime.py`](../../tools/muscle/host_runtime.py), [`tests/unit/test_plugin_hooks.py`](../../tests/unit/test_plugin_hooks.py) |

Hooks route host lifecycle events into `muscle _host-hook`. The runtime fails
open: degraded hook behavior should not block the host application.

## Claude Hooks

| Event | Command | Timeout |
|---|---|---|
| `SessionStart` | `muscle _host-hook --platform claude-code --event session_start || true` | 30 |
| `UserPromptSubmit` | `muscle _host-hook --platform claude-code --event user_prompt_submit || true` | 15 |
| `Stop` | `muscle _host-hook --platform claude-code --event stop || true` | 150 |

Runtime behavior:

- `session_start`: imports available host session deltas, refreshes active-review
  state, and emits a compact banner only when the semantic digest changed.
- `user_prompt_submit`: refreshes active-review state and emits a short reminder
  only when the digest changed.
- `stop`: preserves low-severity Claude stop-review behavior when API access is
  available, then refreshes active-review state.

## Codex Hook

| Event | Matcher | Command |
|---|---|---|
| `PostToolUse` | `Write|Edit` | `muscle _host-hook --platform codex --event post_write || true` |

Runtime behavior:

- `post_write`: refreshes `.muscle/active-review.md` after write/edit activity
  and emits a message only when the semantic digest changed materially.

## State And Deduplication

Hook emission digests are stored through `ProjectMemory` automation state keys.
This keeps host reminders short and avoids repeating the same state banner.

## Testing

`tests/unit/test_plugin_hooks.py` enforces the expected event sets and command
routes. Update that test when hook behavior changes.

