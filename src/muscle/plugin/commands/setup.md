---
description: Initialize or enable MUSCLE for the current project
argument-hint: "[--non-interactive] [--platform claude-code|codex|opencode] [--canonical-model <model>]"
---

Configure MUSCLE for the current project.

For a guided first-time setup that can surface related-project suggestions and unresolved
model identity prompts, run:
```bash
muscle init
```

If action is "init" or no MUSCLE installation exists (no `.muscle/` directory), the
conservative non-interactive default is:
```bash
muscle init --non-interactive
```

That keeps the new knowledge layers in `suggest` mode instead of auto-applying them.
To make the non-interactive setup explicit, you can also run:
```bash
muscle init --non-interactive --related-mode suggest --pack-mode suggest
```

If you already know the backing model for a custom or ambiguous endpoint, set it during
setup so model-specific packs can be used immediately:
```bash
muscle init --non-interactive --canonical-model openai/gpt-5@1 --pack-mode auto
```

During interactive setup:
- related-project suggestions remain opt-in and are never auto-imported
- unresolved model identity prompts let you skip or pick a canonical model explicitly
- model-pack mode defaults to `suggest`, not `auto`

To switch fix execution between the local checkout and isolated worktrees:
```bash
muscle settings review --execution local
muscle settings review --execution worktree
muscle settings review --async-workers --async-worker-limit 3
```

To inspect or switch MUSCLE's execution backend without leaving the CLI, use the
provider command group from the main MUSCLE CLI.

MiniMax is the default low-cost worker backend. OpenRouter is available for
user-selected gateway models via `OPENROUTER_API_KEY` and
`MUSCLE_OPENROUTER_MODEL`; its model identity and pricing are reported as
gateway-scoped unless configured evidence says otherwise. Codex subscription
execution uses the official Codex CLI and ChatGPT sign-in:
```bash
muscle provider login codex-subscription
muscle provider use codex-subscription
```

Codex subscription usage spends ChatGPT Codex subscription allowance, not
OpenAI API dollars. MUSCLE does not store ChatGPT OAuth tokens.

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
muscle status --refresh
muscle doctor
```

To inspect related-project memory suggestions:
```bash
muscle memory related
```

To inspect or manually select the canonical model:
```bash
muscle model status
muscle model select --canonical-model minimax/m2.7@1
```

Model packs are optional overlays. Project-local memory remains authoritative.
If setup leaves model identity unresolved, use `muscle model select` later to opt in.
To submit a reviewed pack candidate to the community draft repo:
```bash
muscle model packs submit --bundle-path .muscle/model-pack-exports/example/export-id --draft
```

For hook configuration:
```bash
muscle settings hooks --enable
muscle settings hooks --disable
```

For lifecycle, manifest, and snapshot diagnostics:
```bash
muscle doctor --refresh
```
