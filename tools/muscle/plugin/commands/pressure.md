---
description: Run adversarial pressure review that challenges design decisions and exposes failure modes
argument-hint: "[target] [focus] [intensity]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Run an adversarial MUSCLE pressure review. Execute:

```bash
muscle review --target . --mode pressure --intensity intensive
```

If the user provided a target, focus list, or intensity, replace `.` or `intensive` and
append `--focus <focus>`.

Present pressure findings as challenges to the code's design. For each finding show the exploit scenario and suggested safer approach.
