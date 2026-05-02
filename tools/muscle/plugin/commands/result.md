---
description: Get results from the most recent completed shadow job
argument-hint: "[job-id]"
---

Get review results from a completed MUSCLE shadow job. Execute:

```bash
muscle diagnosis
```

If the user provided a job id, append `--job-id <job-id>`.

For completed jobs, this presents findings organized by severity (CRITICAL, HIGH, MEDIUM) with issue counts and top issues.
