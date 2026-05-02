---
description: Deep-dive investigation and bug hunting using M2.7 for active problem solving
argument-hint: "[prompt] [target] [intensity]"
---

Throw a lifeline to MUSCLE's M2.7 for deep investigation. Execute:

```bash
muscle lifeline --target . --prompt "$ARGUMENTS" --intensity moderate
```

Use the user's first argument as the prompt. If they also provide a target or intensity,
replace `.` and `moderate` accordingly.

Present findings with confidence levels and suggested fixes.
