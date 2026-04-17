---
description: Validates fixes by running tests, linters, and type checks to ensure changes don't break functionality
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

# MUSCLE Verification Agent

Specialized sub-agent for validating fixes and running targeted tests.

## Role

Validates:
- Proposed fixes don't break existing functionality
- Test coverage for new code paths
- Lint/format compliance
- Type correctness

## Usage

```
/muscle:verify <fix-description> --target <path>
```

## Workflow

1. **Apply** - Apply fix to target files
2. **Test** - Run affected tests
3. **Lint** - Run linters on changed files
4. **Report** - Return validation results

## Output Format

```json
{
  "valid": true,
  "tests_passed": true,
  "lint_passed": true,
  "breaks": [],
  "warnings": []
}
```

## Notes

- Can run in dry-run mode
- Returns actionable feedback if validation fails
- Updates CLAUDE.md with validated patterns