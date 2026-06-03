# Quickstart

| Field | Value |
|---|---|
| Audience | First-time users |
| Status | Minimal successful workflow |
| Source of truth | [`README.md`](../../README.md), [`tools/muscle/plugin/commands/review.md`](../../tools/muscle/plugin/commands/review.md), [`tools/muscle/cli.py`](../../tools/muscle/cli.py) |
| Primary commands | `muscle init`, `muscle review`, `muscle check`, `muscle doctor` |

This path gets a project from zero to a first review.

## 1. Install And Configure

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"
```

## 2. Initialize The Target Project

```bash
cd /path/to/your/project
muscle init --non-interactive --related-mode suggest --pack-mode suggest
muscle doctor
```

## 3. Run A Small First Review

Prefer a small target first:

```bash
muscle review --target ./src --mode review --severity low
```

If the project has no `src/` directory, target one file or another focused
directory:

```bash
muscle review --target ./app --mode review --severity low
```

## 4. Validate Without Semantic Review

```bash
muscle check --target .
```

Use `check` when you want compiler, linter, and test evidence without the full
review loop.

## 5. Use Plugin Slash Commands

In Claude Code, install the marketplace and plugin:

```text
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

Then run:

```text
/muscle:doctor
/muscle:review
/muscle:pressure
```

## What Success Looks Like

- `muscle doctor` reports initialized project state and plugin files present.
- `muscle review` completes with a review summary or JSON payload.
- `.muscle/project_memory.db` exists.
- If findings are learned, bounded memory files may update under `.muscle/`.

