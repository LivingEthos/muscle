---
description: MUSCLE single-shot validation (compiler, linter, tests)
agent: build
---

Run a single-shot validation against a file or directory. Runs compiler, linter, and test checks once.

Usage:
/muscle-check --target <path> [--language <lang>] [--format <format>]

Options:
- --target - Path to validate (file or directory, required)
- --language - Programming language (auto-detected if not specified)
- --format - Output format: text, json (default: text)

Examples:
/muscle-check --target ./src
/muscle-check --target ./src --language python --format json
/muscle-check --target ./tests

Returns exit code 0 if all checks pass, non-zero otherwise.
