---
description: Throw a lifeline to MUSCLE's M2.7 model for active investigation, bug-hunting, or exploratory analysis
argument-hint: "[prompt] [target] [intensity=minimal|moderate|intensive|exhaustive]"
---

Throw a lifeline to MUSCLE's M2.7 for deep investigation. Execute:

```bash
muscle lifeline --target . --prompt "$ARGUMENTS" --intensity moderate
```

Use the user's first argument as the prompt. If they also provide a target or intensity,
replace `.` and `moderate` accordingly.

Valid `--intensity` values: `minimal`, `moderate`, `intensive`, `exhaustive`. Any other value will be rejected by the CLI.

`/muscle:lifeline` is the canonical exploratory entry point. Prefer this when the user wants MUSCLE to *poke around* a problem space, propose hypotheses, or surface unknowns. For a directed root-cause investigation with the rescue subagent persona, use `/muscle:rescue` instead — both wrap `muscle lifeline`, but `/muscle:rescue` is wired to the dedicated rescue subagent prompt.

Present findings with confidence levels and suggested fixes.
