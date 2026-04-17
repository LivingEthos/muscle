---
description: Run MUSCLE self-learning code review on the current project or specified files
args:
  - name: target
    description: Path to review (defaults to current directory)
    required: false
  - name: mode
    description: "Review mode: review, pressure, auto-fix, plan, hybrid"
    required: false
  - name: severity
    description: "Minimum severity: critical, high, medium, low"
    required: false
  - name: execution
    description: "Execution mode for fix-capable reviews: local or worktree"
    required: false
---

Run a MUSCLE code review. Execute the following command, adding any user-specified options:

```bash
muscle review --target "${target:-.}" --mode "${mode:-review}" --severity "${severity:-low}" ${execution:+--execution "$execution"}
```

If the user specified additional options like `--language`, `--format json`, `--shadow`, `--intensity`, `--max-fixes`, `--output`, `--failsafe`, `--workflow`, or `--focus`, append them to the command.

Use `--execution worktree` when the user wants isolated auto-fix or hybrid edits. Leave execution unset to use the project default.

Present the results organized by severity (Critical > High > Medium > Low). For each issue show file, line, title, and suggested fix.
