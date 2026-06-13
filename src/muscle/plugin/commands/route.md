---
description: Classify a task and decide where it should run (M3 vs host model)
argument-hint: "[task] [scope]"
---

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

Classify a task and decide whether MUSCLE's M3 agents should handle it directly or escalate to the host model. Execute:

```bash
muscle route --task "$ARGUMENTS" --json
```

If the user supplied a separate scope, append `--scope <path>`.

The classifier returns:
- **tier**: `mechanical` (pattern/boilerplate/test), `reasoning` (debug/trace/refactor), or `architectural` (design/decision/multi-module)
- **recommended**: `m27` (direct M3), `m27_with_verify` (M3 + verification loop), or `escalate_to_host` (host model should plan directly)
- **confidence**: 0.0-1.0
- **rationale**: one-sentence explanation
- **host_risk**: deterministic Fable safeguard metadata, including `safe_for_fable`, `likely_fallback`, `reason_codes`, `recommended_host`, `recommended_executor`, `needs_user_confirmation`, and `fallback_policy`
- **host_effort**: host effort ladder metadata, including `effort`, `max_output_tokens`, `retry_ladder`, `stop_condition`, `must_not_downgrade`, and `avoided_escalation`
- **recommended_host_role** / **recommended_executor_role**: separates the premium host planner/synthesizer from the MUSCLE worker backend
- **executor_provider** / **executor_capability_profile**: the selected MUSCLE execution provider and capability profile
- **provider_identity_trust** / **provider_cost_confidence**: whether model identity and pricing are first-party, gateway-reported, known, estimated, or unknown

Rules enforced by the router:
- `architectural` tasks ALWAYS escalate to host
- Tasks with confidence < 0.5 ALWAYS escalate to host
- `mechanical` tasks with test targets get `m27_with_verify`
- Fable fallback-risk labels are separate from ordinary host escalation; if `host_risk.likely_fallback=true`, do not treat the route as a normal successful Fable execution.
- High/critical unverified work and verification failures must not finish at only `medium` effort; likely Fable fallback suppresses `max` effort unless the user explicitly requested maximum effort.
- OpenRouter executor routes preserve the exact requested gateway model label and must not be treated as first-party identity or known pricing unless configured evidence proves it.
