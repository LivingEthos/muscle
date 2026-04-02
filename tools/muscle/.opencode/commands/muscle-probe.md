---
description: Check MUSCLE shadow job status
agent: build
---

Check the status of MUSCLE shadow (background) review jobs.

Usage:
/muscle-probe [--job-id <id>]

Options:
- --job-id - Specific job ID to check (optional, shows all if not specified)

Examples:
/muscle-probe
/muscle-probe --job-id abc12345

Shows all active and recent jobs without --job-id, or detailed status of a specific job.
