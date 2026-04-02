---
description: Check MUSCLE shadow job status
agent: build
---

Check the status of MUSCLE shadow (background) review jobs.

Usage:
/muscle-status [--job-id <id>]

Options:
- --job-id - Specific job ID to check (optional, shows all if not specified)

Examples:
/muscle-status
/muscle-status --job-id abc12345

Shows all active and recent jobs without --job-id, or detailed status of a specific job.
