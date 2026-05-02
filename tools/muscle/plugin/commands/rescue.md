---
description: Delegate a focused root-cause investigation to MUSCLE's M2.7 rescue subagent — race conditions, memory leaks, hard-to-reproduce bugs
argument-hint: "[prompt] [target] [intensity=minimal|moderate|intensive|exhaustive]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Hand off a directed root-cause investigation to MUSCLE's M2.7 rescue subagent. Execute:

```bash
muscle lifeline --target . --prompt "$ARGUMENTS" --intensity moderate
```

Use the user's first argument as the prompt. If they also provide a target or intensity,
replace `.` and `moderate` accordingly.

Valid `--intensity` values: `minimal`, `moderate`, `intensive`, `exhaustive`. Any other value will be rejected by the CLI.

`/muscle:rescue` and `/muscle:lifeline` both wrap `muscle lifeline`. Use `/muscle:rescue` when the user has a specific failure they want diagnosed (race condition, memory leak, intermittent test, regression after a known change). Use `/muscle:lifeline` for open-ended exploratory investigation. The corresponding rescue subagent at `agents/rescue_agent.md` returns structured root-cause JSON with `confidence`, `evidence`, and `fix_suggestions` fields.

Present the findings with confidence levels and suggested fixes. Offer to apply suggested fixes or run a follow-up review.
