---
description: Initialize or enable MUSCLE for the current project
args:
  - name: action
    description: "Action: init, enable, disable, status"
    required: false
---

Configure MUSCLE for the current project.

If action is "init" or no MUSCLE installation exists (no `.muscle/` directory), run:
```bash
muscle init --non-interactive
```

To enable MUSCLE after initialization:
```bash
muscle enable
```

To disable MUSCLE for this project:
```bash
muscle disable
```

To check current status:
```bash
muscle status
```

For hook configuration:
```bash
muscle settings hooks --enable
muscle settings hooks --disable
```
