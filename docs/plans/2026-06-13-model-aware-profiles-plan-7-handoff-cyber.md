# Model-Aware Optimization Profiles — Plan 7: Handoff Completeness + Cyber-Safeguard Docs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The final, lowest-risk phase. (1) Make `handoff_generator` emit **complete, self-contained delegation specs** — add a plan-level Delegation Spec section (absolute scope path + the `muscle` invocation + acceptance criteria + session-resume + review mode) and recover the `fix_approach` / `risks` / `context_needed` fields the M3 prompt already produces but currently discards. (2) Surface the **cyber-safeguard friction** note in `muscle provider show`, data-driven from the shown provider's model profile (`SecurityPosture.cyber_safeguard_friction` — its first consumer).

**Architecture:** Both changes are additive text/doc improvements. The handoff change is **unconditional** (there is no profile boolean for handoff completeness; the spec attributes it to "Opus host posture" but the improvement is universal — every recipient benefits from a complete spec). The provider-show note is **data-driven**: it reads `profile_for(canonical_for_label(provider.model)).security.cyber_safeguard_friction` and prints a warning only when the shown provider's model flags friction (Opus 4.8). No behavior is gated on a live host/agent resolution.

**Tech Stack:** Python 3.10+, Plan 1 `model_profiles` (`SecurityPosture.cyber_safeguard_friction`, `profile_for`), `model_identity.canonical_for_label`, `pytest`, `uv run`.

**Spec:** [design §2.5, §3.3, §4 wiring rows](2026-06-13-model-aware-optimization-profiles-design.md). Build phase **P8** (lowest-risk text/doc). **Depends on Plan 1**. Independent of Plans 2–6. **This is the last plan in the 7-plan roadmap.**

---

## Decisions (settled)

1. **Handoff completeness is unconditional.** There is no `LearningPosture`-style boolean for "complete delegation spec." The spec's "(Opus host posture)" is a rationale, not a knob. Every consumer (Opus, Codex, a human) benefits from absolute paths + an explicit delegation command + acceptance criteria, so the improvement applies to all handoffs. (Mirrors the Plan 4 oracle hardening, which was also an unconditional, universally-beneficial change.)
2. **The Delegation Spec section is additive** — it is inserted between the header block and the first `---`, and the existing `**Target:** {target_path}` line is **kept verbatim** (so `test_markdown_structure`'s `"**Target:** ./src"` assertion is unaffected). The absolute path lives in the new section.
3. **Recover the dropped M3 fields.** The handoff system prompt already asks M3 for `fix_approach`, `risks`, `context_needed`; they are parsed-then-discarded today. Capture them on `HandoffIssue` (with empty defaults) and render them as conditional per-issue sections — recovering content we already pay for. Empty defaults → sections omitted → no change when M3 omits them.
4. **Cyber-safeguard note is data-driven and agent-scoped.** The note concerns Opus-**as-executor** friction. `provider show` displays one provider; the note fires when *that provider's model* profile has `cyber_safeguard_friction=True` (Opus). Resolution is defensive (no note on any failure). This is the first consumer of the `cyber_safeguard_friction` knob.

---

## Key facts established by investigation (do not re-discover)

**`src/muscle/code_review/handoff_generator.py`:**
- `generate_handoff(issue, all_issues, session_id, target_path, workflow_name=None, review_mode=None)` ([:165-274]) and `generate_handoffs(issues, session_id, target_path, workflow_name=None, review_mode=None)` ([:276-373]) both build a `HandoffIssue` from parsed M3 JSON, then call `self._generate_markdown(session_id, target_path, [handoff_issues...])` ([:266], [:365]) and return a `HandoffPlan`.
- M3 SYSTEM_PROMPT JSON keys ([:85-98]): `root_cause`, `fix_approach`, `verification_steps`, `effort_estimate`, `related_files`, `risks`, `context_needed`. Today only `root_cause`/`verification_steps`/`effort_estimate`/`related_files` are captured; `fix_approach`/`risks`/`context_needed` are **discarded**.
- Parsing helpers: `self._get_string(data, key, default)` and `self._get_string_list(data, key, default)`.
- `_generate_markdown(self, session_id, target_path, issues)` ([:375-470]): header block ([:381-390]) with `**Session:**`, `**Target:** {target_path}`, `**Generated:**`, then `---`, then per-issue sections (Root Cause, Code Context, Description, Suggested Fix, Verification Steps, Related Files). `review_mode` is NOT currently passed to it.
- `_sanitize_markdown_text(text, max_len=...)` is the text sanitizer used throughout.
- Construction (review_controller.py:224-229) passes `project_path`.

**`src/muscle/code_review/types.py`:**
- `HandoffIssue` ([:91-97]): `issue, root_cause, verification_steps, effort_estimate, related_files`. `field` is already imported (used by `raw_issues` default_factory at [:88]).

**`src/muscle/cli/provider.py`:**
- `provider_show()` ([:80-93]): `profile, source = resolve_provider(Path.cwd())`, then `console.print(...)` lines for name/source/model/billing/role/surface/trust/pricing/effort/credentials. `console` and `resolve_provider`/`PROVIDERS` are imported at top.
- `ProviderProfile` has `.model` (a model label string) and `.capability_profile` (e.g. `"claude-opus-4-8"`, `"minimax-m3"`).

**`src/muscle/model_profiles.py`:** `SecurityPosture.cyber_safeguard_friction: bool = False` ([:73]); Opus profile sets it `True` ([:~205]). Currently **no consumer** (only the definition + the Opus value + one data-integrity test assertion). `profile_for(canonical_key)` returns a `ModelProfile`. `canonical_for_label(label)` (model_identity.py) maps a model label → canonical key (Opus aliases were added in Plan 1).

**Tests:**
- `tests/unit/test_handoff_generator.py`: mock M3 client returns a fixed JSON via `chat(**kwargs)`. `test_markdown_structure` ([:279]) asserts `"# Code Review Handoff Plan"`, `"**Session:** test-006"`, `"**Target:** ./src"`, `"## Issue #1:"`, severity/category — all preserved by an additive section. Other tests assert `root_cause`/`verification_steps`/`code_snippet`.
- `tests/unit/test_cli_provider.py`: `CliRunner().invoke(cli, ["provider", "show"], env={...})`; `test_provider_show_reports_codex_chatgpt_login` ([:229]) is the model (sets `MUSCLE_PROVIDER` to select a provider).

---

## File Structure

- **Modify `src/muscle/code_review/types.py`** — add `fix_approach`/`risks`/`context_needed` to `HandoffIssue` (defaults).
- **Modify `src/muscle/code_review/handoff_generator.py`** — capture the 3 fields; add the plan-level Delegation Spec section; thread `review_mode` into `_generate_markdown`; render the 3 new per-issue sections.
- **Modify `src/muscle/cli/provider.py`** — add the data-driven cyber-safeguard friction note to `provider_show`.
- **Tests** — `test_handoff_generator.py`, `test_cli_provider.py`.

---

## Task 1: Complete, self-contained delegation specs in `handoff_generator`

**Files:**
- Modify: `src/muscle/code_review/types.py`, `src/muscle/code_review/handoff_generator.py`
- Test: `tests/unit/test_handoff_generator.py`

- [ ] **Step 1: Write tests first**

In `tests/unit/test_handoff_generator.py` (reuse the file's existing fixtures/mock-client pattern; keep imports at top). Add two tests. The first asserts the plan-level Delegation Spec (works with the existing mock — the section is built from session/target/review_mode, not M3 output). The second asserts the recovered fields (needs a mock returning them — define a local mock or extend the fixture; READ the existing mock first and match its shape):

```python
def test_handoff_includes_delegation_spec(handoff_generator, sample_issue, tmp_path):
    # (use the file's existing way of constructing a generator + issue; adapt names)
    plan = handoff_generator.generate_handoff(
        sample_issue, [sample_issue], "sess-deleg", str(tmp_path), review_mode="auto-fix"
    )
    md = plan.markdown
    assert "## Delegation Spec" in md
    assert str(tmp_path.resolve()) in md  # absolute scope path present
    assert "muscle review" in md  # explicit delegation command
    assert "Acceptance" in md
    assert "auto-fix" in md  # review mode surfaced
    assert "sess-deleg" in md  # session id for resume


def test_handoff_recovers_fix_approach_risks_context(sample_issue, tmp_path):
    # Mock M3 to return the previously-dropped fields, assert they render.
    # (Construct a HandoffGenerator with a mock client whose chat() returns JSON
    # including fix_approach/risks/context_needed — mirror the file's mock pattern.)
    ...
    plan = gen.generate_handoff(sample_issue, [sample_issue], "s", str(tmp_path))
    hi = plan.issues[0]
    assert hi.fix_approach  # captured on the dataclass
    assert hi.risks
    assert hi.context_needed
    assert "### Fix Approach" in plan.markdown
    assert "### Risks" in plan.markdown
    assert "### Context Needed" in plan.markdown
```

(Adapt the fixture/mock names to the file's actual ones — READ the top of the test file first. The plan author could not pin the exact fixture names; the implementer must match them. Both new tests must use the established construction pattern.)

Run → FAIL (`review_mode` not in markdown / `HandoffIssue` has no `fix_approach`).

- [ ] **Step 2: Implement**

**(a) `types.py` — extend `HandoffIssue`:**
```python
@dataclass
class HandoffIssue:
    issue: ReviewIssue
    root_cause: str
    verification_steps: list[str]
    effort_estimate: str
    related_files: list[str]
    fix_approach: str = ""
    risks: list[str] = field(default_factory=list)
    context_needed: str = ""
```

**(b) `handoff_generator.py` — capture the 3 fields** in BOTH success-path `HandoffIssue(...)` constructions (in `generate_handoff` ~[:243-249] and `generate_handoffs` ~[:337-348]), adding:
```python
                fix_approach=self._get_string(data, "fix_approach", ""),
                risks=self._get_string_list(data, "risks", []),
                context_needed=self._get_string(data, "context_needed", ""),
```
(Leave the `except json.JSONDecodeError` fallback constructions as-is — they keep the empty defaults.)

**(c) Thread `review_mode` into `_generate_markdown`:** change its signature to
```python
    def _generate_markdown(
        self,
        session_id: str,
        target_path: str,
        issues: list[HandoffIssue],
        review_mode: str | None = None,
    ) -> str:
```
and pass `review_mode` at both call sites ([:266] and [:365]): `self._generate_markdown(session_id, target_path, [...], review_mode)`.

**(d) Add the plan-level Delegation Spec section** to the header block in `_generate_markdown`. Compute `abs_target = str(Path(target_path).resolve())` (safe on non-existent paths) and insert the section AFTER the `**Generated:**` line and BEFORE the existing `"---"`. KEEP the `f"**Target:** {target_path}"` line unchanged:
```python
        abs_target = str(Path(target_path).resolve())
        scope_line = f"- **Scope:** `{abs_target}`"
        if review_mode:
            scope_line += f" (review mode: {review_mode})"
        lines = [
            "# Code Review Handoff Plan",
            "",
            f"**Session:** {session_id}",
            f"**Target:** {target_path}",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Delegation Spec",
            "",
            scope_line,
            f"- **Delegate to MUSCLE:** `muscle review {abs_target}`",
            "- **Acceptance:** every issue below is resolved and its verification steps "
            "pass; no new HIGH/CRITICAL findings remain in the scope above.",
            f"- **Resume session:** reference session id `{session_id}` for follow-up.",
            "",
            "---",
            "",
        ]
```
> **Verify the `muscle review` invocation form** against `src/muscle/cli/review.py` (positional target vs `--target` flag) and use the correct one. If unsure, use `muscle review {abs_target}` (positional) — confirm the CLI accepts a positional target; if it requires a flag, use `muscle review --target {abs_target}`.

**(e) Render the 3 recovered fields** as conditional per-issue sections in `_generate_markdown`. Add `Fix Approach` right after the Root Cause section, and `Risks` + `Context Needed` after the Verification Steps / Related Files sections:
```python
            if hi.fix_approach:
                lines.extend(
                    ["### Fix Approach", "", _sanitize_markdown_text(hi.fix_approach), ""]
                )
```
```python
            if hi.risks:
                lines.extend(
                    ["### Risks", ""]
                    + [f"- {_sanitize_markdown_text(r, max_len=500)}" for r in hi.risks]
                    + [""]
                )
            if hi.context_needed:
                lines.extend(
                    ["### Context Needed", "", _sanitize_markdown_text(hi.context_needed), ""]
                )
```
(Place `Fix Approach` immediately after the Root Cause block; place `Risks`/`Context Needed` near the end of the per-issue block, before the trailing `["---", ""]`.)

Run: `uv run pytest tests/unit/test_handoff_generator.py -v` → PASS. Existing tests pass: the Delegation Spec is additive (header `**Target:**` line kept), and the recovered-field sections are conditional (empty defaults → omitted) so the fixed-mock tests that don't return those fields are unaffected.

- [ ] **Step 3: Gates + commit**

```
uv run ruff check src/muscle/code_review/types.py src/muscle/code_review/handoff_generator.py tests/unit/test_handoff_generator.py
uv run ruff format src/muscle/code_review/types.py src/muscle/code_review/handoff_generator.py tests/unit/test_handoff_generator.py
uv run mypy src/muscle/code_review/types.py src/muscle/code_review/handoff_generator.py
```

```bash
git add src/muscle/code_review/types.py src/muscle/code_review/handoff_generator.py tests/unit/test_handoff_generator.py
git commit -m "feat(handoff): self-contained delegation spec + recover fix_approach/risks/context_needed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Cyber-safeguard friction note in `muscle provider show`

**Files:**
- Modify: `src/muscle/cli/provider.py`
- Test: `tests/unit/test_cli_provider.py`

- [ ] **Step 1: Write the failing test**

First READ the provider registry to confirm which provider name exposes an Opus model (the explorer flagged `claude-subscription` / `anthropic-api`). Pick the one whose `model` canonicalizes to the Opus key (verify: `uv run python -c "from muscle.providers import PROVIDERS; from muscle.model_identity import canonical_for_label; [print(n, p.model, canonical_for_label(p.model)) for n,p in PROVIDERS.items()]"`). Use that provider name (call it `<OPUS_PROVIDER>`) and a non-Opus one (e.g. `minimax-plan`) in the tests.

In `tests/unit/test_cli_provider.py` (uses `CliRunner` + `from muscle.cli import cli`; match the existing style):
```python
def test_show_reports_cyber_safeguard_friction_for_opus_provider() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["provider", "show"], env={"MUSCLE_PROVIDER": "<OPUS_PROVIDER>"})
    assert result.exit_code == 0, result.output
    assert "cyber-safeguard" in result.output.lower() or "friction" in result.output.lower()


def test_show_omits_cyber_safeguard_note_for_minimax_provider() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["provider", "show"], env={"MUSCLE_PROVIDER": "minimax-plan"})
    assert result.exit_code == 0, result.output
    assert "cyber-safeguard" not in result.output.lower()
    assert "friction" not in result.output.lower()
```

Run → FAIL (no note yet).

- [ ] **Step 2: Implement**

In `provider_show()` (after the `Credentials` line at [:93]), add a defensive, data-driven note:
```python
    # Cyber-safeguard friction (data-driven from the provider model's profile).
    # When the model flags dual-use refusal friction (Opus 4.8), warn that using
    # it as the EXECUTOR may hit refusals on security/exploit-adjacent tasks.
    try:
        from ..model_identity import canonical_for_label
        from ..model_profiles import profile_for

        canonical = canonical_for_label(profile.model)
        if profile_for(canonical).security.cyber_safeguard_friction:
            console.print(
                "[yellow]Cyber-safeguard friction:[/yellow] this model as the executor "
                "may refuse or heavily caveat dual-use/security tasks (exploit-adjacent "
                "code, offensive tooling). Prefer it as the host/planner and MiniMax M3 "
                "as the executor for those tasks."
            )
    except Exception:  # pragma: no cover - defensive; never break `provider show`
        pass
```
> Note: `profile_for` emits a `RuntimeWarning` only for *unrecognized* canonical keys; the curated provider models (Opus, M3, …) are recognized, so no spurious warning appears in normal CLI output. The `try/except` guards any unexpected failure so `provider show` never breaks.

Run: `uv run pytest tests/unit/test_cli_provider.py -v` → PASS.

- [ ] **Step 3: Gates + commit**

```
uv run ruff check src/muscle/cli/provider.py tests/unit/test_cli_provider.py
uv run ruff format src/muscle/cli/provider.py tests/unit/test_cli_provider.py
uv run mypy src/muscle/cli/provider.py
```

```bash
git add src/muscle/cli/provider.py tests/unit/test_cli_provider.py
git commit -m "feat(provider): surface cyber-safeguard friction note for Opus-executor providers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Full gate sweep + roadmap close-out

- [ ] **Step 1: Type/lint/format**

```bash
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
```
Auto-fix + re-run until clean.

- [ ] **Step 2: Full suite (background, ~1–5 min)**

Run: `uv run pytest tests/ -q` (background). Expected: PASS (baseline 3051 passed / 3 skipped after Plan 6; Plan 7 adds ~4 tests). Intended changes: handoffs now carry a Delegation Spec section + recovered M3 fields (universal); `muscle provider show` prints a cyber-safeguard friction note for Opus-executor providers.

- [ ] **Step 3: Commit any straggler auto-fixes** (only if needed)

```bash
git add -A && git commit -m "chore(handoff): Plan 7 gate sweep

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Roadmap close-out (docs only, optional)**

This is the final plan of the 7-plan model-aware-profiles roadmap. Optionally note completion in the design doc or `docs/REMAINING_TODOS.md` if that's the repo convention. Confirm `cyber_safeguard_friction` and all `LearningPosture`/`SecurityPosture`/`HostBehavior`/`AgentBehavior` knobs now have at least one consumer (no dead profile fields remain).

---

## Self-Review (completed by plan author)

**Spec coverage (Plan 7 scope = §2.5, §3.3, §4 wiring rows):**
- ✅ Complete self-contained delegation specs — Task 1 (Delegation Spec section + recovered fields + absolute path + acceptance criteria + resume + review mode).
- ✅ Cyber-safeguard friction note in `cli/provider.py` — Task 2 (data-driven from `cyber_safeguard_friction`, its first consumer).
- ✅ Closes out the roadmap: every profile knob now has a consumer.

**Type/consistency:** `HandoffIssue` gains `fix_approach: str = ""`, `risks: list[str] = field(default_factory=list)`, `context_needed: str = ""`. `_generate_markdown(..., review_mode: str | None = None)`. The friction note reads `profile_for(canonical_for_label(profile.model)).security.cyber_safeguard_friction`.

**Risk notes:**
- Handoff changes are additive and unconditional; the existing `**Target:**` line is preserved so `test_markdown_structure` is unaffected; recovered-field sections are conditional (empty defaults → omitted) so fixed-mock tests don't break.
- The friction note is defensive (`try/except → no note`) and data-driven; `profile_for` won't warn for the curated provider models. No live host/agent resolution — it reflects the *shown provider's* model.
- Lowest-risk plan in the roadmap (text/doc); no control-flow or escalation/effort changes.
- The exact `muscle review` invocation form and the test fixture/provider names must be verified by the implementer against the real CLI/registry (flagged inline) — the plan author could not pin them without running the code.
