---
description: Check the status of shadow (background) review jobs
args:
  - name: job-id
    description: Specific job ID to check (shows all recent jobs if not specified)
    required: false
---

Check the status of MUSCLE shadow (background) review jobs. Execute:

```bash
muscle probe ${job_id:+--job-id "$job_id"}
```

Without --job-id, shows all active and recent shadow jobs. With --job-id, shows detailed status of that specific job including status, target, mode, intensity, and timestamps.
