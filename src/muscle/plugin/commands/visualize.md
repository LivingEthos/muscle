---
description: Open Visual DevFlow and stream MUSCLE lifecycle events into its dashboard
argument-hint: "[project]"
---

Enable Visual DevFlow for the current project:

```bash
muscle visualize
```

If the user provides a project path, pass it through:

```bash
muscle visualize --project .
```

This command launches or reuses the Visual DevFlow loopback dashboard when its
control command is installed. Once enabled, `muscle run`, `muscle resume`, and
`muscle review` automatically emit best-effort task and agent events so the
dashboard shows generation, evaluation, review, fixing, verification, and
learning progress alongside the normal project tree and dependency graph.

If Visual DevFlow is installed outside PATH, use:

```bash
muscle visualize --command /path/to/visual-devflow
```
