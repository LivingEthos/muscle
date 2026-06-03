# Configuration

| Field | Value |
|---|---|
| Audience | Users and operators configuring projects |
| Status | Current configuration map |
| Source of truth | [`tools/muscle/tui/project_manager.py`](../../tools/muscle/tui/project_manager.py), [`tools/muscle/cli.py`](../../tools/muscle/cli.py), [`README.md`](../../README.md) |

## Environment Variables

| Variable | Purpose |
|---|---|
| `MINIMAX_API_KEY` | Preferred MUSCLE API key environment variable. |
| `ANTHROPIC_API_KEY` | Alternate API key variable accepted by review/lifeline paths. |
| `ANTHROPIC_BASE_URL` | Anthropic-compatible MiniMax endpoint. |
| `MUSCLE_FORCE_PLATFORM` | Platform auto-detection override. |
| `CLAUDE_CONFIG_DIR` | Optional Claude config directory for imported session discovery. |

Global endpoint:

```bash
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"
```

China endpoint:

```bash
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
```

## Project Config

`muscle init` writes `.muscle/config.yaml`. Current implementation preserves
JSON-compatible content in that file for compatibility across readers/writers.

Common settings:

| Setting | Meaning |
|---|---|
| `platform` | `auto`, `opencode`, `claude-code`, or `codex`. |
| `api_key_source` | Where MUSCLE should expect API credentials. |
| `hooks_enabled` | Whether review hooks are enabled for the project. |
| `review_gate` | Review gate behavior such as warn or block modes. |
| `review_execution` | `local` or isolated `worktree`. |
| `related_project_mode` | Related-project overlay policy. |
| `model_pack_mode` | Model-pack overlay policy. |
| `canonical_model_key` | Resolved or manually selected model key. |

## Settings Commands

```bash
muscle settings show
muscle settings api-key
muscle settings hooks --enable
muscle settings hooks --gate warn
muscle settings review --execution worktree
muscle settings platform --platform codex
muscle settings model --related-mode suggest --pack-mode suggest
muscle settings reset
```

## API Key Safety

Diagnostics should report API key state as present or missing. They should not
print secret values.

