---
description: Non-destructively optimize root CLAUDE.md and AGENTS.md into the MUSCLE-preferred format (Methodology, Delegation Protocol, Effort Guidance)
args:
  - name: only
    description: "Restrict to a single target file: CLAUDE.md or AGENTS.md"
    required: false
  - name: dry_run
    description: "Preview changes as a unified diff without writing"
    required: false
---

Use MUSCLE for bulk execution; you retain planning and synthesis.

Optimize host-memory docs. Execute:

```bash
muscle optimize-host-docs ${dry_run:+--dry-run} ${only:+--only "$only"} --yes
```

This wraps existing user content in MUSCLE_PUBLISHED markers (if absent) and injects the canonical Methodology, Delegation Protocol, and Effort & Tool Guidance sections inside those markers. Content outside the markers is preserved verbatim.
