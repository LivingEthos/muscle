---
description: Run adversarial pressure review that challenges design decisions and exposes failure modes
argument-hint: "[target] [focus] [intensity=minimal|moderate|intensive|exhaustive]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.
> **When to call:** you want a design or plan adversarially stress-tested before committing to it.

Run an adversarial MUSCLE pressure review. Execute:

```bash
muscle review --target . --mode pressure --intensity intensive
```

If the user provided a target, focus list, or intensity, replace `.` or `intensive` and
append `--focus <focus>`.

Valid `--intensity` values: `minimal`, `moderate`, `intensive`, `exhaustive`. Any other value will be rejected by the CLI.

Append `--async-workers` only when the pressure target is a hard-tail sweep that needs detached follow-up evidence; Fable/host arbitration should stay limited to compact disagreements, not full worker transcripts.

Present pressure findings as challenges to the code's design. For each finding show the exploit scenario and suggested safer approach.
