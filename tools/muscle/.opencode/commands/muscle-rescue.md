---
description: Deep-dive investigation and rescue by M2.7
agent: build
---

Delegate a task or investigation to MUSCLE's M2.7 model for deeper analysis.

Usage:
/muscle-rescue --prompt <task> [--target <path>] [--intensity <level>] [--model <model>]

Options:
- --prompt - Task description for investigation (required)
- --target - Path or file to investigate (default: current directory)
- --intensity - Investigation intensity: minimal, moderate, intensive, exhaustive (default: moderate)
- --model - Model to use for investigation (optional, defaults to M2.7)

Examples:
/muscle-rescue --prompt "investigate why auth is failing"
/muscle-rescue --prompt "fix the memory leak" --target ./src
/muscle-rescue --prompt "debug flaky test" --intensity intensive

Intensity Levels:
- minimal - Quick scan, surface-level analysis
- moderate - Thorough investigation with multiple hypotheses
- intensive - Deep dive with code tracing and extensive testing
- exhaustive - Comprehensive analysis including edge cases, performance, and security

Rescue hands off a task to MUSCLE's M2.7 model for focused investigation. Unlike review which analyzes existing code, rescue can actively try to fix problems, investigate bugs, or explore solutions.

Use when:
- Stuck on a problem
- Need a deeper investigation than review provides
- Root cause analysis for flaky tests, race conditions, or memory leaks

Use /muscle-status to check progress and /muscle-result to get results.
