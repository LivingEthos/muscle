---
description: Run adversarial pressure review that challenges design decisions and exposes failure modes
args:
  - name: target
    description: Path to review (defaults to current directory)
    required: false
  - name: focus
    description: "Comma-separated focus areas: design, failure, race, auth, data, rollback, reliability"
    required: false
  - name: intensity
    description: "Review intensity: minimal, moderate, intensive, exhaustive"
    required: false
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Run an adversarial MUSCLE pressure review. Execute:

```bash
muscle review --target "${target:-.}" --mode pressure --intensity "${intensity:-intensive}" ${focus:+--focus "$focus"}
```

Present pressure findings as challenges to the code's design. For each finding show the exploit scenario and suggested safer approach.
