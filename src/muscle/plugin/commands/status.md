---
description: Show MUSCLE status including recent long evaluation reports
---

Show MUSCLE status. Execute:

```bash
muscle status
```

Displays whether MUSCLE is enabled and the current project configuration.

To refresh external catchup and regenerate `.muscle/active-review.md` before reading status:

```bash
muscle status --refresh
```

To diagnose manifests, hooks, and snapshot freshness in more detail:

```bash
muscle doctor --refresh
```

To see recent long evaluation reports:

```bash
muscle long-eval reports
```

To compare the legacy reviewer against workflow-driven review strategies:

```bash
muscle long-eval benchmark
```
