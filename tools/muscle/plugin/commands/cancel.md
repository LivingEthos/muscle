---
description: Cancel a running or pending MUSCLE shadow (background) job
args:
  - name: job-id
    description: Job ID to cancel
    required: true
---

Cancel a running MUSCLE shadow job. Execute:

```bash
muscle shadow cancel --job-id "${job_id}"
```

Confirm the cancellation and report final status.
