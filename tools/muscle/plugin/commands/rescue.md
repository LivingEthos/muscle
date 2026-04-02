# MUSCLE Rescue

Delegate a task or investigation to MUSCLE's M2.7 model for deeper analysis.

## Usage

```
/muscle:rescue [--target <path>] [--prompt <task>] [--intensity <level>] [--model <model>]
```

## Options

- `--target` - Path or file to investigate (default: current directory)
- `--prompt` - Task description for MUSCLE to investigate
- `--intensity` - Investigation intensity: `minimal`, `moderate`, `intensive`, `exhaustive` (default: `moderate`)
- `--model` - Model to use for investigation (optional, defaults to M2.7)

## Examples

```
/muscle:rescue investigate why the auth is failing
/muscle:rescue --target ./src fix the memory leak
/muscle:rescue --intensity intensive debug the flaky test
/muscle:rescue --model claude-opus investigate race condition
```

## Intensity Levels

- **minimal** - Quick scan, surface-level analysis
- **moderate** - Thorough investigation with multiple hypotheses
- **intensive** - Deep dive with code tracing and extensive testing
- **exhaustive** - Comprehensive analysis including edge cases, performance, and security

## What It Does

Rescue hands off a task to MUSCLE's M2.7 model for focused investigation. Unlike review which analyzes existing code, rescue can actively try to fix problems, investigate bugs, or explore solutions.

Use when:
- Claude Code is stuck on a problem
- You need a deeper investigation than review provides
- You want M2.7 to take a focused pass at solving something
- Root cause analysis for flaky tests, race conditions, or memory leaks

## Background Jobs

Use `/muscle:status` to check progress and `/muscle:result` to get results.

See also: `/muscle:status`, `/muscle:result`, `/muscle:lifeline` for deeper investigation
