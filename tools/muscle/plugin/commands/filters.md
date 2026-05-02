---
description: Verify, trust, or untrust declarative command-output filters
---

Verify built-in and trusted project-local output filters. Execute:

```bash
muscle filters verify
```

Require every filter to include inline tests:

```bash
muscle filters verify --require-all
```

Trust the current project-local `.muscle/filters.yaml` content by digest:

```bash
muscle filters trust
```

Remove project-local filter trust:

```bash
muscle filters untrust
```

Use project filters only after reviewing their inline tests and guard behavior.
