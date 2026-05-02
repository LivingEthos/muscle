---
description: Manually select or clear the canonical model for this project
argument-hint: "[canonical-model]"
---

Use this when the provider label is ambiguous or when you want model-pack overlays for a known model.
Project-local memory remains primary even when a canonical model is selected.

```bash
muscle model select --canonical-model minimax/m2.7@1
```

To change pack policy at the same time:
```bash
muscle model select --canonical-model minimax/m2.7@1 --pack-mode auto
```

To clear the manual override:
```bash
muscle model select --clear
```

To also adjust pack policy in one place, use:
```bash
muscle settings model --pack-mode suggest
```
