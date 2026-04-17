---
description: Classify a task and decide where it should run (M2.7 vs host model)
args:
  - name: task
    description: Task description to classify
    required: true
  - name: scope
    description: Optional path scope hint for classification
    required: false
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Classify a task and decide whether MUSCLE's M2.7 agents should handle it directly or escalate to the host model. Execute:

```bash
muscle route --task "<task>" [--scope <path>] [--json]
```

The classifier returns:
- **tier**: `mechanical` (pattern/boilerplate/test), `reasoning` (debug/trace/refactor), or `architectural` (design/decision/multi-module)
- **recommended**: `m27` (direct M2.7), `m27_with_verify` (M2.7 + verification loop), or `escalate_to_host` (host model should plan directly)
- **confidence**: 0.0-1.0
- **rationale**: one-sentence explanation

Rules enforced by the router:
- `architectural` tasks ALWAYS escalate to host
- Tasks with confidence < 0.5 ALWAYS escalate to host
- `mechanical` tasks with test targets get `m27_with_verify`
