---
description: Delegate a deep investigation to MUSCLE's M2.7 model for root cause analysis and problem solving
args:
  - name: prompt
    description: Task description for MUSCLE to investigate
    required: true
  - name: target
    description: Path or file to investigate
    required: false
  - name: intensity
    description: "Investigation intensity: minimal, moderate, intensive, exhaustive"
    required: false
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Hand off an investigation to MUSCLE's M2.7 model. Execute:

```bash
muscle lifeline --target "${target:-.}" --prompt "${prompt}" --intensity "${intensity:-moderate}"
```

Present the findings with confidence levels and suggested fixes. Offer to apply suggested fixes or run a follow-up review.
