---
description: Non-destructively optimize root CLAUDE.md and AGENTS.md into the MUSCLE-preferred format (Methodology, Delegation Protocol, Effort Guidance)
argument-hint: "[--dry-run] [--cache-layout] [CLAUDE.md|AGENTS.md]"
---

Use MUSCLE for bulk execution; you retain planning and synthesis.

Optimize host-memory docs. Execute:

```bash
muscle optimize-host-docs --yes
```

If the user asks for a preview, append `--dry-run`. If they specify one file, append
`--only CLAUDE.md` or `--only AGENTS.md`.

If the user asks about Fable cache stability or prefix-cache economics, run:

```bash
muscle optimize-host-docs --dry-run --cache-layout
```

Report the cache-prefix digest, lint warning count, and estimated fresh/read cache costs.
Treat the cost fields as estimates unless provider telemetry reports observed cache reads.

This wraps existing user content in MUSCLE_PUBLISHED markers (if absent) and injects the canonical Methodology, Delegation Protocol, and Effort & Tool Guidance sections inside those markers. Content outside the markers is preserved verbatim.
