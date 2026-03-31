# MUSCLE Pressure Review

Run an adversarial review that challenges design decisions, assumptions, and failure modes.

## Usage

```
/muscle:pressure [--target <path>] [--focus <areas>] [--intensity <level>]
```

## Options

- `--target` - Path to review (default: current directory)
- `--focus` - Focus areas: `design`, `failure`, `race`, `auth`, `data`, `rollback`, `reliability` (comma-separated)
- `--intensity` - Review intensity: `minimal`, `moderate`, `intensive`, `exhaustive` (default: `moderate`)

## Examples

```
/muscle:pressure
/muscle:pressure --focus design,failure,race
/muscle:pressure --intensity exhaustive
```

## Focus Areas

- **design** - Challenge design trade-offs and alternative approaches
- **failure** - Identify failure modes and error handling gaps
- **race** - Find race conditions and concurrency issues
- **auth** - Expose authentication and authorization flaws
- **data** - Detect data loss and corruption risks
- **rollback** - Question rollback and recovery concerns
- **reliability** - Assess reliability and error resilience

## What Makes Pressure Different

Pressure mode doesn't just find bugs - it questions the entire approach. It thinks like an attacker or someone who wants to break the code. Useful before shipping critical changes.

See also: `/muscle:review` for standard review.
