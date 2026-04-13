---
description: Configure MUSCLE review execution mode
args:
  - name: execution
    description: "Execution mode: local or worktree"
    required: false
---

Show or update the review execution mode. Execute:

```bash
muscle settings review ${execution:+--execution "$execution"}
```

Use `local` for in-place fixes or `worktree` to isolate auto-fix and hybrid edits in a temporary git worktree before applying back verified changes.
