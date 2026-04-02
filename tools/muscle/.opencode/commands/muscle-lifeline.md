---
description: Deep-dive M2.7 investigation and problem solving
agent: build
---

Throw a lifeline to M2.7 for deep-dive investigation, bug hunting, or problem solving.

Usage:
/muscle-lifeline --prompt <task> [--target <path>] [--intensity <level>]

Options:
- --prompt - Task description for investigation (required)
- --target - Path or file to investigate (default: current directory)
- --intensity - Investigation intensity: minimal, moderate, intensive, exhaustive (default: moderate)

Examples:
/muscle-lifeline --prompt "investigate why auth is failing"
/muscle-lifeline --prompt "fix the memory leak" --target ./src
/muscle-lifeline --prompt "debug flaky test" --intensity intensive

Unlike review which finds issues, lifeline actively solves problems:
- Root cause analysis for flaky tests
- Race condition detection
- Memory leak tracing
- Performance bottleneck identification
