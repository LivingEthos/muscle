---
description: Report missed MUSCLE opportunities from imported host sessions without writing memory
---

Scan imported host sessions and local MUSCLE state for missed review or verification
opportunities. Execute:

```bash
muscle discover
```

Limit the report window:

```bash
muscle discover --since 14
```

For structured output suitable for automation:

```bash
muscle discover --json
```

The command is read-only and does not edit project memory files.
