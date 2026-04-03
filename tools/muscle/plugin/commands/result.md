---
description: Get results from the most recent completed shadow job
args:
  - name: job-id
    description: Specific job ID to get results for (shows most recent if not specified)
    required: false
---

Get review results from a completed MUSCLE shadow job. Execute:

```bash
muscle diagnosis ${job_id:+--job-id "$job_id"}
```

For completed jobs, this presents findings organized by severity (CRITICAL, HIGH, MEDIUM) with issue counts and top issues.
