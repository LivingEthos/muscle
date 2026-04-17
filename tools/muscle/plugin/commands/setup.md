---
description: Initialize or enable MUSCLE for the current project
args:
  - name: action
    description: "Action: init, enable, disable, status"
    required: false
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
