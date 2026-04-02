---
description: Quick validation check - runs compiler, linter, and tests without full review
args:
  - name: target
    description: Path to check (defaults to current directory)
    required: false
  - name: language
    description: Programming language (auto-detected if not specified)
    required: false
---

Run a quick MUSCLE validation check (compiler + linter + tests). Execute:

```bash
muscle check --target "${target:-.}" ${language:+--language "$language"}
```

Report pass/fail status for each check type. If issues are found, offer to run a full `/muscle:review` for detailed analysis.
