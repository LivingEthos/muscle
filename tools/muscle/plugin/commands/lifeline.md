---
description: Deep-dive investigation and bug hunting using M2.7 for active problem solving
args:
  - name: prompt
    description: Task description for investigation
    required: true
  - name: target
    description: Path or file to investigate
    required: false
  - name: intensity
    description: "Investigation intensity: minimal, moderate, intensive, exhaustive"
    required: false
---

Throw a lifeline to MUSCLE's M2.7 for deep investigation. Execute:

```bash
muscle lifeline --target "${target:-.}" --prompt "${prompt}" --intensity "${intensity:-moderate}"
```

Present findings with confidence levels and suggested fixes.
