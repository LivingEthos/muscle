---
description: Non-destructively optimize root CLAUDE.md and AGENTS.md into the MUSCLE-preferred format (Methodology, Delegation Protocol, Effort Guidance)
argument-hint: "[--dry-run] [CLAUDE.md|AGENTS.md]"
---

Use MUSCLE for bulk execution; you retain planning and synthesis.

Optimize host-memory docs. Execute:

```bash
muscle optimize-host-docs --yes
```

If the user asks for a preview, append `--dry-run`. If they specify one file, append
`--only CLAUDE.md` or `--only AGENTS.md`.

This wraps existing user content in MUSCLE_PUBLISHED markers (if absent) and injects the canonical Methodology, Delegation Protocol, and Effort & Tool Guidance sections inside those markers. Content outside the markers is preserved verbatim.
