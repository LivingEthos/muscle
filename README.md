# MUSCLE - MiniMax Unified Self-Correcting Learning Engine

> "Give your code more muscle"

**Self-learning code review that gets smarter with every task.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Supported Languages: Python, JavaScript, TypeScript, Go, Java, Rust, C++](https://img.shields.io/badge/Languages-Python%20%7C%20JavaScript%20%7C%20TypeScript%20%7C%20Go%20%7C%20Java%20%7C%20Rust%20%7C%20C++-blue.svg)](https://github.com/LivingEthos/muscle)

## Overview

MUSCLE is a self-learning code review companion that:
- Runs post-task verification after Claude Code tasks
- Traces root causes of issues through conversation
- Auto-fixes or proposes fixes based on configurable automation
- Updates CLAUDE.md/AGENT.md/MEMORY.md so Claude NEVER makes same mistake twice
- Evolves its strategies over time when validated effective
- Works locally with optional cloud sync in the future

**Core Philosophy:** M2.7 is cheap enough to run constantly. If it learns your project, it approximates Claude Opus quality at a fraction of the cost.

## Features

- **Post-Task Verification**: Review gate runs after every Claude Code task
- **Root Cause Tracing**: M2.7 traces issues to specific decisions
- **Auto-Fix / Propose**: Configurable per severity level
- **Memory File Updates**: CLAUDE.md, AGENT.md, MEMORY.md management
- **Per-Project KB**: SQLite-based pattern and fix storage
- **Strategy Evolution**: Evolves when validated effective
- **TUI Interface**: Dashboard, reviews, history, settings
- **Claude Code Plugin**: Slash commands, subagents, hooks
- **Multi-Project Support**: Auto-detect + TUI switcher
- **Dynamic Skill Generation**: Creates project-specific skills automatically
- **Dynamic Agent Generation**: Creates specialized sub-agents for complex tasks
- **GitHub Integration**: PRs, comments, issues, status checks
- **Nightly Cron**: Background analysis with morning reports
- **Shadow Mode**: Background review jobs with queue-based processing

## Installation

### Option 1: One-liner install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
```

This installs the `muscle` CLI to `~/.muscle/src` and makes it available on your PATH.

**Environment variables to customize the install:**

| Variable | Default | Description |
|----------|---------|-------------|
| `MUSCLE_INSTALL_DIR` | `~/.muscle/src` | Installation directory |
| `MUSCLE_BRANCH` | `main` | Git branch or tag to install |
| `MUSCLE_SKIP_UV` | `0` | Set to `1` to use pip instead of uv |
| `MUSCLE_NO_INIT` | `0` | Set to `1` to skip running `muscle init` |

**Reinstall or update:**

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
```

The script is idempotent — re-running it updates an existing installation.

### Option 2: Claude Code Plugin

Install MUSCLE as a Claude Code plugin for slash command integration:

```bash
# Add the marketplace
/plugin marketplace add LivingEthos/muscle

# Install the plugin
/plugin install muscle@muscle-marketplace
```

Then use the slash commands in any Claude Code session:

```
/muscle:review     # Standard code review
/muscle:pressure   # Adversarial review
/muscle:rescue     # Deep-dive investigation
/muscle:status     # Check job status
/muscle:result     # Get job results
/muscle:cancel     # Cancel running jobs
/muscle:setup      # Configure review gate
```

> **Note:** The plugin's slash commands shell out to the `muscle` CLI under the hood. Install the CLI (Option 1) first.

### Option 3: Manual install

```bash
# Clone repository
git clone https://github.com/LivingEthos/muscle.git
cd muscle

# Install dependencies
uv sync

# Install as CLI tool
uv pip install -e .
```

## Quick Start

```bash
# Install MUSCLE
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash

# Set your API key
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"

# Initialize MUSCLE for a project
muscle init

# Run a code review
muscle review --target ./src --mode review

# Run with auto-fix
muscle review --target ./src --mode auto-fix

# Start the TUI
muscle tui
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `muscle init` | Initialize MUSCLE for the current project |
| `muscle review` | Review code for issues (review, auto-fix, plan, hybrid, pressure modes) |
| `muscle tui` | Start the Terminal User Interface |
| `muscle probe` | Check status of shadow (background) review jobs |
| `muscle diagnosis` | Get final diagnosis/results from completed shadow jobs |
| `muscle run` | Start a new MUSCLE session |
| `muscle history` | List all MUSCLE sessions |
| `muscle resume` | Resume a failed or incomplete session |
| `muscle abort` | Abort a running session |
| `muscle kb` | Knowledge base management commands |
| `muscle cost` | Cost optimization and cache management |
| `muscle check` | Single-shot validation (no loop) |

## Review Modes

| Mode | Description |
|------|-------------|
| `review` | Standard review, reports issues |
| `auto-fix` | Automatically applies fixes for auto-fixable issues |
| `plan` | Generates handoff plan for manual fixes |
| `hybrid` | Auto-fix safe issues, plan for complex ones |
| `pressure` | Adversarial review that challenges design decisions |

## Claude Code Plugin

MUSCLE provides a Claude Code plugin with slash commands.

### Install from marketplace

```bash
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

### Or load locally for development

```bash
claude --plugin-dir ./tools/muscle/plugin
```

### Available commands

```bash
/muscle:review     # Standard review on changes
/muscle:pressure   # Adversarial review
/muscle:rescue     # Delegate deep-dive investigation
/muscle:status     # Check job status
/muscle:result     # Get job results
/muscle:cancel     # Cancel running jobs
/muscle:setup      # Configure review gate
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER                                         │
└────────────────────────────┬────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    MUSCLE CORE                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │   Review     │  │   Pattern    │  │    Skill     │             │
│  │  Controller │→→│   Detector   │→→│  Generator   │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│         ↓                ↓                ↓                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │   Memory     │  │    Fix      │  │   Agent      │             │
│  │   Manager    │  │   Tracker   │  │  Generator   │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
└────────────────────────────┬────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────────┐
│                     INTEGRATIONS                                      │
│     GitHub │ GitLab │ Jenkins │ MCP │ Claude Code Plugin             │
└─────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
~/.muscle/
├── global_config.yaml       # Global MUSCLE settings
└── global_kb.db            # Optional: cross-project learnings

/path/to/project/
├── .muscle/                 # MUSCLE project directory
│   ├── project.db           # SQLite: patterns, fixes, history
│   ├── config.yaml          # Project config
│   ├── strategy_kb.json     # Evolved review strategies
│   ├── CLAUDE.md           # Project conventions (MUSCLE-managed)
│   ├── AGENT.md             # Agent-specific memory
│   ├── MEMORY.md            # Miscellaneous learnings
│   ├── skills/              # Dynamically generated project skills
│   ├── agents/              # Dynamically generated sub-agents
│   ├── reports/             # Nightly review reports
│   └── logs/                # Review logs
└── .git/
```

## Configuration

### Automation Levels

| Level | Critical/High | Medium/Low | Description |
|-------|---------------|------------|-------------|
| 1: Auto-fix | Auto-fix | Auto-fix if confident | Maximum automation |
| 2: Propose | Propose | Propose | Human in loop |
| 3: Hybrid | Auto-fix | Propose + accept | Balanced |
| 4: Ask | Ask | Ask | Full control |

### Review Gate Behaviors

| Mode | Critical/High | Medium/Low | Fluidity | Accuracy |
|------|--------------|-----------|----------|----------|
| Block+Fix | Auto-fix, then allow | Warn, then allow | High | High |
| Block All | Must address | Must address | Medium | Highest |
| Warn Only | Notify | Notify | Highest | Medium |
| Disabled | No auto | No auto | Highest | User-defined |

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest tests/ -v

# Quality checks (ALL must pass)
uv run mypy tools/muscle/
uv run ruff check tools/muscle/
uv run ruff format --check tools/muscle/
uv run pytest tests/

# Auto-fix issues
uv run ruff check tools/muscle/ --fix
uv run ruff format tools/muscle/
```

## Quality Gates

All code must pass before merging:

| Check | Command | Required |
|-------|---------|----------|
| Types | `uv run mypy tools/muscle/` | Yes |
| Lint | `uv run ruff check tools/muscle/` | Yes |
| Format | `uv run ruff format --check tools/muscle/` | Yes |
| Tests | `uv run pytest tests/` | Yes |

## The Compounding Advantage

```
Review #1 → Review #2 → Review #3 → ... → Review #N
(learns)   (remembers)   (evolves)       (expert)
   ↓          ↓           ↓               ↓
"Auth here"  "Known      "Pressure       "This repo
was missed"  pattern"    works better"   knows no bugs"
```

## Troubleshooting

### API Key Issues

```bash
# Set your API key
export MINIMAX_API_KEY="your-token-plan-api-key"

# For global API endpoint
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"

# For China endpoint
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
```

### Empty or Truncated Responses

MUSCLE handles truncated M2.7 responses with JSON recovery:
- Regex-based extraction for structured findings
- Fallback to partial parsing when needed
- Logs show recovery attempts

### Rate Limiting

MUSCLE implements exponential backoff for retryable errors (429, 5xx, timeouts).

## Examples

### Python Project Review

```bash
muscle review --target ./src --language python --mode review --severity medium
```

### Auto-Fix JavaScript

```bash
muscle review --target ./src --language javascript --mode auto-fix --intensity intensive
```

### Pressure Mode Review

```bash
muscle review --target ./src --mode pressure --focus design,failure,race,auth
```

### Shadow Mode (Background)

```bash
muscle review --target ./src --shadow
muscle probe  # Check status
muscle diagnosis <job-id>  # Get results
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run quality checks: `uv run mypy tools/muscle/ && uv run ruff check tools/muscle/`
5. Submit a PR

## License

MIT License - see LICENSE file for details.

---

*Last updated: 2026-03-31*
