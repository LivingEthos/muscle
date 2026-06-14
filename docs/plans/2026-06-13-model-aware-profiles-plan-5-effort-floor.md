# Model-Aware Optimization Profiles — Plan 5: Host Synthesis Effort Floor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the host synthesis-effort floor from `medium` to `high` when the resolved **host** profile sets a higher floor (Opus 4.8 and Fable 5 both set `HIGH`), while leaving the unknown/default host at `medium` (today's behavior). `decide_host_effort` gains a `synthesis_effort_floor` knob; `routing.py` resolves the host profile and passes it.

**Architecture:** `decide_host_effort` (host_effort_policy.py) gets a keyword-only `synthesis_effort_floor: HostEffortLevel = MEDIUM`, applied as a floor right after the default so the existing evidence escalations and the budget/time caps still compose. A defensive `resolve_host_synthesis_floor(project_path)` (model_profiles.py) resolves only the host profile's floor (`MEDIUM` on any failure). `routing.py` threads the project path/scope to that resolver at its single `decide_host_effort` call site. Default = `MEDIUM` = byte-identical to today.

**Tech Stack:** Python 3.10+, Plan 1 `model_profiles` (`HostModelResolver`, `profile_for`, `HostBehavior.synthesis_effort_floor`), `pytest`, `uv run`.

**Spec:** [design §4 wiring row, §6 floor, §8 P6, §2.4](2026-06-13-model-aware-optimization-profiles-design.md). Build phase **P6**. **Depends on Plan 1**. Independent of Plans 2/3/4.

---

## Decisions (settled)

1. **Host-driven (correct by definition).** `synthesis_effort_floor` is a `HostBehavior` knob describing the **host's own** synthesis/arbitration effort — there is no host-vs-agent ambiguity here. It is resolved from the resolved host profile.
2. **Data-driven, not Opus-only.** Both the Opus (`model_profiles.py:199`) and Fable (`:225`) host profiles set `synthesis_effort_floor=HIGH`; `default`/M3 leave it `MEDIUM`. So the floor rises to `high` for **any premium host** (Opus or Fable) and stays `medium` for unknown/default. This is the whole point of the profile system — the wiring reads whatever the resolved host's profile declares. The P6 guard ("floor med→high only for the premium host; medium for unknown") is asserted via tests for both `opus` and the unknown case.
3. **The floor is a floor, not a ceiling.** It only ever *raises* the baseline; evidence escalations (architectural, verification failures, benchmark) still push higher via `_max_effort`, and the existing token/time budget caps still apply as hard constraints (a tiny `token_budget` can still pull effort below the floor — physical limit, acceptable and pre-existing).
4. **Two existing routing tests become host-deterministic.** `test_routing.py` `:220` and `:252` assert `host_effort.effort == "medium"` from the CLI `route` command but do **not** isolate the host environment. Once routing is host-aware it reads `MUSCLE_HOST_MODEL` / `~/.claude/settings.json`; on a dev box whose `~/.claude/settings.json` has `"model": "opus[...]"` (canonicalizes to Opus) those tests would otherwise flip to `high`. Plan 5 updates exactly those two tests to **isolate the host** (empty `HOME` + unset `MUSCLE_HOST_MODEL`) so they deterministically resolve the default host and keep asserting `medium`. This is determinism hardening (the feature invalidated their implicit env assumption), **not** weakening — they still assert `medium`.

---

## Key facts established by investigation (do not re-discover)

**`src/muscle/host_effort_policy.py`:**
- `HostEffortLevel(str, Enum)`: `MEDIUM`,`HIGH`,`XHIGH`,`MAX` ([:18-24]); `_ORDER` tuple ([:52-57]); `_max_effort(left, right)` ([:187-188]) returns the higher.
- `decide_host_effort(*, route_tier, target_type="unknown", target_size=0, verification_failure_count=0, high_critical_issue_count=0, task_novelty=False, fallback_risk=False, benchmark_mode=False, explicit_user_maximum_effort=False, time_budget_seconds=None, token_budget=None) -> HostEffortDecision` ([:67-171]). Body starts `effort = HostEffortLevel.MEDIUM` / `reasons = ["default medium for routine host synthesis"]` / `must_not_downgrade = False` ([:99-101]). All escalations use `effort = _max_effort(effort, ...)`. Budget/time caps at [:142-156]. `retry_ladder` derived from final `effort` ([:158]).
- Sole caller in src: `routing.py:427`.

**`src/muscle/model_profiles.py`:**
- Already imports `from .host_effort_policy import HostEffortLevel` ([:24]). Has `profile_for(canonical_key) -> ModelProfile`, `logger`, `from pathlib import Path`, `PROFILES`, `DEFAULT_PROFILE_KEY`. `ModelProfile.host.synthesis_effort_floor: HostEffortLevel`.
- `resolve_active_profiles` lazily imports `HostModelResolver`; `HostModelResolver().resolve(project_path) -> ModelIdentity` (`.canonical_model_key`). Resolving only the host avoids agent/provider work.

**`src/muscle/routing.py`:**
- `_host_effort_from_features(decision: RouteDecision, features: dict[str, str]) -> HostEffortDecision` ([:422-441]) is the **only** `decide_host_effort` call site.
- `_with_route_metadata(decision, features) -> RouteDecision` ([:413-419]) calls `_host_effort_from_features(decision, features)`.
- `Router.route(self, task_description, scope: Path | None = None)` calls `_with_route_metadata(decision, features)` at **two** sites ([:154] cached path, [:158] fresh path) and has `scope` in hand.
- `_offline_route(task_description, profile)` calls `_with_route_metadata(RouteDecision(...), features)` at several branch sites and has **no** scope (host resolves via env/home only — acceptable for the offline fallback).
- routing.py does NOT currently import `model_profiles`; `model_profiles` does NOT import `routing` (no cycle). Use a lazy in-function import to match the repo pattern.

**Tests:**
- `tests/unit/test_host_effort_policy.py`: direct `decide_host_effort` unit tests (e.g. `test_routine_task_defaults_to_medium`). These call `decide_host_effort` directly (no host resolution) → unaffected (floor defaults `MEDIUM`).
- `tests/unit/test_routing.py`: ONLY `:220` and `:252` assert `host_effort...== "medium"` (both CLI `route` tests). All `TestOfflineRoute` host_effort assertions are `high`/`xhigh` (evidence-driven) — a `HIGH` floor never lowers them, so they pass regardless of the dev's host env. Full-suite grep confirms no other test asserts `host_effort == medium`.
- `tests/unit/test_model_profiles.py` already imports `HostEffortLevel` ([:5]).
- Confirmed on this dev box: `~/.claude/settings.json` `model` = `opus[1m]` → `canonical_for_host_label("opus[1m]")` = the Opus key. So without isolation, `:220`/`:252` WOULD break here.

---

## File Structure

- **Modify `src/muscle/host_effort_policy.py`** — add `synthesis_effort_floor` param + floor application.
- **Modify `src/muscle/model_profiles.py`** — add `resolve_host_synthesis_floor(project_path)` defensive helper.
- **Modify `src/muscle/routing.py`** — thread `project_path` (from `scope`) into `_with_route_metadata`/`_host_effort_from_features`; resolve + pass the floor.
- **Tests** — `test_host_effort_policy.py`, `test_model_profiles.py`, `test_routing.py`.

---

## Task 1: `decide_host_effort` synthesis-effort floor

**Files:**
- Modify: `src/muscle/host_effort_policy.py`
- Test: `tests/unit/test_host_effort_policy.py`

- [ ] **Step 1: Write tests first**

In `tests/unit/test_host_effort_policy.py` (imports already at top: `HostEffortLevel, decide_host_effort, host_effort_metadata`). Append:

```python
def test_synthesis_floor_raises_routine_medium_to_high() -> None:
    decision = decide_host_effort(
        route_tier="mechanical",
        target_type="file",
        synthesis_effort_floor=HostEffortLevel.HIGH,
    )
    assert decision.effort == HostEffortLevel.HIGH
    assert decision.retry_ladder[0] == HostEffortLevel.HIGH
    assert "host synthesis effort floor high" in decision.rationale


def test_synthesis_floor_default_medium_is_noop() -> None:
    floored = decide_host_effort(
        route_tier="mechanical",
        target_type="file",
        synthesis_effort_floor=HostEffortLevel.MEDIUM,
    )
    baseline = decide_host_effort(route_tier="mechanical", target_type="file")
    assert floored.effort == HostEffortLevel.MEDIUM
    assert floored.to_dict() == baseline.to_dict()


def test_synthesis_floor_does_not_lower_higher_evidence_effort() -> None:
    # Evidence already pushes xhigh; a HIGH floor must not pull it down.
    decision = decide_host_effort(
        route_tier="mechanical",
        verification_failure_count=2,
        synthesis_effort_floor=HostEffortLevel.HIGH,
    )
    assert decision.effort == HostEffortLevel.XHIGH
```

Run: `uv run pytest tests/unit/test_host_effort_policy.py -k "synthesis_floor" -v` → FAIL (`synthesis_effort_floor` kwarg unknown).

- [ ] **Step 2: Implement**

In `decide_host_effort`, add the keyword-only param to the signature (after `token_budget`):

```python
    token_budget: int | None = None,
    synthesis_effort_floor: HostEffortLevel = HostEffortLevel.MEDIUM,
) -> HostEffortDecision:
```

Add a one-line doc entry under Args (after the `token_budget:` line):

```python
        synthesis_effort_floor: Minimum effort for intelligence-sensitive host
            synthesis, from the resolved host profile (raises the baseline only).
```

Apply the floor immediately after the initial `effort`/`reasons`/`must_not_downgrade` setup (after `must_not_downgrade = False`, ~line 101):

```python
    floored = _max_effort(effort, synthesis_effort_floor)
    if floored != effort:
        effort = floored
        reasons.append(f"host synthesis effort floor {synthesis_effort_floor.value}")
```

(Placed before the evidence escalations so they still compose via `_max_effort`; the budget/time caps near the end still apply as hard constraints.)

Run: `uv run pytest tests/unit/test_host_effort_policy.py -v` → PASS (all, incl. the pre-existing tests, which omit `synthesis_effort_floor` → `MEDIUM` → unchanged).

- [ ] **Step 3: Gates + commit**

```
uv run ruff check src/muscle/host_effort_policy.py tests/unit/test_host_effort_policy.py
uv run ruff format src/muscle/host_effort_policy.py tests/unit/test_host_effort_policy.py
uv run mypy src/muscle/host_effort_policy.py
```

```bash
git add src/muscle/host_effort_policy.py tests/unit/test_host_effort_policy.py
git commit -m "feat(effort): decide_host_effort honors a synthesis_effort_floor (default medium = no-op)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Resolve the host floor + wire `routing.py`

**Files:**
- Modify: `src/muscle/model_profiles.py`, `src/muscle/routing.py`
- Test: `tests/unit/test_model_profiles.py`, `tests/unit/test_routing.py`

- [ ] **Step 1: Add `resolve_host_synthesis_floor` (test first)**

In `tests/unit/test_model_profiles.py` (add `resolve_host_synthesis_floor` to the top import block from `muscle.model_profiles`; `HostEffortLevel` is already imported from `muscle.host_effort_policy`). Append:

```python
def test_resolve_host_synthesis_floor_opus(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    assert resolve_host_synthesis_floor(tmp_path) == HostEffortLevel.HIGH


def test_resolve_host_synthesis_floor_unknown_is_medium(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    assert resolve_host_synthesis_floor(tmp_path) == HostEffortLevel.MEDIUM
```

Run → FAIL. Implement in `model_profiles.py` (near `resolve_active_profiles`):

```python
def resolve_host_synthesis_floor(project_path: Path | str | None) -> HostEffortLevel:
    """Resolve the active HOST profile's synthesis effort floor, defensively.

    Resolves only the host (no agent/provider work) and returns the conservative
    default floor (``MEDIUM``) on any resolution failure, so routing never breaks
    on profile-resolution edge cases. Mirrors resolve_host_fragment_keys.
    """
    try:
        from .host_model_resolver import HostModelResolver

        resolved = Path(project_path) if project_path is not None else None
        host_identity = HostModelResolver().resolve(resolved)
        return profile_for(host_identity.canonical_model_key).host.synthesis_effort_floor
    except Exception:
        logger.debug("resolve_host_synthesis_floor failed; using MEDIUM", exc_info=True)
        return HostEffortLevel.MEDIUM
```

Run: `uv run pytest tests/unit/test_model_profiles.py -k "synthesis_floor" -v` → PASS.

- [ ] **Step 2: Thread the floor into `routing.py`**

Add `project_path: Path | None = None` to both helpers and resolve+pass the floor at the single `decide_host_effort` call:

```python
def _with_route_metadata(
    decision: RouteDecision,
    features: dict[str, str],
    project_path: Path | None = None,
) -> RouteDecision:
    decision.host_effort = _host_effort_from_features(decision, features, project_path)
    decision.provider_metadata = _provider_route_metadata(decision, features)
    return decision


def _host_effort_from_features(
    decision: RouteDecision,
    features: dict[str, str],
    project_path: Path | None = None,
) -> HostEffortDecision:
    from .model_profiles import resolve_host_synthesis_floor

    fallback_risk = bool(decision.host_risk and decision.host_risk.likely_fallback)
    return decide_host_effort(
        route_tier=decision.tier.value,
        target_type=features.get("target_type", "unknown"),
        target_size=_int_feature(features, "target_size", "line_count", "file_count"),
        verification_failure_count=_int_feature(features, "verification_failure_count"),
        high_critical_issue_count=_high_critical_issue_count(features),
        task_novelty=_bool_feature(features.get("task_novelty")),
        fallback_risk=fallback_risk,
        benchmark_mode=_bool_feature(features.get("benchmark_mode"))
        or _bool_feature(features.get("benchmark_run")),
        explicit_user_maximum_effort=features.get("effort", "").lower()
        in {"max", "maximum", "xhigh"},
        time_budget_seconds=_optional_int_feature(features.get("time_budget_seconds")),
        token_budget=_optional_int_feature(features.get("token_budget")),
        synthesis_effort_floor=resolve_host_synthesis_floor(project_path),
    )
```

In `Router.route`, pass `scope` to **both** `_with_route_metadata` calls ([:154] and [:158]):

```python
            return _with_route_metadata(decision, features, scope)
```
```python
        decision = _with_route_metadata(decision, features, scope)
```

Leave the `_offline_route` `_with_route_metadata(...)` calls unchanged (they default `project_path=None`; the offline fallback resolves the host via env/home settings only, which is acceptable — and is exactly what the new offline-route tests below assert).

- [ ] **Step 3: Make the two env-dependent routing tests deterministic + add floor tests**

In `tests/unit/test_routing.py`:

(a) **`:220` and `:252`** — these CLI `route` tests assert `host_effort...== "medium"`. Add host isolation so they resolve the default host regardless of the dev's `~/.claude/settings.json`. Add `monkeypatch` (and `tmp_path` if not present) to each test's signature and, at the **start** of each test body (before the `runner.invoke`/`patch.dict`), add:

```python
        monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
```

Keep the `== "medium"` assertions unchanged. (Read each test first; `patch.dict("os.environ", ..., clear=False)` preserves the monkeypatched `HOME`, so isolation holds. If a test already takes `monkeypatch`/`tmp_path`, reuse them.) Do NOT change any other assertion in these tests.

(b) Append two new tests that lock the P6 guard via the pure `offline_route` API (no CLI/mock needed). `offline_route` is already imported at the top of the file:

```python
class TestHostSynthesisFloor:
    def test_opus_host_raises_routine_floor_to_high(self, monkeypatch) -> None:
        monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
        decision = offline_route("rename a variable across files")
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "high"

    def test_unknown_host_keeps_routine_floor_medium(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        decision = offline_route("rename a variable across files")
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "medium"
```

(`"rename a variable across files"` routes mechanical/reasoning → base effort `medium`; the opus host floor raises it to `high`, the unknown host leaves it `medium`. This matches the existing `test_default_review_returns_m27` routing of the same string.)

Run: `uv run pytest tests/unit/test_routing.py tests/unit/test_model_profiles.py -v` → PASS. Then sanity-check the broader host-effort/routing surface:
`uv run pytest tests/unit/test_host_effort_policy.py tests/unit/test_delegation_metrics.py tests/unit/test_review_controller.py -q` → PASS (these assert host_effort structure or `high`/`xhigh`, never `medium`, so the floor doesn't disturb them).

- [ ] **Step 4: Gates + commit**

```
uv run ruff check src/muscle/model_profiles.py src/muscle/routing.py tests/unit/test_model_profiles.py tests/unit/test_routing.py
uv run ruff format src/muscle/model_profiles.py src/muscle/routing.py tests/unit/test_model_profiles.py tests/unit/test_routing.py
uv run mypy src/muscle/model_profiles.py src/muscle/routing.py
```

```bash
git add src/muscle/model_profiles.py src/muscle/routing.py tests/unit/test_model_profiles.py tests/unit/test_routing.py
git commit -m "feat(effort): routing raises host synthesis floor from the resolved host profile (premium host -> high)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Full gate sweep

- [ ] **Step 1: Type/lint/format**

```bash
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
```
Auto-fix + re-run until clean.

- [ ] **Step 2: Full suite (background, ~1–5 min)**

Run: `uv run pytest tests/ -q` (background). Expected: PASS (baseline 3038 passed / 3 skipped after Plan 4; Plan 5 adds ~7 tests). Intended change: the `route`/`offline_route` host-effort floor is `high` when a premium host (Opus/Fable) is resolved; `medium` otherwise. The two CLI route tests now isolate the host and still assert `medium`.

- [ ] **Step 3: Commit any straggler auto-fixes** (only if needed)

```bash
git add -A && git commit -m "chore(effort): Plan 5 gate sweep

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

**Spec coverage (Plan 5 scope = §6 floor / §4 wiring row / §8 P6):**
- ✅ `decide_host_effort` accepts the floor; raises baseline only — Task 1.
- ✅ `routing` passes the resolved host profile's floor — Task 2.
- ✅ Floor med→high for premium host (Opus + Fable), medium for unknown — Task 2 tests (`TestHostSynthesisFloor`).
- ✅ No-op guarantee: default floor `MEDIUM` is byte-identical (`test_synthesis_floor_default_medium_is_noop` asserts `to_dict()` equality); unknown host → `MEDIUM`.

**Type/consistency:** `synthesis_effort_floor: HostEffortLevel = HostEffortLevel.MEDIUM` (keyword-only) on `decide_host_effort`; `resolve_host_synthesis_floor(project_path) -> HostEffortLevel`; `project_path: Path | None = None` added to `_with_route_metadata`/`_host_effort_from_features`. `Router.route` passes `scope`; `_offline_route` defaults `None`.

**Risk notes:**
- Floor is host-driven and data-driven (Opus + Fable both `HIGH`); resolution is fully defensive (`MEDIUM` on failure), so routing never breaks.
- The only behavior change for the default/unknown host is **none** (floor `MEDIUM`). The premium-host change (floor `high`) is the intended P6 behavior.
- `test_routing.py:220`/`:252` are updated for host-determinism (isolate `HOME` + unset `MUSCLE_HOST_MODEL`); they still assert `medium`. This is required because the feature makes routing read `~/.claude/settings.json` (which on this dev box selects Opus). All other host-effort assertions in the suite are `high`/`xhigh`/structure and are unaffected by a raised floor.
- Budget/time caps remain hard constraints and can still pull effort below the floor (pre-existing, physical) — out of scope to change.
