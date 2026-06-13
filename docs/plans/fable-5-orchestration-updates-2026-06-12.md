# Fable 5 Orchestration Update Plan for MUSCLE

Date: 2026-06-12

Inputs:

- `docs/fable-5-system-card-muscle-recommendations-2026-06-12.md`
- Current MUSCLE development guide in `AGENTS.md`
- Current repo layout under `src/muscle/`, including the package-based CLI in
  `src/muscle/cli/`

## Executive Summary

The Fable 5 system-card lessons should not become a generic prompt tweak. They
should become a host-orchestration layer that decides when Fable is worth paying
for, when it is likely to degrade or fall back, how much effort to request, and
which final claims can be made from evidence.

The highest-value update is a Fable-aware routing and reporting spine:

1. Add deterministic Fable safeguard/fallback preflight before expensive host
   calls.
2. Replace static "use xhigh" guidance with a measurable host effort ladder.
3. Make verification claims typed and evidence-backed.
4. Wrap untrusted content before it reaches host or worker prompts.
5. Make cache-stable prompt prefixes and fallback telemetry visible in cost
   reports.
6. Add hard-tail async workers only after the evidence and routing foundations
   are in place.

Product direction update: MUSCLE should be developed first as the Claude
Code/Fable 5 optimizer, because that is the workflow where cost pressure,
host-memory files, Claude-native skills/subagents, and subscription/API token
savings are most concrete. That does not mean Claude becomes the only MUSCLE
agent backend. MiniMax and OpenRouter remain active optional execution
providers inside the MUSCLE CLI so users can move bulk review, validation,
pattern scanning, and self-learning work away from Fable or heavy Opus spend.

The main CLI should remain `muscle`. Using a separate provider CLI as the
primary user workflow is currently the painful path: each external CLI has
different auth, session, tool, streaming, JSON, and cost-accounting semantics.
When a provider CLI is useful for subscription-compliant execution, MUSCLE
should wrap it behind the provider layer instead of making users leave the
MUSCLE command/plugin surface.

This plan is ordered so each task can be implemented and verified independently.
Do not start broad async-worker work until the preflight, effort policy, and
verification-claim contracts are green.

## Current Repo Integration Points

Use these existing seams rather than creating a parallel orchestration system:

- Routing: `src/muscle/routing.py`
  - `TaskRouter`, `RouteDecision`, `offline_route`, and `ROUTING_BENCHMARK_CASES`
  - Current route output only covers task tier and M3-vs-host recommendation.
- Review orchestration: `src/muscle/code_review/review_controller.py`
  - `_route_review_request()` stores route data in `ctx.scope_summary`.
  - `_record_delegation_event()` already centralizes route, cache, provider, and
    verification metadata into `DelegationEvent.metadata`.
- Savings and cost reports: `src/muscle/delegation_metrics.py`,
  `src/muscle/cost_optimizer.py`, `src/muscle/savings.py`
  - Fable host pricing already exists.
  - `metadata_json` on `delegation_events` can carry the first version of
    preflight and fallback signals without a schema migration.
- Provider and model identity: `src/muscle/providers.py`,
  `src/muscle/model_identity.py`, `src/muscle/model_packs.py`
  - Provider profiles and canonical model keys are the right home for Fable
    capability metadata.
  - The current production execution path is the synchronous `M27Client`
    contract through `providers.create_client()`. Existing async LLM adapters
    for OpenRouter/Kimi are useful reference material, but they do not preserve
    the current MUSCLE review, cache, telemetry, structured-output, and
    learning behavior by themselves.
- Prompt composition and telemetry: `src/muscle/optimization/prompt_context.py`,
  `src/muscle/optimization/types.py`
  - `PromptEnvelope.metadata` and `TelemetryContext.metadata` are the right
    initial place for cache-layout, effort, and untrusted-envelope metadata.
- Command and artifact evidence: `src/muscle/command_evidence.py`,
  `src/muscle/code_review/review_artifacts.py`
  - Command evidence already persists raw and compact output.
  - Review artifacts already have a manifest, diagnostics, and LLM trace slots.
- Host output compression and filters:
  `src/muscle/optimization/tool_output_crusher.py`,
  `src/muscle/output_filters.py`
  - Extend these for prompt-injection anomaly retention and envelope metadata.
- CLI and plugin commands:
  - CLI entry point is `muscle.cli:main`, implemented as package modules under
    `src/muscle/cli/`.
  - Route, crush, expand, pack, filters: `src/muscle/cli/plumbing.py`.
  - Cost and long-eval: `src/muscle/cli/cost.py`.
  - Review: `src/muscle/cli/review.py`.
  - Plugin command docs live under `src/muscle/plugin/commands/`.

## Non-Goals

- Do not remove MiniMax as a cheap execution layer.
- Do not make Claude/Fable/Opus the only MUSCLE-agent backend.
- Do not demote OpenRouter to a someday-only idea. It should stay a developed
  optional API backend for users who want arbitrary model choice.
- Do not make Kimi, Codex, OpenRouter, or any provider-specific CLI the primary
  UX. The primary UX stays the MUSCLE CLI and Claude Code plugin/desktop
  workflow; provider-specific CLIs are adapter internals when needed.
- Do not route every code review through Fable.
- Do not add LLM-based preflight as the default path. The preflight must be
  deterministic first, with optional ambiguity escalation later.
- Do not add async workers before claim auditing exists. Parallelism without
  evidence discipline will multiply bad summaries.
- Do not publish a public Fable model pack until source/licensing constraints are
  reviewed separately.

## Provider Strategy Clarification

MUSCLE has two separate roles that should not be collapsed:

- Host role: the expensive interactive planner/synthesizer the user is already
  using. For the primary product path, this is Claude Code or Claude Desktop
  with Fable 5 and heavy Opus available for hard work.
- Execution role: the MUSCLE agent backend that performs bulk review, static
  analysis synthesis, fix candidate generation, verification loops, memory
  updates, skill/subagent drafting, and self-learning jobs.

The development target is:

1. Claude Code/Fable 5 is the first-class host experience.
2. MUSCLE CLI is the first-class execution and orchestration surface.
3. MiniMax remains a first-class low-cost execution provider.
4. OpenRouter becomes a first-class optional API execution provider with
   user-selected models.
5. Claude subscription/API execution remains available for cases where the user
   intentionally wants MUSCLE agents to spend Claude credit or API dollars.
6. Kimi/Codex external CLI execution can remain beta/adapter work after the
   provider contract is clean, but they should not drive the initial product
   architecture.

This preserves the big economic goal: Claude/Fable does the expensive thinking
only when it is valuable, while MUSCLE uses cheaper or user-selected providers
for the repeated agent work that creates evidence, compresses context, updates
memory, prevents repeat mistakes, and verifies fixes.

Design implications:

- Provider selection belongs in `muscle provider ...`, project config, global
  config, and `MUSCLE_PROVIDER`; not in separate user-facing CLIs.
- All production provider backends should satisfy the current `M27Client`-style
  sync surface first: `chat`, `chat_streaming`, `chat_structured`,
  `TokenUsage`, response cache, telemetry metadata, model identity, and provider
  stamping.
- OpenRouter should not be treated as first-party model identity evidence.
  Preserve both the gateway provider (`openrouter-api`) and the requested model
  string, and mark pricing/identity as user-selected or gateway-reported unless
  trusted upstream evidence is available.
- Claude subscription execution must remain compliance-oriented: invoke the
  official CLI as a subprocess when using subscription/Agent-SDK credit; never
  read, store, or replay subscription OAuth credentials.
- MiniMax plan/API paths should keep their current cost/accounting advantages,
  passive cache assumptions, and thinking-policy controls.
- Generated skills, subagent profiles, `CLAUDE.md`, `AGENTS.md`, and MUSCLE
  memory updates must be optimized by the same compaction, cache-stability,
  evidence, and mistake-correction loops they are meant to teach.

## Phase 0 - Baseline and Plan Hygiene

Goal: lock the starting state and remove path ambiguity before code work starts.

Tasks:

1. Capture `git status --short` before implementation and preserve unrelated
   modified/untracked files.
2. Confirm the CLI package layout in any docs touched during implementation.
   The old `src/muscle/cli.py` path should be treated as historical only.
3. Confirm the source recommendation document remains read-only unless the task
   explicitly changes it.
4. Run the existing focused routing and cost tests as a baseline when available:
   - `uv run pytest tests/unit/test_routing.py -v`
   - `uv run pytest tests/unit/test_cost_optimizer.py tests/unit/test_savings_discovery.py -v`

Acceptance:

- Baseline status is recorded in implementation notes.
- No unrelated dirty worktree changes are reverted or reformatted.

## Phase 1 - Fable Safeguard and Fallback Preflight

Goal: predict and label Fable fallback/degradation risk before host tokens are
spent.

New module:

- `src/muscle/host_risk_preflight.py`

Core types:

- `HostRiskReasonCode`
  - `cyber_dual_use`
  - `bio_chem`
  - `distillation`
  - `frontier_llm_development`
  - `binary_reconstruction_or_exploit_like`
  - `benign_software_engineering`
- `HostRiskPreflightInput`
  - `task_text`
  - `target_paths`
  - `workflow_mode`
  - `static_issue_categories`
  - `requested_tools`
  - `user_declared_domain`
- `HostRiskPreflightDecision`
  - `safe_for_fable`
  - `likely_fallback`
  - `reason_codes`
  - `recommended_host`
  - `recommended_executor`
  - `needs_user_confirmation`
  - `rationale`

Implementation details:

1. Build a deterministic classifier using normalized task text, workflow mode,
   static analyzer categories, file names, requested tools, and explicit domain
   hints.
2. Prefer allowlist-like benign code-review classification for normal software
   engineering requests.
3. Treat exploit reconstruction, malware-like binary rebuilds, credential theft,
   offensive security execution, wet-lab biology/chemistry, distillation, and
   frontier model development as Fable-risk categories.
4. Return a decision object even when confidence is low. Low confidence should
   prefer `needs_user_confirmation=True` and `recommended_host=claude-opus-4-8`
   or `recommended_executor=minimax-m3`, depending on task shape.
5. Extend `RouteDecision` or add a nested route metadata payload so `TaskRouter`
   can expose host risk without changing the existing `tier/recommended`
   contract abruptly.
6. Wire preflight into:
   - `muscle route --json`
   - `ReviewController._route_review_request()`
   - `ReviewController._record_delegation_event()`
   - `DelegationMetrics.report()`
   - `src/muscle/plugin/commands/route.md`

Metadata contract:

Add these keys to `DelegationEvent.metadata` for review and route flows:

- `requested_host_model`
- `recommended_host_model`
- `host_risk_safe_for_fable`
- `host_risk_likely_fallback`
- `host_risk_reason_codes`
- `host_risk_needs_user_confirmation`
- `fallback_policy`

Tests:

- `tests/unit/test_host_risk_preflight.py`
  - one positive test per reason code
  - benign code-review case stays safe for Fable
  - ambiguous dual-use case requires confirmation
- `tests/unit/test_routing.py`
  - route JSON includes host-risk metadata
  - architectural route still escalates to host
  - Fable-risk route is labeled separately from architectural escalation
- `tests/unit/test_delegation_metrics.py` or existing cost-report tests
  - report counts likely avoided Fable fallbacks
  - JSON output includes the new host-risk fields

Verification:

```bash
uv run pytest tests/unit/test_host_risk_preflight.py tests/unit/test_routing.py -v
uv run pytest tests/unit/test_cost_optimizer.py tests/unit/test_savings_discovery.py -v
```

Acceptance:

- No Fable-risk route is reported as an ordinary successful Fable execution.
- Cost report can distinguish "host escalation", "Fable fallback risk", and
  "M3 delegated work".

## Phase 2 - Host Effort Ladder

Goal: replace static xhigh guidance with an effort policy that escalates only
when evidence justifies it.

New module:

- `src/muscle/host_effort_policy.py`

Core types:

- `HostEffortLevel`: `medium`, `high`, `xhigh`, `max`
- `HostEffortDecision`
  - `effort`
  - `max_output_tokens`
  - `retry_ladder`
  - `stop_condition`
  - `rationale`
  - `must_not_downgrade`

Policy inputs:

- route tier
- target type and size
- verification failure count
- high/critical issue count
- task novelty
- fallback risk
- benchmark mode
- explicit user maximum-effort request
- time or token budget

Default ladder:

- `medium`
  - planning summaries
  - final synthesis from good evidence
  - straightforward review summaries
  - code tasks with deterministic evidence and passing checks
- `high`
  - complex semantic review
  - fix generation that touches multiple files
  - professional artifacts with nontrivial constraints
  - ambiguous review arbitration
- `xhigh` or `max`
  - failed verification retry
  - benchmark mode
  - hard-tail task after cheap workers disagree
  - explicit user request for maximum effort

Implementation details:

1. Add the policy module with no provider coupling first.
2. Add effort decision metadata to route JSON, review artifacts, and delegation
   metadata.
3. Add a provider capability field indicating whether effort can be transmitted
   as an API parameter or is host-orchestration metadata only.
4. Keep M3 `thinking_policy.py` separate. M3 thinking mode is not the same as
   host effort.
5. Add guardrails:
   - high/critical unverified fixes cannot finish with only `medium`.
   - failed verification escalates one rung at most per retry.
   - likely fallback prevents max Fable effort unless the user explicitly asks.

Tests:

- `tests/unit/test_host_effort_policy.py`
  - matrix over route tier, severity, verification failures, and benchmark mode
  - high/critical unverified fixes cannot stay at medium
  - likely fallback suppresses Fable max escalation
- Update route/cost report tests to include effort metadata.

Verification:

```bash
uv run pytest tests/unit/test_host_effort_policy.py tests/unit/test_routing.py -v
```

Acceptance:

- Every host-route decision has an effort decision.
- Savings reports can count avoided effort escalations separately from measured
  token savings.

## Phase 3 - Typed Verification Claims

Goal: stop ungrounded "verified" or "end-to-end" claims from entering handoffs
and final reports.

New module:

- `src/muscle/verification_claims.py`

Core types:

- `VerificationClaimType`
  - `ran_test`
  - `typechecked`
  - `linted`
  - `manual_inspection`
  - `runtime_smoke`
  - `not_run`
  - `blocked`
- `VerificationClaim`
  - `claim_text`
  - `claim_type`
  - `evidence_id`
  - `command`
  - `exit_code`
  - `observed_at`
  - `limitations`
- `ClaimAuditResult`
  - `allowed_claims`
  - `downgraded_claims`
  - `blocked_claims`
  - `not_run`

Implementation details:

1. Add an `evidence_id` to `CommandEvidence`, derived from command, cwd,
   created_at, exit code, and artifact path. Keep raw artifact paths intact.
2. Add `ReviewArtifactStore.write_claims()` so every review session can persist
   `verification-claims.json`.
3. Teach fix verification, static analyzer validation, and post-fix validation
   to emit claims instead of only prose fields.
4. Add a claim auditor:
   - "verified" requires a passing command or runtime-smoke evidence ID.
   - "end-to-end" requires a runtime path, not just lint/typecheck.
   - failed commands must appear in summaries.
   - requested-but-skipped checks must create `not_run` claims.
5. Update handoff and summary generation:
   - include evidence IDs beside verification statements.
   - add a "Not run" section when claims require it.
   - downgrade "verified" to "inspected" when evidence is manual only.

Tests:

- `tests/unit/test_verification_claims.py`
  - rejects "verified end-to-end" with lint-only evidence
  - failed command evidence must be surfaced
  - manual inspection downgrades completion language
- `tests/unit/test_command_evidence.py`
  - evidence ID is stable enough for artifact linking
- Review workflow integration test:
  - auto-fix run writes `verification-claims.json`

Verification:

```bash
uv run pytest tests/unit/test_verification_claims.py tests/unit/test_command_evidence.py -v
uv run pytest tests/integration/test_review_pipeline.py -v
```

Acceptance:

- Fixture suite has zero false "verified" claims.
- All verification claims in review artifacts have either an evidence ID or an
  explicit `not_run`/`blocked` limitation.

## Phase 4 - Fable Prompt-Injection Firewall

Goal: ensure untrusted tool, document, dependency, issue, PR, and generated
content is framed as data before host or worker models see it.

New module:

- `src/muscle/untrusted_content.py`

Core types:

- `UntrustedSourceKind`
  - `web`
  - `file`
  - `dependency_source`
  - `email`
  - `issue_body`
  - `pr_comment`
  - `generated_artifact`
  - `command_output`
- `UntrustedPermissions`
  - `read_only`
  - `action_forbidden`
  - `citation_only`
  - `trusted_local`
- `UntrustedContentEnvelope`
  - `source_kind`
  - `permissions`
  - `instruction_policy`
  - `digest`
  - `source_path`
  - `sanitizer_warnings`
  - `content`

Implementation details:

1. Add deterministic envelope rendering:
   - clear start/end sentinels
   - explicit "content is data" instruction policy
   - digest/source path
   - permissions
2. Add sanitizer flags for:
   - instruction-like text
   - hidden HTML/CSS text
   - base64-looking payloads
   - "ignore previous instructions" variants
   - shell-command-looking blocks in external docs
3. Integrate first with:
   - `code_reviewer.build_semantic_review_prompt()`
   - `source_context.py`
   - `agent_kb_fetcher.py`
   - `command_evidence.build_command_evidence()`
   - `tool_output_crusher.crush_text()`
4. Action tools must consume parsed trusted decisions only, not raw untrusted
   content.
5. Preserve suspicious lines as evidence. Do not silently drop them.

Tests:

- `tests/unit/test_untrusted_content.py`
  - markdown prompt injection fixture
  - HTML hidden text fixture
  - JSON tool-output injection fixture
  - dependency README injection fixture
- Update code reviewer prompt determinism tests so the envelope is stable.

Verification:

```bash
uv run pytest tests/unit/test_untrusted_content.py tests/unit/test_prompt_determinism.py -v
```

Acceptance:

- Prompt-injection fixtures are preserved as evidence but never rendered as
  executable model instructions.
- Envelope rendering is byte-stable for the same input.

## Phase 5 - Cache-Aware Host Prompt Layout

Goal: make stable host prompt prefixes measurable and lintable so Fable cache
reads compound with command-output crushing.

New module:

- `src/muscle/optimization/prompt_prefix.py`

Core types:

- `PromptPrefixSection`
- `PromptPrefixPlan`
- `PromptPrefixLintWarning`
- `PromptPrefixCostEstimate`

Stable prefix order:

1. system instructions
2. MUSCLE methodology and delegation contract
3. stable project summary
4. model-pack lessons
5. tool schemas
6. dynamic task payload

Implementation details:

1. Add `PromptPrefixPlanner` that returns stable and dynamic prompt sections.
2. Add a prefix linter that flags unstable content in the cacheable prefix:
   - timestamps
   - random IDs
   - transient status
   - path lists from current scans
   - token counters
   - command output
3. Extend `compose_prompt_envelope()` metadata with:
   - `cache_prefix_chars`
   - `cache_prefix_digest`
   - `cache_prefix_lint_warning_count`
   - `estimated_cache_fresh_cost`
   - `estimated_cache_read_cost`
4. Add CLI surface by extending the existing host-doc optimization command:
   - `muscle optimize-host-docs --cache-layout --dry-run`
   - plugin doc: `src/muscle/plugin/commands/optimize-host-docs.md`
5. Flow provider telemetry cache-read/write tokens into savings reports when
   available. Until provider telemetry exists, label cost as estimated.

Tests:

- Byte-stability tests for prompt prefix plans.
- Linter tests for timestamp/random-ID/path-list warnings.
- Savings/report tests for cache read/write token fields.

Verification:

```bash
uv run pytest tests/unit/test_prompt_compactor.py tests/unit/test_prompt_context_compaction.py -v
uv run pytest tests/unit/test_host_memory_optimizer.py tests/unit/test_savings_discovery.py -v
```

Acceptance:

- Dynamic task payload changes do not alter the stable-prefix digest.
- Reports separate crush savings, cache savings, and avoided fallback waste.

## Phase 6 - Claude-First Provider Strategy and Optional Agent Backends

Goal: keep Claude Code/Fable 5 as the primary host experience while making
MiniMax and OpenRouter clean, current, optional MUSCLE-agent execution backends
inside the MUSCLE CLI.

Principle:

- `muscle` is the orchestration surface.
- Provider adapters are interchangeable execution engines.
- Host routing decides when expensive Claude/Fable/Opus reasoning is worth it.
- Agent routing decides which cheaper or user-selected backend should do the
  repeatable MUSCLE work.

Implementation details:

1. Extend the provider registry shape with explicit role/capability metadata:
   - `execution_surface`: `http-api`, `official-cli`, or `manual-host`
   - `provider_role`: `cheap-worker`, `premium-host`, `fallback-host`,
     `user-selected-gateway`
   - `supports_structured_json`
   - `supports_streaming`
   - `supports_effort`
   - `supports_cache_telemetry`
   - `subscription_safe`
   - `identity_trust`: `first-party`, `gateway-reported`, `alias-only`
   - `pricing_source`: `known`, `estimated`, `unknown`
2. Keep and harden existing Claude providers:
   - `claude-subscription`: official Claude CLI subprocess for subscription /
     Agent-SDK-credit use only; no credential scraping; default effort policy
     maps to `medium` and `high` first, with `xhigh/max` only when justified.
   - `anthropic-api`: direct API for explicit Claude API-dollar spend.
   - Add Fable host capability metadata without forcing every Claude execution
     call to be Fable.
3. Keep MiniMax as a first-class optional execution backend:
   - `minimax-plan`: default low-marginal-cost provider when configured.
   - `minimax-api`: pay-as-you-go MiniMax path.
   - Preserve MiniMax passive prefix-cache accounting, M3 thinking policy, and
     long-context pricing behavior.
   - Make docs stop implying MiniMax is the only possible MUSCLE brain while
     also avoiding the opposite mistake of treating it as deprecated.
4. Add OpenRouter as a first-class optional API execution backend:
   - provider name: `openrouter-api`
   - env key: `OPENROUTER_API_KEY`
   - model selection: project/global config plus an env override such as
     `MUSCLE_OPENROUTER_MODEL`
   - billing: `api-dollars`
   - role: `user-selected-gateway`
   - identity: keep both `provider=openrouter-api` and the exact requested /
     served model labels; do not upgrade gateway-served models to trusted
     first-party identities without verified upstream evidence.
   - pricing: support explicit user-configured rates where possible; otherwise
     label savings/cost as estimated or unknown rather than inventing precision.
   - implementation path: build an `M27Client`-compatible sync adapter or a
     shared OpenAI-compatible client wrapper for the product path. The existing
     async `src/muscle/llm/adapters/openrouter.py` can be mined for endpoint
     details, but should not be wired directly into review orchestration unless
     the sync contract is preserved.
   - schema compatibility: any OpenAI-compatible tool/function schema emitted
     by this adapter must pass a top-level object-root validator before the API
     call is sent. Pydantic/Zod/OpenAPI schemas that produce a top-level
     `array`, `enum`, `const`, `oneOf`, `anyOf`, `allOf`, or `not` must be
     wrapped at the provider boundary instead of changing the underlying
     feature contract.
5. Treat provider-specific CLI adapters as beta surfaces unless they are needed
   for compliance:
   - Claude CLI is justified because subscription-compliant execution requires
     the official binary.
   - Kimi/Codex CLI adapters should wait until the provider contract is stable,
     unless a specific subscription-compliance need makes one worth adding.
   - If added, they must still appear as MUSCLE providers and keep MUSCLE's
     structured output, telemetry, cache, and learning behavior.
6. Extend model identity aliases:
   - `anthropic/claude-fable-5@2026-06-09`
   - common labels such as `claude-fable-5` and `fable 5`
   - MiniMax M3/M-series aliases already supported by the MiniMax path should
     remain first-party only for MiniMax endpoints.
   - OpenRouter arbitrary model strings should resolve as gateway-scoped labels
     unless trusted evidence is available.
7. Add provider capability profiles without forcing all providers to support the
   same model:
   - `claude-fable-5`: premium synthesis/tool/professional/code host with
     fallback-risk preflight
   - `claude-opus-4-8`: fallback host
   - `codex-default`: local code executor host
   - `minimax-m3`: cheap worker/reviewer
   - `openrouter-selected`: user-selected gateway worker/reviewer
8. Store capabilities in a typed registry rather than only in prompt text.
9. Teach routing:
   - use Fable for final synthesis, professional artifacts, tool planning, and
     hard code reasoning after cheap evidence compression
   - avoid Fable for bulk static review, raw log scanning, mechanical fix
     generation, and likely fallback domains
   - prefer MiniMax or OpenRouter for bulk MUSCLE-agent work when configured and
     when the task can be validated by evidence
   - keep high-risk final claims with the host until typed verification evidence
     exists
10. Add route JSON fields:
   - `recommended_host_role`
   - `recommended_executor_role`
   - `host_capability_profile`
   - `executor_provider`
   - `executor_capability_profile`
   - `provider_identity_trust`
   - `provider_cost_confidence`

OpenAI-compatible tool schema contract:

Add a small shared helper, preferably `src/muscle/llm/tool_schema_compat.py`,
used only at provider/API boundaries. Its job is to normalize generated
function/tool schemas without changing MUSCLE's internal feature behavior.

Rules:

1. Every emitted function `parameters` schema must have root
   `{"type": "object", "properties": ...}`.
2. The root schema must not contain `oneOf`, `anyOf`, `allOf`, `enum`, `const`,
   or `not`. These keywords may remain inside properties only where the target
   provider supports them.
3. If the source schema is a top-level array, expose it as:
   - property name: `items`
   - schema: the original array schema
   - dispatch behavior: unwrap `arguments["items"]` before calling the existing
     handler.
4. If the source schema is a top-level scalar or enum, expose it as:
   - property name: `value`
   - schema: the original scalar/enum schema
   - dispatch behavior: unwrap `arguments["value"]`.
5. If the source schema is a top-level union/combinator, expose it as:
   - property name: `payload`
   - schema: the original union/combinator schema when the provider allows
     nested combinators; otherwise convert it into a conservative object with a
     required discriminator plus provider-supported properties.
   - dispatch behavior: unwrap `arguments["payload"]`.
6. If the source schema is already a valid object-root schema, preserve it
   byte-for-byte except for provider-required fields such as
   `additionalProperties: false`.
7. Function names, route names, handler names, and user-facing command names
   must not be renamed as part of this fix. Generated names like
   `_multicategorysearchitems` are allowed to remain stable; only their
   `parameters` wrapper changes.
8. The wrapper/unwrapper mapping must be stored with the registered tool so
   callers and tests can prove the public feature result is unchanged.

Tests:

- `tests/unit/test_model_identity.py`
- `tests/unit/test_providers.py`
- `tests/unit/test_routing.py`
- New or extended OpenAI-compatible schema tests:
  - top-level array schemas are wrapped under `items` and unwrapped before
    handler invocation
  - top-level enum/scalar schemas are wrapped under `value`
  - top-level `oneOf`/`anyOf`/`allOf` schemas are wrapped under `payload`
  - already-valid object-root schemas remain stable
  - a generated `_multicategorysearchitems` fixture validates as an
    object-root function schema and still dispatches to the same search
    behavior
  - provider serialization rejects invalid top-level schemas before network I/O
    with a local, actionable error
- OpenRouter-specific provider tests:
  - missing API key fails clearly
  - arbitrary model label is preserved
  - gateway identity does not become first-party identity
  - unknown pricing is labeled, not silently treated as MiniMax or Claude

Verification:

```bash
uv run pytest tests/unit/test_model_identity.py tests/unit/test_providers.py \
  tests/unit/test_routing.py -v
```

Acceptance:

- Fable identity resolves to a canonical model key when requested.
- Route output distinguishes host role from executor role.
- MiniMax remains selectable and documented as a current optional agent backend.
- OpenRouter is selectable through MUSCLE provider configuration, preserves
  arbitrary model choice, and does not weaken identity/cost accounting.
- OpenAI-compatible providers cannot emit function schemas that fail with
  "schema must have type 'object' and not have top-level combinators"; existing
  tool behavior is preserved through boundary wrapping and unwrapping.
- Users do not need to leave the MUSCLE CLI to use MiniMax or OpenRouter for
  MUSCLE-agent execution.

Phase 6 implementation sequence:

1. Provider metadata-only slice:
   - extend `ProviderProfile` or add a sibling capability registry
   - keep the existing four providers behaviorally unchanged
   - add route/report serialization for role, surface, identity trust, and cost
     confidence
   - update provider CLI output so users can see which providers are cheap
     workers, premium hosts, or gateway providers
2. MiniMax preservation slice:
   - add regression tests proving `minimax-plan` and `minimax-api` remain
     selectable through env/project/global config
   - keep MiniMax credential guards isolated from Claude/OpenRouter credentials
   - update README/plugin wording from "MiniMax required" to "MiniMax optional
     low-cost backend" where accurate
3. OpenRouter product-path slice:
   - add `OpenRouterApiClient` on the product `M27Client`-compatible path
   - add `openrouter-api` to `PROVIDERS`
   - add config/env model selection
   - preserve arbitrary model labels in request metadata and artifacts
   - add tests for structured output, usage parsing, missing credentials,
     gateway identity, and pricing uncertainty
4. OpenAI-compatible schema compatibility slice:
   - add the schema normalization helper and a small wrapper/unwrapper registry
   - route OpenRouter and any future OpenAI-compatible tool/function calls
     through the validator
   - add `_multicategorysearchitems` regression fixture coverage
   - keep internal feature handlers unchanged; only adapt the provider-facing
     request/response boundary
5. Provider-aware agent selection slice:
   - teach review, rescue, long-eval, skill generation, agent generation, and
     shadow worker paths to use the resolved provider consistently
   - record `executor_provider` on every agent job and learning event
   - ensure generated skills/subagents do not hard-code MiniMax when the
     project's configured executor is OpenRouter or Claude
6. Documentation and setup slice:
   - update `muscle setup` and `muscle provider list/show/use`
   - update plugin command docs and skill docs
   - update `config.yaml.example`
   - add a "Claude host plus optional MUSCLE executor providers" section to the
     README
   - preserve compliance wording for Claude subscription execution

Implementation progress, 2026-06-12:

- Baseline captured before this schema slice:
  `uv run pytest tests/unit/test_model_identity.py tests/unit/test_providers.py
  tests/unit/test_routing.py -v` passed with 68 tests.
- Added `src/muscle/llm/tool_schema_compat.py` as the provider-boundary helper
  for OpenAI-compatible function/tool schemas.
- The helper normalizes generated top-level array schemas under `items`,
  scalar/enum schemas under `value`, and root combinator schemas under
  `payload`; valid object-root schemas are preserved.
- The helper returns an argument unwrap registry keyed by function name so
  provider-facing wrapper arguments can be unwrapped before existing handlers
  run.
- Wired normalization into the synchronous OpenAI-compatible `M27Client.chat()`
  path and the async OpenAI-compatible adapters for OpenAI, OpenRouter, Kimi,
  Z.AI, and the MiniMax chat-completions adapter.
- Added `tests/unit/test_tool_schema_compat.py`; the new focused regression
  file passed with 11 tests before the full quality gates.
- Full quality gates passed after documentation updates:
  - `uv run pytest tests/unit/test_model_identity.py tests/unit/test_providers.py
    tests/unit/test_routing.py -v`: 68 passed.
  - `uv run mypy src/muscle/`: no issues in 189 source files.
  - `uv run ruff check src/muscle/`: all checks passed.
  - `uv run ruff format --check src/muscle/`: 189 files already formatted.
  - `uv run pytest tests/ -v`: 2940 passed, 3 skipped.

## Phase 7 - Local Fable 5 Model Pack

Goal: encode the stable Fable lessons as a repo-local model pack that can be
used by lesson resolution without relying on prose docs.

Canonical key:

- `anthropic/claude-fable-5@2026-06-09`

Initial lessons:

- run safeguard/fallback preflight before expensive Fable calls
- use the host effort ladder
- require typed evidence for verification claims
- wrap untrusted tool and document output
- reserve hard-tail async workers for tasks that meet trigger thresholds
- keep Fable as planner/synthesizer, not bulk reviewer

Implementation details:

1. Create a local bundle using the existing model-pack schema:
   - `pack.json`
   - `lessons.json`
2. Set `safety_scope=host-orchestration`.
3. Set `portability=portable`.
4. Install it through `ModelPackManager.install_bundle()` in tests or fixture
   setup.
5. Do not submit to the community model-pack repo in this phase.

Tests:

- `tests/unit/test_packs.py`
- `tests/unit/test_learning_pipeline.py` if lesson resolution is touched
- model-pack validation test for the new canonical key and safety scope

Verification:

```bash
uv run pytest tests/unit/test_packs.py tests/unit/test_model_identity.py -v
```

Acceptance:

- The Fable pack validates and can be installed locally.
- Lesson resolver can retrieve Fable host-orchestration lessons under the
  canonical key.

## Phase 8 - Hard-Tail Async Worker Mode

Goal: spend cheap worker tokens only when the hard tail justifies the
coordination overhead.

Existing foundations:

- `src/muscle/code_review/shadow_broker.py`
- `src/muscle/code_review/shadow_worker.py`
- `src/muscle/packs.py`
- worktree support in `ReviewController`

New behavior:

- Add opt-in review mode flag:
  - CLI: `muscle review --async-workers`
  - config key: `review.async_workers`
  - plugin docs for rescue/pressure/review commands
- Use hard-tail triggers:
  - target exceeds file/module threshold
  - verification failed once
  - issue spans multiple subsystems
  - route confidence is low but not architectural
  - historical pass rate for similar work is poor
- Worker model:
  - long-lived workers with bounded roles
  - shared content-addressed context pack
  - separate worktree when editing
  - lead controller owns synthesis
  - worker claims must include evidence IDs

Implementation details:

1. Add `AsyncWorkerPolicy` with deterministic trigger evaluation.
2. Extend `ReviewConfig` with `async_workers: bool = False` and optional worker
   limits.
3. Add worker job metadata to review artifacts:
   - critical path time
   - worker token usage
   - worker evidence IDs
   - skipped worker reason for easy tasks
4. Deduplicate worker outputs using structured keys:
   - file path
   - line number
   - issue category
   - CWE ID
   - source agent
5. Keep Fable arbitration limited to compact disagreements.

Tests:

- easy task does not trigger workers
- verification-failed hard-tail task triggers workers
- worker outputs are evidence-backed
- worker dedupe preserves distinct issue categories

Verification:

```bash
uv run pytest tests/unit/test_shadow_worker.py tests/integration/test_concurrent_review.py -v
uv run pytest tests/integration/test_shadow_worktree.py -v
```

Acceptance:

- Async workers do not run by default.
- Easy tasks show zero worker overhead.
- Hard-tail fixtures improve quality or latency without hiding failed worker
  claims.

## Phase 9 - Benchmark Integrity Guards

Goal: prevent MUSCLE from optimizing against contaminated or transcript-leaky
benchmark results.

Implementation details:

1. Add strict result envelopes:
   - final deliverable must be inside a parseable result span/object
   - graders only see the result envelope
2. Add contamination blocklists:
   - known benchmark answer URLs
   - local fixture answer files
   - retrieved source paths known to contain labels
3. Add transcript leakage review:
   - flag when an answer appears in tool output but not in final result evidence
   - distinguish "retrieved answer leakage" from normal source citation
4. Persist judge metadata:
   - judge model
   - prompt version
   - rubric version
   - grader run count
   - pairwise ordering fields
5. Refuse zero-scenario suites as hard failures.

Likely modules:

- `src/muscle/code_review/review_benchmark.py`
- `src/muscle/code_review/long_eval_runner.py`
- `src/muscle/structured_io.py`

Tests:

- missing result envelope is rejected
- malformed result envelope is rejected
- answer in tool output but not result evidence is flagged
- zero-scenario suite fails

Verification:

```bash
uv run pytest tests/unit/test_review_benchmark.py tests/unit/test_structured_io.py -v
uv run pytest tests/integration/test_shadow_nightly.py -v
```

Acceptance:

- Benchmarks report methodology metadata with every score.
- Long-eval output can be compared across judge and prompt versions.

## Phase 10 - Command Familiarity Guard

Goal: avoid blindly executing unfamiliar commands copied from untrusted docs,
issue bodies, tool output, or subagents.

New module:

- `src/muscle/command_familiarity_guard.py`

Implementation details:

1. Add `CommandFamiliarityGuard` with sources of truth:
   - local project docs
   - `pyproject.toml` scripts and tool config
   - package scripts
   - `--help`
   - man page
   - official docs only when network lookup is explicitly allowed
2. Integrate with `run_command_with_evidence()` for MUSCLE-owned command
   execution.
3. Add risk escalation for:
   - destructive commands
   - writes outside repo
   - git state mutation
   - option-looking filenames
   - shell metacharacters when command should be argv-safe
4. Store guard result in `CommandEvidence.warnings` and artifact JSON.
5. Keep known evaluator commands cheap by allowlisting stable internal
   invocations after tests prove the shape.

Tests:

- unknown command requires source-of-truth check
- known pytest/ruff/mypy commands pass
- destructive command is blocked or marked high risk
- filename beginning with dash is rejected or forced behind `--`

Verification:

```bash
uv run pytest tests/unit/test_command_evidence.py tests/unit/test_static_analyzer.py -v
```

Acceptance:

- MUSCLE-owned command execution records whether command familiarity was checked.
- Unknown destructive commands cannot be silently executed through the guard.

## Cross-Cutting Reporting Changes

Update these report surfaces as phases land:

- `muscle route --json`
  - host risk decision
  - effort decision
  - recommended host role and executor role
  - selected execution provider and capability profile
- `muscle cost delegation-report --format json`
  - Fable calls avoided due likely fallback
  - actual fallback events observed
  - avoided effort escalations
  - cache read/write token estimates
  - host model requested versus served
  - executor provider used for each MUSCLE-agent job
  - provider cost confidence: observed, estimated, configured, or unknown
- `muscle savings --json`
  - crush savings
  - cache savings
  - avoided fallback waste
  - avoided effort escalation
  - claim-auditor downgrade count
  - savings split by provider backend
- Review artifacts:
  - `host-risk-preflight.json`
  - `host-effort-policy.json`
  - `verification-claims.json`
  - `untrusted-content-warnings.json`
  - `provider-execution.json`
  - worker metadata when async mode runs

Fallback metadata to standardize everywhere:

- `requested_host_model`
- `served_host_model`
- `fallback_category`
- `fallback_policy`
- `fallback_observed`
- `fallback_reason_source`
- `executor_provider`
- `executor_model_requested`
- `executor_model_served`
- `executor_identity_trust`
- `executor_cost_confidence`

## Execution Order

Run implementation as a strict sequence. For each item, implement only that
slice, run its verification, and continue only after it passes.

1. Phase 1: Fable safeguard/fallback preflight.
2. Phase 2: Host effort ladder.
3. Phase 3: Typed verification claims.
4. Phase 4: Prompt-injection firewall.
5. Phase 5: Cache-aware prompt layout.
6. Phase 6: Claude-first provider strategy and optional agent backends.
7. Phase 7: Local Fable model pack.
8. Phase 9: Benchmark integrity guards.
9. Phase 10: Command familiarity guard.
10. Phase 8: Hard-tail async worker mode.

The async-worker phase intentionally comes last. It depends on host-risk,
effort, untrusted-content, and evidence-claim contracts.

## Release Gates

Focused gates per phase are listed above. Before merging the whole Fable update
train, run the full quality gate:

```bash
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
uv run pytest tests/ -v
```

If broad tests are too slow during development, use this ladder:

1. New unit tests for the active phase.
2. Existing unit tests for touched modules.
3. Integration tests for review, shadow, benchmark, or CLI surfaces touched by
   the phase.
4. Full quality gate before final merge.

## Success Metrics

Track these over review and route flows:

- Fable calls avoided due likely fallback.
- Actual fallback events observed, with structured category.
- Requested host model versus served host model.
- Median host effort by workflow.
- Fable output tokens per successful review/fix.
- Avoided effort escalations.
- False "verified" claims: target zero in fixtures.
- Verification claims with evidence IDs: target 100 percent where a command or
  runtime check was run.
- Prompt-cache prefix byte-stability.
- Prompt-cache read/write tokens when provider telemetry is available.
- Prompt-injection fixture obedience: target zero.
- Hard-tail async worker activation rate on easy tasks: target zero.
- Host dollars avoided per week, split into delegation, crush, cache, avoided
  fallback waste, and avoided effort escalation.
- Claude subscription/API spend avoided by using MiniMax/OpenRouter execution
  backends for MUSCLE agents.
- MUSCLE-agent jobs by executor provider: MiniMax, OpenRouter, Claude
  subscription, Anthropic API.
- Provider identity confidence and pricing confidence coverage.

## Risks and Mitigations

- Risk: deterministic safeguard classifier over-blocks benign security review.
  Mitigation: reason codes, confidence labels, and user-confirmation path.
- Risk: effort ladder lowers quality on important fixes.
  Mitigation: never allow medium-only completion for high/critical unverified
  fixes.
- Risk: claim auditor creates noisy reports.
  Mitigation: start by auditing only verification/completion language, not every
  sentence.
- Risk: prompt-injection envelope bloats prompts.
  Mitigation: integrate with `crush`, prompt compaction, and stable prefix
  planning.
- Risk: async workers increase token spend on easy tasks.
  Mitigation: default off, deterministic hard-tail triggers, and report skipped
  reasons.
- Risk: provider APIs expose different effort/fallback telemetry fields.
  Mitigation: normalize into MUSCLE metadata and label estimated versus observed.
- Risk: OpenRouter arbitrary model choice breaks identity and pricing
  assumptions.
  Mitigation: preserve gateway provenance, require explicit configured pricing
  for precise savings, and label unknowns instead of silently using a default.
- Risk: Claude-first messaging makes users think MiniMax is deprecated.
  Mitigation: docs and `muscle provider list` should present MiniMax as a
  current low-cost execution backend, not a legacy fallback.
- Risk: provider-specific CLI workflows fragment the product.
  Mitigation: keep provider CLIs behind MUSCLE provider adapters and make
  `muscle` plus the Claude Code plugin the main user-facing workflow.

## First Implementation Slice

Start with Phase 1 only.

Minimal patch set:

- Add `src/muscle/host_risk_preflight.py`.
- Add `tests/unit/test_host_risk_preflight.py`.
- Extend `src/muscle/routing.py` route JSON/data shape with optional host-risk
  metadata while keeping existing fields stable.
- Extend `src/muscle/cli/plumbing.py` route command output.
- Extend `ReviewController._route_review_request()` and
  `_record_delegation_event()` with the preflight metadata.
- Extend `DelegationMetrics` report formatting with Fable-risk counts.
- Update `src/muscle/plugin/commands/route.md`.

First-slice verification:

```bash
uv run pytest tests/unit/test_host_risk_preflight.py tests/unit/test_routing.py -v
uv run pytest tests/unit/test_cost_optimizer.py tests/unit/test_savings_discovery.py -v
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
```

Do not proceed to Phase 2 until the first slice is green.
