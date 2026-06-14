# Model-Aware Optimization Profiles — Plan 2: Agent-Side Wiring (Opus per-stage thinking/effort)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Opus agent path (`anthropic-api` provider) consume the Opus `ModelProfile.agent` knobs — keep adaptive thinking on for **every** stage and set **per-stage** effort (`xhigh`/`high`/`low`) — while keeping the MiniMax M3 request **byte-identical** to today.

**Architecture:** Thread a new optional `stage` argument from review call sites through `M27Client.chat()`/`chat_structured()` into the `_prepare_payload` provider hook. The base (MiniMax) hook ignores `stage` (no-op → byte-identical). The Opus `AnthropicApiClient._prepare_payload` resolves its own `ModelProfile.agent` (from Plan 1's registry) and uses `stage_effort[stage]` for `output_config.effort`, always emitting `thinking:{type:adaptive}` (never the off-shape). This is the **first plan that changes live behavior** — guarded by an M3 byte-identical golden test.

**Tech Stack:** Python 3.10+, the Plan 1 `model_profiles` registry, `pytest` + `unittest.mock`, `uv run` for all gates.

**Spec:** [2026-06-13-model-aware-optimization-profiles-design.md](2026-06-13-model-aware-optimization-profiles-design.md) §3.1, §3.2. **Depends on Plan 1** (merged: `model_profiles.py`, `canonical_for_label`).

---

## Key facts established by investigation (do not re-discover)

- `M27Client.chat()` builds the payload then calls `self._prepare_payload(payload, is_openai_compatible, thinking=thinking, cache_plan=cache_plan)` at [m27_client.py:777-779](../../src/muscle/m27_client.py). Signature at [m27_client.py:698-712](../../src/muscle/m27_client.py).
- `M27Client.chat_structured()` delegates to `self.chat(...)` at [m27_client.py:1434-1443](../../src/muscle/m27_client.py). Signature at [m27_client.py:1347-1358](../../src/muscle/m27_client.py).
- `M27Client.chat_streaming()` builds its own payload and posts directly — it **never** calls `_prepare_payload` ([m27_client.py:1088-1123](../../src/muscle/m27_client.py)). **Out of scope** for this plan (no review-stage call site uses it; per-stage effort on streaming is a separate, pre-existing gap).
- Base `_prepare_payload` is a no-op at [m27_client.py:655-667](../../src/muscle/m27_client.py). Opus override at [anthropic_client.py:125-150](../../src/muscle/anthropic_client.py) currently derives effort from the thinking **mode** only via `_EFFORT_FOR_THINKING` ([anthropic_client.py:31-36](../../src/muscle/anthropic_client.py)).
- **22 call sites** across 9 files pass `thinking=thinking_for("<stage>")` (see Task 5 for the exact list). Each will additionally pass `stage="<stage>"`.
- Existing tests: [tests/unit/test_anthropic_client.py](../../tests/unit/test_anthropic_client.py) has `TestThinkingEffortMapping` asserting the exact Opus payload (these tests **change** in Task 4). `_posted_payload(mock_session)` helper extracts the posted JSON.

## Two deliberate decisions (flagged for reviewer)

1. **On Opus, thinking is always adaptive — `MUSCLE_THINKING_MODE=disabled` does NOT force thinking off on the Opus path.** Rationale (spec §3.1): with thinking disabled, Opus 4.8 leaks verbose reasoning into the visible (parsed) response, which is a parsing-robustness and quality risk on structured stages. Both modes cost the same on Opus, so keeping thinking on is a pure quality/safety lever. The override remains a MiniMax-path lever. (The Opus client reads `keep_thinking_on_all_stages` from its profile, so this is data-driven, not hardcoded.)
2. **`reasoning_display` mechanism is wired but Opus's value is `None`** (thinking content omitted, the throughput default). The opt-in that sets it to `"summarized"` for audit is a later config knob (out of scope here); Plan 2 only plumbs the profile value through.

---

## File Structure

- **Modify `src/muscle/m27_client.py`** — add `stage: str | None = None` to `chat()` and `chat_structured()`; forward it (to `_prepare_payload` and to the inner `self.chat()` respectively); add `stage` param to the base `_prepare_payload` (ignored).
- **Modify `src/muscle/anthropic_client.py`** — resolve the Opus `AgentBehavior` from the profile registry; rewrite `_prepare_payload` to consume `keep_thinking_on_all_stages` + `stage_effort` + `reasoning_display`; accept `stage`.
- **Modify 9 `src/muscle/code_review/*.py` files** — add `stage="<stage>"` at the 22 call sites.
- **Modify `tests/unit/test_m27_client.py`** — M3 byte-identical golden (stage ignored).
- **Modify `tests/unit/test_anthropic_client.py`** — update `TestThinkingEffortMapping`; add per-stage effort + keep-thinking-on + reasoning_display tests.

---

## Task 1: M3 byte-identical golden (the guard) + base `_prepare_payload` accepts `stage`

**Files:**
- Modify: `src/muscle/m27_client.py` (base `_prepare_payload` signature)
- Test: `tests/unit/test_m27_client.py`

This task adds the `stage` param to the BASE hook (ignored) and locks in that the MiniMax payload is unaffected by it. It changes no MiniMax behavior.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_m27_client.py` (use the file's existing mock-session pattern — find how other tests construct an `M27Client` with a mocked `requests` session and read the posted JSON; mirror it). Add:

```python
class TestStageParamIsMiniMaxNoOp:
    def test_stage_does_not_change_minimax_payload(self, monkeypatch):
        """The new stage arg must be a byte-identical no-op on the MiniMax path."""
        client = _make_minimax_client(monkeypatch)  # mirror existing helper/fixture in this file

        sent: list[dict] = []
        _patch_session_capture(client, sent)  # mirror existing capture pattern

        client.chat([{"role": "user", "content": "hi"}], thinking="adaptive")
        baseline = sent[-1]

        client.chat([{"role": "user", "content": "hi"}], thinking="adaptive", stage="semantic_review")
        with_stage = sent[-1]

        assert with_stage == baseline  # stage must not alter the MiniMax request
        assert "stage" not in with_stage  # never serialized into the payload
```

If `test_m27_client.py` has no reusable client/capture helper, write the two small helpers `_make_minimax_client` and `_patch_session_capture` at the top of this test class by copying the construction + `session.post` mocking pattern already used elsewhere in the file. Do NOT invent a new mocking style.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_m27_client.py -k "TestStageParamIsMiniMaxNoOp" -v`
Expected: FAIL — `TypeError: chat() got an unexpected keyword argument 'stage'`.

- [ ] **Step 3: Add `stage` to the base `_prepare_payload` (ignored) and to `chat()` signature/forwarding**

In `src/muscle/m27_client.py`, change the base `_prepare_payload` ([~655-667](../../src/muscle/m27_client.py)) to accept and ignore `stage`:

```python
    def _prepare_payload(
        self,
        payload: dict[str, Any],
        is_openai_compatible: bool,
        thinking: str | None = None,
        cache_plan: CachePlan | None = None,
        stage: str | None = None,
    ) -> dict[str, Any]:
        """Provider hook: final payload adjustment before POST.

        Base (MiniMax) implementation is a strict no-op — in particular it
        never emits cache_control (MiniMax prefix-caches passively) and ignores
        ``stage`` (per-stage effort is an Opus-only concern).
        """
        return payload
```

Add `stage: str | None = None` to `chat()` ([698-712](../../src/muscle/m27_client.py)) — place it right after `thinking`:

```python
        thinking: str | None = None,
        stage: str | None = None,
```

And forward it at the `_prepare_payload` call ([777-779](../../src/muscle/m27_client.py)):

```python
        payload = self._prepare_payload(
            payload, is_openai_compatible, thinking=thinking, cache_plan=cache_plan, stage=stage
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_m27_client.py -k "TestStageParamIsMiniMaxNoOp" -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

Run: `uv run mypy src/muscle/m27_client.py`, `uv run ruff check src/muscle/m27_client.py tests/unit/test_m27_client.py`, `uv run ruff format --check ...`. Auto-fix and re-run until clean.

```bash
git add src/muscle/m27_client.py tests/unit/test_m27_client.py
git commit -m "feat(m27): add ignored stage param to chat()/_prepare_payload (MiniMax no-op)"
```

---

## Task 2: Thread `stage` through `chat_structured()`

**Files:**
- Modify: `src/muscle/m27_client.py` (`chat_structured`)
- Test: `tests/unit/test_m27_client.py`

- [ ] **Step 1: Write the failing test**

Append to `TestStageParamIsMiniMaxNoOp` in `tests/unit/test_m27_client.py`:

```python
    def test_chat_structured_forwards_stage(self, monkeypatch):
        """chat_structured must accept stage and forward it to chat()."""
        client = _make_minimax_client(monkeypatch)
        seen: dict[str, object] = {}

        def _fake_chat(*args, **kwargs):
            seen["stage"] = kwargs.get("stage")
            return "{}", _zero_usage()  # mirror the file's TokenUsage zero helper

        monkeypatch.setattr(client, "chat", _fake_chat)

        class _Schema(BaseModel):  # use the file's existing pydantic import
            pass

        client.chat_structured(_Schema, [{"role": "user", "content": "hi"}], stage="fix_generation")
        assert seen["stage"] == "fix_generation"
```

Use the file's existing pydantic `BaseModel` import and its TokenUsage construction (look at how other `chat_structured` tests build a fake return); mirror them rather than inventing.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_m27_client.py -k "test_chat_structured_forwards_stage" -v`
Expected: FAIL — `chat_structured() got an unexpected keyword argument 'stage'`.

- [ ] **Step 3: Implement**

In `chat_structured()` ([1347-1358](../../src/muscle/m27_client.py)), add the param after `thinking`:

```python
        thinking: str | None = None,
        stage: str | None = None,
        cache_plan: CachePlan | None = None,
```

And forward it in the inner `self.chat(...)` call ([1434-1443](../../src/muscle/m27_client.py)) — add `stage=stage,` next to `thinking=thinking,`:

```python
            response_text, usage = self.chat(
                messages=working_messages,
                system=system_with_schema,
                max_tokens=max_tokens,
                temperature=0.1,
                telemetry_context=telemetry_context,
                thinking=thinking,
                stage=stage,
                _metadata_sink=call_meta,
                cache_plan=cache_plan,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_m27_client.py -k "TestStageParamIsMiniMaxNoOp" -v`
Expected: PASS (both tests).

- [ ] **Step 5: Gates + commit**

Run mypy/ruff on `src/muscle/m27_client.py` + the test file; auto-fix.

```bash
git add src/muscle/m27_client.py tests/unit/test_m27_client.py
git commit -m "feat(m27): thread stage through chat_structured to chat"
```

---

## Task 3: Opus `_prepare_payload` consumes the Opus `AgentBehavior`

**Files:**
- Modify: `src/muscle/anthropic_client.py`
- Test: `tests/unit/test_anthropic_client.py`

This is the **behavior change**. After this task, the Opus path keeps thinking adaptive on every stage and sets effort from the profile's `stage_effort` (defaulting to `default_effort` when `stage` is None).

- [ ] **Step 1: Update the existing tests to the new contract + add per-stage tests**

In `tests/unit/test_anthropic_client.py`, the `TestThinkingEffortMapping` class currently asserts the OLD behavior. Replace that class body with the new contract:

```python
class TestThinkingEffortMapping:
    def test_adaptive_no_stage_keeps_thinking_and_default_high_effort(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking="adaptive")
        payload = _posted_payload(mock_session)
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "high"}  # Opus default_effort

    def test_disabled_mode_still_keeps_thinking_on_opus(self, mock_client):
        # On Opus, keep_thinking_on_all_stages=True overrides a 'disabled' mode:
        # thinking stays adaptive (avoids the verbose-reasoning leak).
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking="disabled")
        payload = _posted_payload(mock_session)
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "high"}  # no stage -> default_effort

    def test_none_thinking_keeps_thinking_on_opus(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking=None)
        payload = _posted_payload(mock_session)
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["output_config"] == {"effort": "high"}


class TestPerStageEffort:
    def test_coding_stages_use_xhigh(self, mock_client):
        client, mock_session = mock_client
        for stage in ("semantic_review", "committee_review", "fix_generation"):
            client.chat([{"role": "user", "content": "hi"}], thinking="adaptive", stage=stage)
            payload = _posted_payload(mock_session)
            assert payload["output_config"] == {"effort": "xhigh"}, stage
            assert payload["thinking"] == {"type": "adaptive"}, stage

    def test_verification_and_pattern_use_high(self, mock_client):
        client, mock_session = mock_client
        for stage in ("verification", "pattern_detection"):
            client.chat([{"role": "user", "content": "hi"}], thinking="adaptive", stage=stage)
            payload = _posted_payload(mock_session)
            assert payload["output_config"] == {"effort": "high"}, stage

    def test_formatting_stages_use_low_with_thinking_on(self, mock_client):
        client, mock_session = mock_client
        for stage in (
            "memory_consolidation",
            "handoff_generation",
            "skill_generation",
            "agent_generation",
            "strategy_evolution",
        ):
            client.chat([{"role": "user", "content": "hi"}], thinking="disabled", stage=stage)
            payload = _posted_payload(mock_session)
            assert payload["output_config"] == {"effort": "low"}, stage
            assert payload["thinking"] == {"type": "adaptive"}, stage  # never omitted on Opus

    def test_unknown_stage_falls_back_to_default_effort(self, mock_client):
        client, mock_session = mock_client
        client.chat([{"role": "user", "content": "hi"}], thinking="adaptive", stage="nonexistent_stage")
        payload = _posted_payload(mock_session)
        assert payload["output_config"] == {"effort": "high"}  # Opus default_effort
```

(Keep the existing `TestSamplingParamStrip` and cache-breakpoint tests unchanged — Task 3 must not regress sampling-param stripping or cache logic.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_anthropic_client.py -k "TestThinkingEffortMapping or TestPerStageEffort" -v`
Expected: FAIL (old `_prepare_payload` omits thinking for disabled and ignores stage).

- [ ] **Step 3: Implement — resolve the Opus AgentBehavior and use it**

In `src/muscle/anthropic_client.py`:

(a) Resolve the agent behavior in `__init__` (after the `super().__init__(...)` call). Add the imports at the top of the file:

```python
from .model_identity import canonical_for_label
from .model_profiles import profile_for
```

(If importing these at module top triggers an import cycle when running the tests, move both imports inside `__init__` as local imports — the Plan 1 modules use lazy imports for exactly this reason.)

At the end of `__init__`:

```python
        # This client is Opus-only, so its profile is always the Opus profile.
        # Resolving via the registry keeps per-stage effort/thinking knobs in one
        # place (model_profiles) rather than hardcoded here.
        self._agent_behavior = profile_for(canonical_for_label(self.model)).agent
```

(b) Rewrite `_prepare_payload` ([125-150](../../src/muscle/anthropic_client.py)) to accept `stage` and consume the behavior:

```python
    def _prepare_payload(
        self,
        payload: dict[str, Any],
        is_openai_compatible: bool,
        thinking: str | None = None,
        cache_plan: CachePlan | None = None,
        stage: str | None = None,
    ) -> dict[str, Any]:
        """Adapt the MiniMax-shaped payload to the Opus 4.8 request contract.

        Per-stage effort and always-on thinking come from this model's
        ``ModelProfile.agent`` (the Opus profile). ``thinking`` (the resolved
        MiniMax mode) is intentionally NOT used to gate thinking on Opus: with
        thinking disabled, Opus 4.8 leaks verbose reasoning into the visible
        response, so ``keep_thinking_on_all_stages`` keeps it adaptive and
        expresses the per-stage difference through effort instead.
        """
        # Opus 4.8 returns 400 on sampling params — never send them.
        for param in ("temperature", "top_p", "top_k"):
            payload.pop(param, None)

        behavior = self._agent_behavior
        if behavior.keep_thinking_on_all_stages:
            think_block: dict[str, str] = {"type": "adaptive"}
            if behavior.reasoning_display is not None:
                think_block["display"] = behavior.reasoning_display
            payload["thinking"] = think_block
            effort = (
                behavior.stage_effort.get(stage, behavior.default_effort)
                if stage is not None
                else behavior.default_effort
            )
        else:
            # Defensive fallback for a hypothetical non-keep-on profile: mode-based,
            # mirroring the pre-profile behavior.
            mode = str(thinking).strip().lower() if thinking is not None else None
            if mode in ("adaptive", "enabled"):
                payload["thinking"] = {"type": "adaptive"}
            else:
                payload.pop("thinking", None)
            effort = _EFFORT_FOR_THINKING.get(mode, "medium")
        payload["output_config"] = {"effort": effort}

        # Write-amortization rule: a cache write only pays off when at least
        # one more call is expected to reuse the prefix within the TTL.
        if cache_plan is not None and cache_plan.expected_reuse >= 1:
            self._insert_cache_breakpoint(payload, cache_plan)
        return payload
```

Keep `_EFFORT_FOR_THINKING` (used by the defensive fallback). Keep `_insert_cache_breakpoint` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_anthropic_client.py -v`
Expected: PASS (the updated mapping tests, the new per-stage tests, AND the unchanged sampling-strip + cache tests).

- [ ] **Step 5: Gates + commit**

Run mypy/ruff/format on `src/muscle/anthropic_client.py` + the test file; auto-fix.

```bash
git add src/muscle/anthropic_client.py tests/unit/test_anthropic_client.py
git commit -m "feat(anthropic): per-stage effort + always-on thinking from the Opus profile"
```

---

## Task 4: Verify the M3 golden still holds end-to-end

**Files:** none (verification) — or a small assertion if missing.

- [ ] **Step 1: Confirm the MiniMax path is unchanged**

Run: `uv run pytest tests/unit/test_m27_client.py -k "TestStageParamIsMiniMaxNoOp" -v`
Expected: PASS — the MiniMax payload is byte-identical with/without `stage` (base `_prepare_payload` ignores it; Task 3 only touched the Opus subclass).

- [ ] **Step 2: Confirm Opus and MiniMax are isolated**

Run: `uv run pytest tests/unit/test_anthropic_client.py tests/unit/test_m27_client.py -v`
Expected: PASS — Opus behavior changed, MiniMax behavior unchanged.

(No commit unless a gap is found that needs an added assertion.)

---

## Task 5: Thread `stage="<stage>"` into all 22 review call sites

**Files (modify each; match on the `thinking=thinking_for("X")` line, not line numbers, which will drift):**

| File | Stage string | Sites |
|---|---|---|
| `src/muscle/code_review/code_reviewer.py` | `semantic_review` | 4 |
| `src/muscle/code_review/memory_manager.py` | `memory_consolidation` | 4 |
| `src/muscle/code_review/agent_generator.py` | `agent_generation` | 2 |
| `src/muscle/code_review/handoff_generator.py` | `handoff_generation` | 2 |
| `src/muscle/code_review/pattern_detector.py` | `pattern_detection` | 2 |
| `src/muscle/code_review/fix_generator.py` | `fix_generation` | 2 |
| `src/muscle/code_review/strategy_evolver.py` | `strategy_evolution` | 3 |
| `src/muscle/code_review/skill_generator.py` | `skill_generation` | 1 |
| `src/muscle/code_review/verification_loop.py` | `verification` | 2 |

For **every** occurrence of `thinking=thinking_for("<STAGE>"),`, add a sibling line `stage="<STAGE>",` immediately after it. The stage string is always identical to the `thinking_for(...)` argument. Example (code_reviewer.py):

```python
                thinking=thinking_for("semantic_review"),
                stage="semantic_review",
```

> **Note (no-op for now, correct later):** `committee_review` exists in the Opus profile's `stage_effort` but has no `thinking_for("committee_review")` call site — committee review currently routes through the `semantic_review` path. Do NOT invent a call site for it; leave the profile entry as forward-looking. If you find `committee_reviewer.py` calls `chat`/`chat_structured` with a `thinking_for` of its own, thread its real stage; otherwise leave it.

- [ ] **Step 1: Find every site (don't trust the table's line numbers)**

Run: `grep -rn 'thinking=thinking_for(' src/muscle/code_review --include='*.py'`
Confirm 22 matches across the 9 files above.

- [ ] **Step 2: Add `stage="<stage>"` at each site**

Edit each occurrence as shown. The `stage` value must equal the `thinking_for(...)` argument at that site. (Do this carefully per file; re-run the grep after to confirm counts.)

- [ ] **Step 3: Add a thread-through regression test**

In `tests/unit/test_anthropic_client.py` (or a focused test in `tests/unit/test_code_reviewer.py` if that's where the integration fixtures live), add one test that drives a real review stage through the Opus client and asserts the effort reflects the stage. If `code_reviewer` is hard to unit-test in isolation, instead add this lighter assertion to `test_anthropic_client.py` proving the resolved Opus profile drives effort (already covered by Task 3's `TestPerStageEffort`), and rely on the existing `code_reviewer` integration tests to exercise the call-site change. Document which you chose in the commit.

- [ ] **Step 4: Run the affected test suites**

Run: `uv run pytest tests/unit/test_code_reviewer.py tests/unit/test_anthropic_client.py tests/unit/test_m27_client.py -q`
Expected: PASS. If any `code_reviewer`/`fix_generator`/etc. test constructs calls and asserts kwargs, update those assertions to include `stage=`.

- [ ] **Step 5: Gates + commit**

Run: `uv run mypy src/muscle/code_review/`, `uv run ruff check src/muscle/code_review/`, `uv run ruff format --check src/muscle/code_review/`. Auto-fix.

```bash
git add src/muscle/code_review/ tests/unit/
git commit -m "feat(review): pass stage to chat/chat_structured so the Opus path sets per-stage effort"
```

---

## Task 6: Full gate sweep

**Files:** none (verification).

- [ ] **Step 1: Full type/lint/format**

Run:
```bash
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
```
Expected: clean (auto-fix + re-run if needed).

- [ ] **Step 2: Full suite (background, ~1–3.5 min)**

Run: `uv run pytest tests/ -q` (background per project memory).
Expected: PASS — no regressions. The only intended behavior change is the Opus request shape (per-stage effort + always-on thinking); MiniMax is byte-identical.

- [ ] **Step 3: Commit any straggler auto-fixes**

```bash
git add -A && git commit -m "chore(model-profiles): Plan 2 gate sweep" # only if auto-fixes were applied
```

---

## Self-Review (completed by plan author)

**Spec coverage (Plan 2 scope = §3.1, §3.2):**
- ✅ §3.1 never emit the off-shape; keep adaptive thinking on every stage — Task 3 (`keep_thinking_on_all_stages`).
- ✅ §3.1 formatting stages → `low` effort — Task 3 + Task 5 (formatting stages map to `low` in the Opus profile, reached once `stage` is threaded).
- ✅ §3.2 `xhigh` for coding stages (`semantic_review`/`committee_review`/`fix_generation`), `high` for `verification`/`pattern_detection` — Task 3 tests + the Opus profile's `stage_effort`.
- ✅ §3.2 `reasoning_display` plumbed from the profile (Opus value `None`; opt-in deferred) — Task 3.
- ✅ M3 byte-identical guarantee — Task 1 golden + Task 4 re-verify.
- ✅ Profile is the single source of truth (client reads `profile_for(...).agent`, no hardcoded effort table except the defensive fallback) — Task 3.

**Placeholder scan:** Task 1/2 reference "mirror the existing helper/fixture in this file" for the M27 test mocks because the exact fixture name in `test_m27_client.py` must match what's already there — the implementer reads the file and reuses the established pattern (this is reuse guidance, not a placeholder for missing logic). Task 5 Step 3 offers a concrete either/or with a documented choice. No `TBD`/`TODO` in shipped code.

**Type consistency:** `stage: str | None` is consistent across `chat`/`chat_structured`/base `_prepare_payload`/Opus `_prepare_payload`. `self._agent_behavior` is an `AgentBehavior` (from Plan 1). `stage_effort.get(stage, default_effort)` matches the `Mapping[str, str]` type.

**Risk notes for the reviewer:**
- The behavior change is confined to the Opus (`anthropic-api`) provider, which is a niche premium path. The default MiniMax path is provably unchanged (Task 1 golden).
- Existing `TestThinkingEffortMapping` assertions are intentionally rewritten (Task 3) — that's the documented §3.1 change, not a regression.
- `chat_streaming` is out of scope (doesn't reach `_prepare_payload`); if a future streaming review stage needs per-stage effort, that's a separate change.

---

## Decisions surfaced for your review (before execution)

1. **Opus ignores `MUSCLE_THINKING_MODE=disabled`** (thinking stays on) — see "Two deliberate decisions" above. If you'd rather the explicit override still force thinking off on Opus (accepting the reasoning-leak risk), say so and I'll adjust Task 3.
2. **`stage` is passed redundantly alongside `thinking=thinking_for("X")`** at each call site (both name the stage). The cleaner-looking alternative — pass only `stage="X"` and resolve `thinking` inside the client — was rejected because it would move thinking-mode resolution off the call sites and risk the M3 byte-identical guarantee. The small redundancy buys a provably-unchanged MiniMax path. Flag if you'd prefer the refactor.
