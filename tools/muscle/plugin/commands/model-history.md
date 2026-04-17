---
description: Show recent resolved model identity history for the current project
args: []
---

Inspect recent model identity resolution events for this project.
This is useful when provider labels are ambiguous, when MUSCLE upgraded an
identity from trusted provider evidence, or when you want to confirm that a
manual override is active.

```bash
muscle model history
```

For the current effective state instead of recent history:

```bash
muscle model status
```
