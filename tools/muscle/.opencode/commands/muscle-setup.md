---
description: Configure MUSCLE settings or run setup wizard
agent: build
---

Configure MUSCLE settings or run the interactive setup wizard.

Usage:
/muscle-setup [--enable-auto-review] [--disable-auto-review] [--api-key <key>] [--platform <opencode|claude-code|auto>]

Options:
- --enable-auto-review - Enable automatic review after tasks
- --disable-auto-review - Disable automatic review
- --api-key - Set your MINIMAX/M2.7 API key
- --platform - Force platform detection: opencode, claude-code, or auto (default: auto)
- --configure - Run interactive configuration wizard

Examples:
/muscle-setup --configure
/muscle-setup --enable-auto-review
/muscle-setup --disable-auto-review
/muscle-setup --api-key sk-xxxxx

Run without options to launch the interactive setup wizard.
