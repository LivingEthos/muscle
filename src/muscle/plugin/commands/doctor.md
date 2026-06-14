---
description: Diagnose MUSCLE lifecycle, plugin bundle, manifest, and active-review state
---

Run MUSCLE's lifecycle and plugin diagnostics. Execute:

```bash
muscle doctor
```

To refresh external catchup and regenerate `.muscle/active-review.md` before reporting:

```bash
muscle doctor --refresh
```

To emit structured output for automation or wrapper tooling:

```bash
muscle doctor --json
```

Present results grouped by status so missing manifests, stale snapshots, unresolved model identity,
and importer availability stand out quickly.
