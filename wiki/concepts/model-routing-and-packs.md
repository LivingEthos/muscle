# Model Routing And Packs

| Field | Value |
|---|---|
| Audience | Operators tuning model behavior and agents deciding delegation |
| Status | Current overlay and routing model |
| Source of truth | [`src/muscle/routing.py`](../../src/muscle/routing.py), [`src/muscle/model_identity.py`](../../src/muscle/model_identity.py), [`src/muscle/lesson_resolver.py`](../../src/muscle/lesson_resolver.py), [`src/muscle/system_db.py`](../../src/muscle/system_db.py), [`src/muscle/model_packs.py`](../../src/muscle/model_packs.py) |
| Primary commands | `muscle route`, `muscle model status`, `muscle model select`, `muscle model packs ...` |

MUSCLE separates task routing, model identity, and optional model-pack lessons.
The current project remains the first source of truth.

## Task Routing

`muscle route` classifies work before expensive context is spent:

```bash
muscle route --task "Add validation tests for settings parser" --json
```

Router tiers:

| Tier | Meaning |
|---|---|
| `mechanical` | Suitable for direct M2.7 execution. |
| `reasoning` | Suitable for M2.7 with verification. |
| `architectural` | Should usually stay with the host model. |

Recommendations include `m27`, `m27_with_verify`, or `escalate_to_host`.

## Model Identity

`ModelIdentityResolver` resolves model labels into stable canonical model keys.
Manual overrides take precedence over aliases and heuristics.

```bash
muscle model status
muscle model history
muscle model select --canonical-model minimax/m2.7@1
muscle model select --clear
```

Use manual selection when provider labels are ambiguous or when pack scope needs
a stable canonical key.

## Model Packs

Model packs are optional canonical-model overlays. They should not override
project-local memory.

```bash
muscle model packs list
muscle model packs install --canonical-model minimax/m2.7@1
muscle model packs install --bundle-path /path/to/bundle
muscle model packs update --canonical-model minimax/m2.7@1
muscle model packs export-candidate --canonical-model minimax/m2.7@1
muscle model packs submit --bundle-path /path/to/bundle --draft
```

## Lesson Resolution Order

The effective prompt context is composed in this order:

1. Project-local lessons.
2. Related-project provisional overlays, if enabled.
3. Model-pack overlays for the resolved canonical model, if enabled.
4. Global lessons only where current code explicitly permits them.

Project-local lessons win conflicts.

## Settings

```bash
muscle settings model --related-mode suggest --pack-mode suggest
muscle settings model --related-mode off
muscle settings model --pack-mode off
muscle settings model --canonical-model minimax/m2.7@1
```

Recommended default for new projects: keep related-project and model-pack modes
at `suggest` until the project has enough local evidence.

