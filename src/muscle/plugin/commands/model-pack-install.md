---
description: Install, list, or update optional model-pack overlays for the current project
---

Project-local memory remains authoritative. Model packs are optional overlays keyed to the resolved
or manually selected canonical model.

To install a pack from the community repo for a known canonical model:
```bash
muscle model packs install --canonical-model minimax/m3@1
```

To install a local exported bundle instead:
```bash
muscle model packs install --bundle-path /path/to/bundle
```

To install MUSCLE's bundled local Fable 5 host-orchestration pack:
```bash
muscle model packs install --bundle-path src/muscle/model_pack_bundles/anthropic/claude-fable-5@2026-06-09
```

To inspect installed packs:
```bash
muscle model packs list
```

To refresh an installed pack:
```bash
muscle model packs update --canonical-model minimax/m3@1
```

Legacy M2.7 pack pins remain available when reproducing older runs:
```bash
muscle model packs install --canonical-model minimax/m2.7@1
```
