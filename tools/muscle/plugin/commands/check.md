---
description: Quick validation check - runs compiler, linter, and tests without full review
argument-hint: "[target] [language]"
---

Run a quick MUSCLE validation check (compiler + linter + tests). Execute:

```bash
muscle check --target .
```

If the user provided a target, replace `.` with that path. If they provided a language,
append `--language <language>`.

Report pass/fail status for each check type. If issues are found, offer to run a full `/muscle:review` for detailed analysis.
