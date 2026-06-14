---
description: Delegate a focused root-cause investigation to MUSCLE's M3 rescue subagent — race conditions, memory leaks, hard-to-reproduce bugs
argument-hint: "[prompt] [target] [intensity=minimal|moderate|intensive|exhaustive]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.
> **When to call:** a single failure needs a deep root-cause dive (race condition, memory leak, flaky test) — delegate here rather than spelunking inline.

Hand off a directed root-cause investigation to MUSCLE's M3 rescue subagent. Execute:

```bash
muscle lifeline --target . --prompt "$ARGUMENTS" --intensity moderate
```

Use the user's first argument as the prompt. If they also provide a target or intensity,
replace `.` and `moderate` accordingly.

Valid `--intensity` values: `minimal`, `moderate`, `intensive`, `exhaustive`. Any other value will be rejected by the CLI.

`/muscle:rescue` and `/muscle:lifeline` both wrap `muscle lifeline`. Use `/muscle:rescue` when the user has a specific failure they want diagnosed (race condition, memory leak, intermittent test, regression after a known change). Use `/muscle:lifeline` for open-ended exploratory investigation. The corresponding rescue subagent at `agents/rescue_agent.md` returns structured root-cause JSON with `confidence`, `evidence`, and `fix_suggestions` fields.

Do not use review async workers as a substitute for rescue. Async workers belong to `muscle review --async-workers` and only collect detached hard-tail review evidence after the planner has a focused review target.

Present the findings with confidence levels and suggested fixes. Offer to apply suggested fixes or run a follow-up review.
