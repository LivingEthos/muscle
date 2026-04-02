# MUSCLE Lifeline

Throw a lifeline to M2.7 for deep-dive investigation, bug hunting, or problem solving. Unlike review which focuses on finding issues, lifeline is for active problem solving.

## Usage

```
/muscle:lifeline [--target <path>] [--prompt <task>] [--intensity <level>]
```

## Options

- `--target` - Path or file to investigate (default: current directory)
- `--prompt` - Task description for investigation (required)
- `--intensity` - Investigation intensity: `minimal`, `moderate`, `intensive`, `exhaustive` (default: `moderate`)

## Examples

```
/muscle:lifeline investigate why auth is failing
/muscle:lifeline --target ./src fix the memory leak
/muscle:lifeline --target ./tests --prompt "debug flaky integration test" --intensity intensive
```

## Use Cases

- Stuck on a problem and need deeper analysis
- Investigating root cause of flaky tests
- Debugging race conditions or memory leaks
- Performance bottleneck identification
- When `/muscle:rescue` needs more focused investigation
