# Installation

| Field | Value |
|---|---|
| Audience | New MUSCLE users and operators |
| Status | User-facing install guide |
| Source of truth | [`README.md`](../../README.md), [`install.sh`](../../install.sh), [`pyproject.toml`](../../pyproject.toml) |

## Requirements

- Python 3.10 or newer.
- Git.
- A MiniMax token-plan API key for MUSCLE model calls.
- Claude Code only if you want Claude slash commands.

Claude Code can host the plugin UI, but MUSCLE still needs its own model API
key for review, pressure review, and lifeline calls.

## Install The CLI

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
```

The installer is expected to clone MUSCLE under `~/.muscle/src`, install the
`muscle` CLI, and print plugin setup guidance.

For local development from this checkout:

```bash
uv sync --extra dev
uv run muscle --help
```

## Configure API Access

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

MUSCLE should report API key presence, not the secret value.

## Initialize A Project

From the target project root:

```bash
muscle init --non-interactive --related-mode suggest --pack-mode suggest
muscle status
muscle doctor
```

This creates `.muscle/` project state and keeps optional overlays in suggest
mode by default.

## Development Validation

For a local checkout:

```bash
uv sync --extra dev
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
uv run pytest tests/ -v
```

