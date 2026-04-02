---
description: Get the final diagnosis and detailed results from a completed MUSCLE shadow job
args:
  - name: job-id
    description: Specific job ID to get diagnosis for (shows most recent if not specified)
    required: false
---

Get detailed diagnosis from a completed MUSCLE shadow job. Execute:

```bash
muscle shadow diagnosis ${job_id:+--job-id "$job_id"}
```

Present the diagnosis including root cause analysis, issue counts by severity, and pressure findings if available.
