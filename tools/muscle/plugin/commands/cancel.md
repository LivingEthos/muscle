---
description: Cancel a running or pending MUSCLE shadow (background) job
args:
  - name: job-id
    description: Job ID to cancel
    required: true
---

Cancel a running or pending MUSCLE shadow job.

Note: There is currently **no cancel command** in MUSCLE. To stop a running shadow job, you can:

- Kill the process running the shadow job directly
- Use `muscle probe` to check the job status

Background shadow jobs can also be monitored with `muscle probe` and results retrieved with `muscle diagnosis`.
