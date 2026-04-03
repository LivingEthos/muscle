---
description: Get the final diagnosis and detailed results from a completed shadow job
args:
  - name: job-id
    description: Specific job ID to get diagnosis for (shows most recent if not specified)
    required: false
---

Get detailed diagnosis from a completed MUSCLE shadow job. Execute:

```bash
muscle diagnosis ${job_id:+--job-id "$job_id"}
```

Presents root cause analysis, issue counts by severity (CRITICAL, HIGH, MEDIUM), and pressure findings if available. Use `muscle probe` to check job status before results are ready.
