---
description: Configure canonical model selection plus related-project and model-pack policy
---

Project-local memory remains authoritative. Use this to control optional overlay behavior for the
current project.

To inspect the current model and overlay settings:
```bash
muscle settings model
```

To set the canonical model explicitly:
```bash
muscle settings model --canonical-model minimax/m3@1
muscle settings model --canonical-model openai/gpt-5.5@1
```

For a legacy M2.7 pin, use:
```bash
muscle settings model --canonical-model minimax/m2.7@1
```

For Codex subscription execution, authenticate and select the provider through
the provider group:
```bash
muscle provider login codex-subscription
muscle provider use codex-subscription
```

To keep related-project lessons suggested but not auto-applied, and model packs suggested by
default:
```bash
muscle settings model --related-mode suggest --pack-mode suggest
```

To disable related-project suggestions or model-pack overlays:
```bash
muscle settings model --related-mode off
muscle settings model --pack-mode off
```

To clear a manual model override:
```bash
muscle settings model --clear
```
