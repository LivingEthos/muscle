---
description: Run MUSCLE self-learning code review on the current project or specified files
argument-hint: "[target] [mode] [severity] [execution]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

> **Effort:** Run fix-application flows at `xhigh` effort. In auto mode, skip the confirmation prompt.

Run a MUSCLE code review. Execute the following command, adding any user-specified options:

```bash
muscle review --target . --mode review --severity low
```

If the user specified target, mode, severity, execution, or additional options like
`--language`, `--format json`, `--shadow`, `--intensity`, `--max-fixes`, `--output`,
`--failsafe`, `--workflow`, or `--focus`, append those flags to the command.

Use `--execution worktree` when the user wants isolated auto-fix or hybrid edits. Leave execution unset to use the project default.

Present the results organized by severity (Critical > High > Medium > Low). For each issue show file, line, title, and suggested fix.
