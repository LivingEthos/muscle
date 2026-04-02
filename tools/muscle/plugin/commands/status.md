---
description: Check status of running or completed MUSCLE shadow (background) jobs
args:
  - name: job-id
    description: Specific job ID to check (shows all if not specified)
    required: false
---

Check the status of MUSCLE shadow jobs. Execute:

```bash
muscle shadow status ${job_id:+--job-id "$job_id"}
```

Show job status (pending, running, completed, failed) with timestamps.
