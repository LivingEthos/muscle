---
description: Initialize or configure MUSCLE for the current project
args:
  - name: action
    description: "Action: init, enable-auto-review, disable-auto-review, list"
    required: false
---

Configure MUSCLE for the current project.

If action is "init" or no MUSCLE installation exists (no `.muscle/` directory), run:
```bash
muscle init --non-interactive
```

If action is "enable-auto-review":
```bash
muscle settings platform --hooks
```

If action is "disable-auto-review":
```bash
muscle settings platform --no-hooks
```

If action is "list" or no action specified:
```bash
muscle settings show
```
