---
description: Show current MUSCLE settings and configuration
agent: build
---

Show current MUSCLE settings and configuration.

Usage:
/muscle-settings-show

Examples:
/muscle-settings-show

Shows:
- Project name and path
- Platform (opencode, claude-code, auto)
- API key source (env, opencode, ask, manual)
- Hooks enabled/disabled
- CLI path
- Review gate mode (block+fix, block-all, warn, disabled)
- Automation level (auto-fix, propose, hybrid, ask)

Also shows environment status (MINIMAX_API_KEY set/unset).
