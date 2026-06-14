# Scope: MiniMax-M3 Request-Time Thinking Toggle (Tier 1.1)

## Implementation status — IMPLEMENTED (2026-06-03)

Built and shipped (tests + gates green). The open questions below were resolved against MiniMax's primary docs (no live API key was available, so shapes are doc-verified, not probe-verified):

- **Thinking param shapes confirmed:** Anthropic `/v1/messages` → `thinking: {"type": "disabled"|"adaptive"|"enabled"}` ("adaptive" recommended); OpenAI `/v1/chat/completions` → boolean `reasoning_split` (apidog, lower confidence — but the endpoint ignores unknown fields, so it's fail-safe). Implemented in `m27_client._apply_thinking_param`.
- **Default per-stage policy:** `code_review/thinking_policy.py` — analysis stages `adaptive`, formatting/summarization stages `disabled`; `MUSCLE_THINKING_MODE` overrides all. Wired into 22 call sites across 9 review modules.
- **Reasoning-token telemetry:** `TokenUsage.reasoning_tokens` is now parsed from both Anthropic- and OpenAI-shaped usage blocks.
- **Output cap:** model-aware (`MODEL_MAX_OUTPUT_TOKENS`, M3=32768) — *assumption*, M3's true ceiling is still undocumented; confirm before relying on near-cap outputs.
- **Prompt caching:** found to be **automatic/passive** server-side (no `cache_control` needed) — contradicts the earlier deep-research "refuted" verdict. No client code added.

The remaining text below is the original pre-implementation scope, retained for context.

## Summary
- MiniMax-M3 (default model as of the Tier-0 switch) adds a **request-time thinking toggle**: thinking **on** for deep reasoning / agentic / long-horizon work, **off** for low-latency responses. Both modes are billed at the same rate, so this is purely a latency/quality lever — not a cost lever.
- Today MUSCLE cannot control thinking. It treats reasoning output as noise: `_strip_thinking_tags()` deletes `<think>…</think>` ([m27_client.py:78](../../src/muscle/m27_client.py:78)) and a retry loop exists purely to cope with M2.x returning thinking-only responses ([m27_client.py:589-706](../../src/muscle/m27_client.py:589)).
- Goal: thread a per-call `thinking` mode through `chat()` / `chat_structured()` / `chat_streaming()`, drive it from a per-stage policy (mirroring the existing `optimize.context.<stage>` settings), and default each review stage to the mode that fits it.
- Non-goal: this is **not** a cost optimization (same price both modes) and does **not** depend on the 1M context, prompt caching, or native structured output (those are separate tiers).

## Background: current model-call surface
- **Default endpoint is OpenAI-compatible, not Anthropic.** `_detect_api_base()` returns `OPENAI_BASE_URL_IO` (`https://api.minimax.io/v1`) unless `ANTHROPIC_BASE_URL`/`MINIMAX_API_BASE` is set ([m27_client.py:137-148](../../src/muscle/m27_client.py:137)). The client picks the request shape at runtime: `is_openai_compatible = endpoint_base.endswith("/v1")`, and `endpoint_path = "/chat/completions"` vs `"/v1/messages"` ([m27_client.py:591](../../src/muscle/m27_client.py:591)). **The toggle must support both shapes**, because both endpoints are reachable.
- **Single payload builder.** `chat()` builds one `payload` dict ([m27_client.py:574-585](../../src/muscle/m27_client.py:574)) shared by streaming and non-streaming. `chat_structured()` ([m27_client.py:1025](../../src/muscle/m27_client.py:1025)) and `chat_streaming()` ([m27_client.py:803](../../src/muscle/m27_client.py:803)) ultimately go through the same request path, so the param is added in one place.
- **`chat()` signature** today: `chat(messages, system=None, max_tokens=4096, temperature=1.0, stream=False, telemetry_context=None)` ([m27_client.py:534](../../src/muscle/m27_client.py:534)).
- **Reasoning-token telemetry already exists**: external benchmark turns carry a `reasoning_tokens` column (see `insert_external_benchmark_turn(... reasoning_tokens=...)`), so capturing M3's reasoning-token usage has a home already.

## Open questions to resolve BEFORE coding (verify against live MiniMax docs)
These are flagged from the research as unverified and are load-bearing for the param shape:
1. **Exact field name + shape per endpoint.** Research saw `reasoning` / `reasoning_split` with values `Off` / `Adaptive` / `Enabled (+budget_tokens)` on the OpenAI-style API, and an Anthropic-style `thinking: {type, budget_tokens}` on the `/anthropic` path. Confirm the precise JSON for each endpoint (`/chat/completions` vs `/v1/messages`) and whether MiniMax accepts Anthropic's `thinking` object verbatim.
2. **Default mode when the field is omitted.** If M3 defaults to thinking-on, "off" must be sent explicitly for latency-sensitive stages; if it defaults to adaptive, our policy may only need to override the extremes.
3. **Reasoning-token accounting.** Confirm whether reasoning tokens appear in the usage block and count toward the output-token bill (they share M3's flat price, but `max_tokens` budgeting and the 8192 cap interact with them).
4. **Interaction with the thinking-only retry loop.** With thinking explicitly **off**, the `thinking_only_count` rescue path ([m27_client.py:589-706](../../src/muscle/m27_client.py:589)) should rarely trigger; confirm it still behaves when thinking is on.

## Proposed design

### 1. Public interface
- Add an enum-like literal `ThinkingMode = Literal["off", "adaptive", "on"]` (or reuse a small dataclass if budget_tokens is needed) in `m27_client.py`.
- Extend the three entry points with a keyword-only `thinking: ThinkingMode | None = None` (None = "use endpoint/account default", i.e. send nothing — preserves today's behavior):
  - `chat(..., thinking=None)`
  - `chat_structured(..., thinking=None)`
  - `chat_streaming(..., thinking=None)`
- A single private helper `_apply_thinking(payload, thinking, is_openai_compatible)` injects the correct field for the active endpoint shape. All three methods call it; nothing else changes in the request path.

### 2. Per-stage policy (config-driven, mirrors existing pattern)
- The codebase already has stage-keyed optimization settings — `optimize.context.semantic_review` / `optimize.context.fix_generation` consumed in `_build_context_budgeter()` ([cli.py:156-160](../../src/muscle/cli.py:156)), and stage names defined in [optimization/prompt_context.py](../../src/muscle/optimization/prompt_context.py) (`semantic_review`, `fix_generation`, `committee_review`).
- Add a parallel `thinking.<stage>` settings family with sane defaults, resolved once and passed down to each call site. Proposed defaults:

  | Stage | Call site | Default mode | Rationale |
  |---|---|---|---|
  | semantic review | `code_reviewer.chat_structured` ([code_reviewer.py:680](../../src/muscle/code_review/code_reviewer.py:680), [:794](../../src/muscle/code_review/code_reviewer.py:794), [:1278](../../src/muscle/code_review/code_reviewer.py:1278)) | **on** | core reasoning quality |
  | committee review | committee passes via code_reviewer | **on** | multi-pass judgement |
  | verification | `verification_loop.chat` ([verification_loop.py:282](../../src/muscle/code_review/verification_loop.py:282), [:407](../../src/muscle/code_review/verification_loop.py:407)) | **on** | correctness judgement |
  | fix generation | `fix_generator.chat` ([fix_generator.py:204](../../src/muscle/code_review/fix_generator.py:204), [:303](../../src/muscle/code_review/fix_generator.py:303)) | **adaptive** | reasoning helps, latency matters |
  | pattern detection | `pattern_detector.chat` ([pattern_detector.py:263](../../src/muscle/code_review/pattern_detector.py:263), [:403](../../src/muscle/code_review/pattern_detector.py:403)) | **adaptive** | mostly mechanical scan |
  | memory consolidation / handoff / skill / agent gen | `memory_manager`, `handoff_generator`, `skill_generator`, `agent_generator`, `strategy_evolver` | **off** | summarization/formatting, latency-sensitive |
  | generate-fix loop | `code_generator.chat(_streaming)` ([code_generator.py:258](../../src/muscle/code_generator.py:258), [:488](../../src/muscle/code_generator.py:488)) | **on** | iterative code synthesis |

  Note: static analysis (`static_analyzer.py`) makes **no** model call, so it's unaffected.

### 3. Telemetry
- Capture M3's reasoning-token count from the usage block into `TokenUsage` (currently `input_tokens`/`output_tokens` only, [m27_client.py:84](../../src/muscle/m27_client.py:84)) and surface it through the existing `reasoning_tokens` benchmark column so the TUI/benchmark can show thinking-mode impact.

### 4. Simplification opportunity (follow-on, not required)
- With thinking explicitly **off** on deterministic stages, the thinking-only rescue loop ([m27_client.py:589-706](../../src/muscle/m27_client.py:589)) becomes mostly dead weight for those calls. Leave it in place for safety initially; revisit once the toggle is proven.

## Locked decisions
- `thinking=None` means "send no thinking field" → byte-for-byte identical requests to today. The feature is strictly additive and opt-in per stage.
- Do not remove `_strip_thinking_tags()` or the thinking-only retry loop in this pass (defensive; M3 may still emit `<think>` even with a mode set, and the Anthropic-style endpoint differs).
- Keep one payload-injection helper; do not duplicate per-endpoint logic across the three methods.
- No new model call is added for any stage; this only annotates existing calls.

## Risks
- **Wrong param shape → 400s.** The exact field is unverified (open question #1). Mitigation: gate behind verification + an integration test that asserts the payload shape per endpoint; failing-open to "no field" if the model rejects it.
- **Latency/quality regressions** from a mis-tuned default. Mitigation: ship config-overridable defaults; start conservative (only the clear wins: `on` for semantic/committee/verification, leave the rest at endpoint default) and expand after measuring.
- **Reasoning tokens inflating output** against the hardcoded `max_tokens=8192` cap ([m27_client.py:567](../../src/muscle/m27_client.py:567)). Mitigation: confirm accounting (open question #3); raising that cap is tracked separately (Tier 1.2).

## Test plan
- Unit: `_apply_thinking` produces the right field for `is_openai_compatible` True/False across all three modes; `thinking=None` adds nothing.
- Unit: each call site passes the policy-resolved mode (mock `chat`/`chat_structured`, assert kwarg).
- Unit: `TokenUsage` parses reasoning tokens from a sample usage block.
- Integration: payload-shape assertions per endpoint (extend the existing m27_client request tests).

## Effort estimate
- **S–M.** Client plumbing + helper + telemetry: ~half a day. Per-stage policy wiring + config + defaults: ~half a day. Tests: ~half a day. Gated on resolving the 4 open questions first (a short docs-verification spike, ideally a couple of live probe calls against `MiniMax-M3`).

## Suggested phasing
1. **Spike** (blocking): confirm the param shape on both endpoints with live calls; nail down default mode + reasoning-token accounting.
2. **Client**: add `thinking` kwarg + `_apply_thinking` helper + `TokenUsage` reasoning field + unit/integration tests.
3. **Policy**: `thinking.<stage>` settings + resolver + wire the high-confidence stages (semantic, committee, verification = `on`).
4. **Tune**: extend to remaining stages, measure latency/quality, adjust defaults.
