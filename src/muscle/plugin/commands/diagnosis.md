---
description: Get the final diagnosis and detailed results from a completed shadow job
argument-hint: "[job-id]"
---

Get detailed diagnosis from a completed MUSCLE shadow job. Execute:

```bash
muscle diagnosis
```

If the user provided a job id, append `--job-id <job-id>`.

Presents root cause analysis, issue counts by severity (CRITICAL, HIGH, MEDIUM), and pressure findings if available. Use `muscle probe` to check job status before results are ready.
