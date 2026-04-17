---
description: Install, list, or update optional model-pack overlays for the current project
args: []
---

Project-local memory remains authoritative. Model packs are optional overlays keyed to the resolved
or manually selected canonical model.

To install a pack from the community repo for a known canonical model:
```bash
muscle model packs install --canonical-model minimax/m2.7@1
```

To install a local exported bundle instead:
```bash
muscle model packs install --bundle-path /path/to/bundle
```

To inspect installed packs:
```bash
muscle model packs list
```

To refresh an installed pack:
```bash
muscle model packs update --canonical-model minimax/m2.7@1
```
