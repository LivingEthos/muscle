---
description: Explain how to stop MUSCLE work when there is no dedicated cancel subcommand
---

There is no cancel command in MUSCLE, and there is no dedicated `cancel` CLI
subcommand.

For a foreground generation session, use:

```bash
muscle abort
```

For background shadow-review jobs, use the inspection commands that MUSCLE
ships today:

```bash
muscle probe
muscle diagnosis
```

If you need to stop an external worker process directly, do that at the process
level and then use `muscle probe` again to confirm the recorded job state.
