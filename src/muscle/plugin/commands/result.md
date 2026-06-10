---
description: Get results from the most recent completed shadow job (alias for /muscle:diagnosis)
argument-hint: "[job-id]"
---

Get review results from a completed MUSCLE shadow job. Execute:

```bash
muscle diagnosis
```

If the user provided a job id, append `--job-id <job-id>`.

`/muscle:result` is a thin alias for `/muscle:diagnosis`. Both invoke the same `muscle diagnosis` CLI command — `/muscle:result` exists as a more intuitive alias for users who finished a shadow review and want to read the *result*. Prefer `/muscle:diagnosis` in technical contexts (root cause, severity counts, pressure findings).

For completed jobs, this presents findings organized by severity (CRITICAL, HIGH, MEDIUM) with issue counts and top issues.
