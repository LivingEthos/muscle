---
description: Submit a local model-pack candidate bundle as a draft PR
args:
  - name: bundle-path
    description: Path to an exported candidate bundle
    required: true
---

Project-local memory remains primary. Model packs are optional overlays and should be reviewed before submission.

Export a deterministic candidate bundle first:
```bash
muscle model packs export-candidate --canonical-model minimax/m2.7@1
```

```bash
muscle model packs submit --bundle-path /path/to/bundle --draft
```
