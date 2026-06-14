# Model Routing And Packs

| Field | Value |
|---|---|
| Audience | Operators tuning model behavior and agents deciding delegation |
| Status | Current overlay and routing model |
| Source of truth | [`src/muscle/routing.py`](../../src/muscle/routing.py), [`src/muscle/providers.py`](../../src/muscle/providers.py), [`src/muscle/model_identity.py`](../../src/muscle/model_identity.py), [`src/muscle/llm/tool_schema_compat.py`](../../src/muscle/llm/tool_schema_compat.py), [`src/muscle/lesson_resolver.py`](../../src/muscle/lesson_resolver.py), [`src/muscle/system_db.py`](../../src/muscle/system_db.py), [`src/muscle/model_packs.py`](../../src/muscle/model_packs.py) |
| Primary commands | `muscle route`, `muscle provider ...`, `muscle model status`, `muscle model select`, `muscle model packs ...` |

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

## Provider Roles

Provider selection stays behind the MUSCLE CLI/provider layer. The intended
split is:

| Role | Meaning |
|---|---|
| Host | The interactive planner/synthesizer, usually Claude Code/Fable or heavy Opus. |
| Executor | The MUSCLE backend doing bulk review, validation, pattern scans, and learning work. |

MiniMax remains a current cheap executor. OpenRouter is a current
user-selected gateway executor. Claude subscription/API providers remain
available when the user intentionally wants Claude credit or API spend.

Useful commands:

```bash
muscle provider list
muscle provider show
muscle provider use openrouter-api
muscle provider use minimax-plan
```

## OpenAI-Compatible Tool Schemas

OpenAI-compatible providers require every function/tool `parameters` schema to
be an object at the root. MUSCLE keeps generated/internal handler contracts
unchanged and normalizes only at the provider boundary in
`tool_schema_compat.py`.

Boundary rules:

| Source schema root | Provider-facing property | Dispatch behavior |
|---|---|---|
| `{"type": "array", ...}` | `items` | unwrap `arguments["items"]` before the handler |
| scalar or top-level `enum` / `const` | `value` | unwrap `arguments["value"]` before the handler |
| top-level `oneOf` / `anyOf` / `allOf` / `not` | `payload` | unwrap `arguments["payload"]` before the handler |
| valid `{"type": "object", ...}` | unchanged | pass arguments through unchanged |

The provider-facing root must not contain top-level `oneOf`, `anyOf`, `allOf`,
`enum`, `const`, or `not`. Invalid provider-facing schemas are rejected locally
before network I/O with an actionable error. Tool names and command names are
not renamed; for example generated names such as `_multicategorysearchitems`
stay stable while only their provider-facing `parameters` wrapper changes.

Agent implementation notes:

- Use `normalize_openai_compatible_payload()` when serializing OpenAI-style
  `tools` or legacy `functions`.
- Keep the returned `argument_wrappers` mapping with the registered tool call.
- Before dispatch, call `unwrap_openai_tool_arguments(function_name, arguments,
  argument_wrappers)` to recover the original handler argument shape.

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
