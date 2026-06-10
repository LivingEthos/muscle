---
description: Check the status of shadow (background) review jobs
argument-hint: "[job-id]"
---

Check the status of MUSCLE shadow (background) review jobs. Execute:

```bash
muscle probe
```

If the user provided a job id, append `--job-id <job-id>`.

Without --job-id, shows all active and recent shadow jobs. With --job-id, shows detailed status of that specific job including status, target, mode, intensity, and timestamps.
