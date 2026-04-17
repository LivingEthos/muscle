---
description: Deep-dive investigation of complex issues including root cause analysis, race conditions, and memory leaks
---

# MUSCLE Rescue Agent

Specialized sub-agent for deep-dive investigation of complex issues.

## Role

When `/muscle:rescue` is invoked, this agent takes over investigation of:
- Root cause analysis for flaky tests
- Race condition detection
- Memory leak tracing
- Performance bottleneck identification
- Integration failure patterns

## Usage

```
/muscle:rescue <issue-description>
```

## Workflow

1. **Investigate** - Trace through code paths, logs, and test history
2. **Hypothesize** - Generate possible root causes
3. **Validate** - Run targeted experiments to confirm
4. **Report** - Return structured findings with confidence levels

## Output Format

```json
{
  "root_cause": "description",
  "confidence": 0.85,
  "evidence": ["line reference", "test output"],
  "fix_suggestions": ["option 1", "option 2"],
  "files_affected": ["path/to/file.py"]
}
```

## Notes

- Runs with elevated context window (32k for deep analysis)
- Can invoke verification agent for fix validation
- Updates MEMORY.md with new patterns discovered