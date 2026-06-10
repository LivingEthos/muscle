---
description: Generate an opt-in local foresight preflight without durable memory promotion
argument-hint: "[task] [target]"
---

Generate a bounded short-term preflight for the current project:

```bash
muscle foresight --task "Plan the next small release-hardening slice"
```

If the user provides a target file or directory, pass it through:

```bash
muscle foresight --task "Plan CLI tests" --target tests/unit/test_cli.py
```

For structured output suitable for automation:

```bash
muscle foresight --task "Plan CLI tests" --target tests/unit/test_cli.py --json
```

This command is explicit and offline. It may write `.muscle/MUSCLE_SHORT_TERM.md`
when the project already has `.muscle/` state, but it does not run during normal
`muscle run` or `muscle review`, and it does not mutate CLAUDE.md, AGENTS.md,
MEMORY.md, model packs, or learned rules.
