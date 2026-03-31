# MUSCLE Rescue

Delegate a task or investigation to MUSCLE's M2.7 model for deeper analysis.

## Usage

```
/muscle:rescue [--target <path>] [--prompt <task>]
```

## Options

- `--target` - Path or file to investigate (default: current directory)
- `--prompt` - Task description for MUSCLE to investigate
- `--background` - Run in background

## Examples

```
/muscle:rescue investigate why the auth is failing
/muscle:rescue --target ./src fix the memory leak
/muscle:rescue --background find security vulnerabilities
```

## What It Does

Rescue hands off a task to MUSCLE's M2.7 model for focused investigation. Unlike review which analyzes existing code, rescue can actively try to fix problems, investigate bugs, or explore solutions.

Use when:
- Claude Code is stuck on a problem
- You need a deeper investigation than review provides
- You want M2.7 to take a focused pass at solving something

## Background Jobs

Use `/muscle:status` to check progress and `/muscle:result` to get results.

See also: `/muscle:status`, `/muscle:result`
