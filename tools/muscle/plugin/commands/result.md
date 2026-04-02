---
description: Get the results from a completed MUSCLE shadow (background) job
args:
  - name: job-id
    description: Specific job ID to get results for (shows most recent if not specified)
    required: false
---

Get results from a completed MUSCLE shadow job. Execute:

```bash
muscle shadow result ${job_id:+--job-id "$job_id"}
```

Present the review findings organized by severity.
