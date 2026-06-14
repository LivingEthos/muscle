---
description: Configure MUSCLE review execution mode
argument-hint: "[local|worktree]"
---

Show or update the review execution mode. Execute:

```bash
muscle settings review
```

If the user provided an execution mode, append `--execution local` or
`--execution worktree`.
If the user wants hard-tail async review workers enabled or disabled by default, append
`--async-workers` or `--no-async-workers`. If they provide a worker cap, append
`--async-worker-limit <N>`.

Use `local` for in-place fixes or `worktree` to isolate auto-fix and hybrid edits in a temporary git worktree before applying back verified changes.
