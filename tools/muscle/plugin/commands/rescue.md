---
description: Delegate a deep investigation to MUSCLE's M2.7 model for root cause analysis and problem solving
argument-hint: "[prompt] [target] [intensity]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Hand off an investigation to MUSCLE's M2.7 model. Execute:

```bash
muscle lifeline --target . --prompt "$ARGUMENTS" --intensity moderate
```

Use the user's first argument as the prompt. If they also provide a target or intensity,
replace `.` and `moderate` accordingly.

Present the findings with confidence levels and suggested fixes. Offer to apply suggested fixes or run a follow-up review.
