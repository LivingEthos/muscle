---
description: Quick probe of a shadow job's current progress without waiting for completion
args:
  - name: job-id
    description: Job ID to probe (shows most recent if not specified)
    required: false
---

Probe a MUSCLE shadow job's current progress. Execute:

```bash
muscle shadow probe ${job_id:+--job-id "$job_id"}
```

Show current progress, issues found so far, and estimated time remaining.
