---
description: Cancel a running MUSCLE shadow job
agent: build
---

Cancel a running MUSCLE shadow (background) job.

Usage:
/muscle-cancel [--job-id <id>]

Options:
- --job-id - Job ID to cancel (required)

Examples:
/muscle-cancel --job-id abc12345

Sends abort signal to the running job.
