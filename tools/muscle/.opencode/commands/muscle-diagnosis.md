---
description: Get MUSCLE shadow job diagnosis/results
agent: build
---

Get the final diagnosis/results from a completed MUSCLE shadow job.

Usage:
/muscle-diagnosis [--job-id <id>]

Options:
- --job-id - Specific job ID to get diagnosis (optional, shows most recent if not specified)

Examples:
/muscle-diagnosis
/muscle-diagnosis --job-id abc12345

Shows the completed job's issues found, pressure findings, or other results.
