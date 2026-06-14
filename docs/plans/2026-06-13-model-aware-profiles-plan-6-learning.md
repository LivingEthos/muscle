# Model-Aware Optimization Profiles — Plan 6: Learning Reinforcement

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the two `LearningPosture` host-profile flags into the learning pipeline: (1) `point_of_action_reinforcement` — when the host profile sets it, the published root `CLAUDE.md` emphasizes the top-N highest-value Critical Rules so they're salient where the host reads them; (2) `repeated_violation_escalation` — when the host profile sets it, the verification loop tracks per-rule failure counts and emits a rule-attributed `"repeated_rule_violation"` escalation when the *same* learned rule repeatedly fails verification. Both `True` only on Opus; default `False` = byte-identical no-op.

**Architecture:** A defensive `resolve_host_learning_posture(project_path) -> LearningPosture` (model_profiles.py) resolves the host profile's learning flags (`LearningPosture()` — both `False` — on any failure). `ClaudePublisher._build_published_content` consults `point_of_action_reinforcement` to bold the top-N sorted Critical Rules in place (no extra lines, no duplication, no reordering). `VerificationLoop` gains a per-rule failure counter and consults `repeated_violation_escalation` in `_check_escalation` to emit a sharper, rule-attributed escalation alongside today's session-global one.

**Tech Stack:** Python 3.10+, Plan 1 `model_profiles` (`LearningPosture`, `resolve_active_profiles`), `escalation.py`, `pytest`, `uv run`.

**Spec:** [design §2.3, §4 wiring row](2026-06-13-model-aware-optimization-profiles-design.md). Build phase **P7** ("most behaviorally subtle; lands late"). **Depends on Plan 1**. Independent of Plans 2–5.

---

## Decisions (settled — flagging for review)

1. **Host-driven (per the handoff).** Both flags read the **host** profile's `LearningPosture`: `point_of_action_reinforcement` shapes the `CLAUDE.md` the host reads; `repeated_violation_escalation` sharpens the escalation signal *to* the host planner. Resolution: `resolve_active_profiles(pp).host.learning`. Opus host → both `True`; unknown/default/Fable/M3 → both `False`.
2. **`point_of_action_reinforcement` = bold the top-N (N=3) highest-value Critical Rules in place.** This is the lowest-risk faithful reading of "re-surface high-value rules at the decision point": the top rules (already sorted first by score) become visually salient where the host reads them. It adds **no** extra lines, **no** duplicated text, and does **not** reorder — so it cannot break the existing size-cap / dedup / sort tests (verified: those tests use substring/line-prefix/position checks that a `**…**` wrapper preserves). A louder "re-stated callout block" was rejected as higher-risk (duplicates text → breaks dedup; adds lines → complicates the cap).
3. **`repeated_violation_escalation` = rule-attributed escalation, not earlier escalation.** The existing session-global escalation (`len(self._failed_fixes) >= 2`) is unchanged for all hosts. When the Opus host opts in, the verification loop *additionally* tracks per-rule failure counts and, when the **same** rule (`issue.cwe_id or issue.title`) reaches the failure threshold, emits a distinct `"repeated_rule_violation"` escalation naming that rule — a more actionable signal for the planner. This keeps escalation *volume/timing* unchanged (low-risk) while giving the careful host a sharper, rule-specific signal. The default host is untouched. *(Alternative considered: lower the threshold so Opus escalates earlier — rejected as it changes escalation volume and is harder to reason about. Flag if you want the more aggressive version.)*
4. **Out of scope (noted follow-up):** `learning_pipeline._get_recurrence_count` is still a stub returning `1` (real cross-run `review_findings.rule_id` counting is a separate, larger change). Plan 6 does not touch scoring; it works with the existing `score`/`validated_count` and the in-session per-rule failure counter.

**No-op proof:** default host → `LearningPosture(point_of_action_reinforcement=False, repeated_violation_escalation=False)` → publisher renders rules byte-identically to today; verification loop's `_check_escalation` behaves exactly as today (the per-rule branch is gated off).

---

## Key facts established by investigation (do not re-discover)

**`src/muscle/model_profiles.py`:**
- `LearningPosture` ([:83-88]): `point_of_action_reinforcement: bool = False`, `repeated_violation_escalation: bool = False`. Opus profile sets both `True`; `default`/M3/Fable leave both `False`.
- Has `resolve_active_profiles`, `PROFILES`, `DEFAULT_PROFILE_KEY`, `logger`, `from pathlib import Path`. Sibling defensive helpers `resolve_agent_security_posture`, `resolve_host_synthesis_floor` exist as the pattern to mirror.

**`src/muscle/claude_publisher.py`:**
- `ClaudePublisher` has `self.project_path` ([:173]) and already resolves the host profile in `_build_published_content` via `resolve_host_fragment_keys(self.project_path)` ([:679]).
- Critical Rules render ([:682-698]): sorts `critical_rules` by `(score, validated_count)` desc, caps at `MAX_SECTION_LINES`, renders each as `f"- {text} (score: {score}, validated: {validated}x)"` where `text = self._compile_host_memory_text(...)`.
- `publish(critical_rules=..., mistake_corrections=..., agent_calls=..., skill_calls=..., tooling_notes=...)`.
- Tests in `tests/unit/test_claude_publisher.py`: `test_publish_sorts_by_score` (:266, uses `content.find("High score rule")` position checks — a `**…**` wrapper preserves these), `test_publish_enforces_size_cap` (:117, counts lines starting with `-`), `test_publish_deduplicates_entries` (:147, counts a rule-text occurrence == 1), `test_publish_idempotent` (:387, byte-for-byte). `TestPublisherHostFragments` (:812) uses `monkeypatch.setenv("MUSCLE_HOST_MODEL","opus")` — the pattern for opus-host tests. **This dev box's `~/.claude/settings.json` selects opus**, so publisher tests resolve the Opus host unless they isolate `HOME`.

**`src/muscle/code_review/verification_loop.py`:**
- `VerificationLoop` dataclass ([:98-106]): fields incl. `_verified_fixes`, `_failed_fixes: list[VerificationResult]`, `_runtime_context: dict`.
- `configure_runtime(project_path, session_id, ...)` ([:108-131]) stores `project_path`/`session_id` in `_runtime_context`. Called by `ReviewController`.
- `verify_fix` ([:158-225]): on failure appends to `_failed_fixes` and calls `self._check_escalation(result)` ([:222-223]).
- `_check_escalation(result)` ([:133-156]): early-returns if no `project_path`/`session_id`; else `policy = EscalationPolicy()`, `attempt_count = len(self._failed_fixes)`, `recorder = EscalationRecorder(project_path, policy)`, `if recorder.should_escalate("verification_failure", attempt_count): recorder.emit(EscalationRecord(reason="verification_failure", source_module="verification_loop", ...))`.
- The rule identity used upstream is `issue.cwe_id or issue.title` (review_controller.py:1387).
- `escalation.py`: `EscalationPolicy.escalate_on_verification_failure_count = 2`; `should_escalate("verification_failure", n) -> n >= 2`; `emit(record)` writes a markdown artifact (`.muscle/reports/escalations/{session_id}.md`) + a DB row in `escalations` (columns incl. `reason`, `attempt_count`, `issue_summary`).
- Tests in `tests/unit/test_verification_loop.py`: 2 tests, construct `VerificationLoop(m27_client=..., verify_compile=..., ...)` inline, do NOT call `configure_runtime` (so `_check_escalation` early-returns → escalation paths untested today). `_issue`-style `ReviewIssue` construction.

---

## File Structure

- **Modify `src/muscle/model_profiles.py`** — add `resolve_host_learning_posture(project_path) -> LearningPosture`.
- **Modify `src/muscle/claude_publisher.py`** — `_build_published_content` bolds the top-N Critical Rules when `point_of_action_reinforcement`.
- **Modify `src/muscle/code_review/verification_loop.py`** — per-rule failure counter + rule-attributed escalation when `repeated_violation_escalation`.
- **Tests** — `test_model_profiles.py`, `test_claude_publisher.py`, `test_verification_loop.py`.

---

## Task 1: `resolve_host_learning_posture` helper

**Files:**
- Modify: `src/muscle/model_profiles.py`
- Test: `tests/unit/test_model_profiles.py`

- [ ] **Step 1: Write tests first**

In `tests/unit/test_model_profiles.py` — add `LearningPosture` and `resolve_host_learning_posture` to the top import block from `muscle.model_profiles`. Append:

```python
def test_resolve_host_learning_posture_opus(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    posture = resolve_host_learning_posture(tmp_path)
    assert posture.point_of_action_reinforcement is True
    assert posture.repeated_violation_escalation is True


def test_resolve_host_learning_posture_unknown_is_off(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    posture = resolve_host_learning_posture(tmp_path)
    assert posture.point_of_action_reinforcement is False
    assert posture.repeated_violation_escalation is False
```

Run: `uv run pytest tests/unit/test_model_profiles.py -k "learning_posture" -v` → FAIL.

- [ ] **Step 2: Implement**

In `model_profiles.py`, near the sibling resolvers:

```python
def resolve_host_learning_posture(project_path: Path | str | None) -> LearningPosture:
    """Resolve the active HOST profile's LearningPosture, defensively.

    Returns the conservative default posture (both flags ``False``) on any
    resolution failure, so publishing/verification never break on profile edge
    cases. Mirrors resolve_host_synthesis_floor / resolve_agent_security_posture.
    """
    try:
        resolved = Path(project_path) if project_path is not None else None
        return resolve_active_profiles(resolved).host.learning
    except Exception:
        logger.debug("resolve_host_learning_posture failed; using default posture", exc_info=True)
        return PROFILES[DEFAULT_PROFILE_KEY].learning
```

Run: `uv run pytest tests/unit/test_model_profiles.py -k "learning_posture" -v` → PASS.

- [ ] **Step 3: Gates + commit**

```
uv run ruff check src/muscle/model_profiles.py tests/unit/test_model_profiles.py
uv run ruff format src/muscle/model_profiles.py tests/unit/test_model_profiles.py
uv run mypy src/muscle/model_profiles.py
```

```bash
git add src/muscle/model_profiles.py tests/unit/test_model_profiles.py
git commit -m "feat(learning): add resolve_host_learning_posture defensive helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Point-of-action reinforcement in the publisher

**Files:**
- Modify: `src/muscle/claude_publisher.py`
- Test: `tests/unit/test_claude_publisher.py`

- [ ] **Step 1: Write tests first**

In `tests/unit/test_claude_publisher.py` append (match the file's existing `with tempfile.TemporaryDirectory()` + `ClaudePublisher(tmpdir)` + `publish(...)` + read-CLAUDE.md pattern; import `ClaudePublisher` inside the method as the file does; these tests need `monkeypatch`/`tmp_path`, so use `tmp_path` instead of `TemporaryDirectory`):

```python
class TestPointOfActionReinforcement:
    RULES = [
        {"text": "Top value rule", "score": 0.9, "validated_count": 5},
        {"text": "Mid value rule", "score": 0.6, "validated_count": 2},
        {"text": "Low value rule", "score": 0.2, "validated_count": 1},
        {"text": "Fourth rule", "score": 0.1, "validated_count": 1},
    ]

    def test_opus_host_bolds_top_rules(self, monkeypatch, tmp_path):
        from muscle.claude_publisher import ClaudePublisher

        monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\n")
        ClaudePublisher(str(tmp_path)).publish(critical_rules=list(self.RULES))
        content = (tmp_path / "CLAUDE.md").read_text()
        # Top 3 by score are bolded; the 4th is not.
        assert "- **Top value rule**" in content
        assert "- **Mid value rule**" in content
        assert "- **Low value rule**" in content
        assert "- **Fourth rule**" not in content
        assert "- Fourth rule (score:" in content

    def test_unknown_host_does_not_bold(self, monkeypatch, tmp_path):
        from muscle.claude_publisher import ClaudePublisher

        monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\n")
        ClaudePublisher(str(tmp_path)).publish(critical_rules=list(self.RULES))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "- **Top value rule**" not in content
        assert "- Top value rule (score:" in content
```

Run → the opus test FAILS (no bolding yet).

- [ ] **Step 2: Implement**

In `claude_publisher.py`:

1. Add a module-level constant near `MAX_SECTION_LINES`:
```python
# Number of highest-value Critical Rules to emphasize when the host profile sets
# point_of_action_reinforcement (re-surface the top rules where the host reads them).
REINFORCED_RULE_COUNT = 3
```

2. In `_build_published_content`, resolve the learning posture once near the top of the method (alongside the existing host-fragment resolution) and use it in the Critical Rules loop. Replace the rules block ([:682-698]) with:

```python
        # Critical Rules (high score rules first). When the host profile opts into
        # point-of-action reinforcement, the top-N highest-value rules are bolded
        # in place so they are salient where the host reads them (no extra lines,
        # no duplication, no reordering).
        if critical_rules:
            from .model_profiles import resolve_host_learning_posture

            reinforce = resolve_host_learning_posture(
                self.project_path
            ).point_of_action_reinforcement
            lines.append(SECTION_CRITICAL_RULES)
            sorted_rules = sorted(
                critical_rules,
                key=lambda r: (r.get("score", 0), r.get("validated_count", 0)),
                reverse=True,
            )
            for index, rule in enumerate(sorted_rules[:MAX_SECTION_LINES]):
                text = self._compile_host_memory_text(
                    str(rule.get("text", "")),
                    compact_host_memory=compact_host_memory,
                )
                if reinforce and index < REINFORCED_RULE_COUNT:
                    text = f"**{text}**"
                score = rule.get("score", 0)
                validated = rule.get("validated_count", 0)
                lines.append(f"- {text} (score: {score}, validated: {validated}x)")
            lines.append("")
```

(Use a lazy in-function import of `resolve_host_learning_posture` — matches the Plan 3/4 pattern and avoids widening the import graph. `claude_publisher` already imports from `code_review.host_memory_templates`; importing from `model_profiles` is acyclic.)

Run: `uv run pytest tests/unit/test_claude_publisher.py -k "Reinforcement" -v` → PASS.

- [ ] **Step 3: Full file + commit**

Run: `uv run pytest tests/unit/test_claude_publisher.py -v`. The bolding is an in-place `**…**` wrapper on the top-N — it preserves substring positions (`test_publish_sorts_by_score`), line-prefix counts (`test_publish_enforces_size_cap`), single-occurrence dedup (`test_publish_deduplicates_entries`), and determinism (`test_publish_idempotent`). So all pre-existing tests should pass **even though this dev box resolves the Opus host** (bolding on). If any pre-existing test DOES break, isolate the host in that specific test (`monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)` + `monkeypatch.setenv("HOME", str(tmp_path/"empty-home"))`) so it runs against the default host — do NOT weaken the assertion. Report any test you had to isolate and why.

Gates:
```
uv run ruff check src/muscle/claude_publisher.py tests/unit/test_claude_publisher.py
uv run ruff format src/muscle/claude_publisher.py tests/unit/test_claude_publisher.py
uv run mypy src/muscle/claude_publisher.py
```

```bash
git add src/muscle/claude_publisher.py tests/unit/test_claude_publisher.py
git commit -m "feat(learning): publisher bolds top-N high-value rules under point_of_action_reinforcement

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Repeated-violation escalation in the verification loop

**Files:**
- Modify: `src/muscle/code_review/verification_loop.py`
- Test: `tests/unit/test_verification_loop.py`

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_verification_loop.py` (keep imports at top — the file imports `VerificationLoop`, `ReviewIssue`/`Severity` helpers, `tmp_path`). Add a test that drives two failed verifications of the SAME rule and asserts a `repeated_rule_violation` escalation row appears for the Opus host. Use the file's existing `ReviewIssue` construction; set `verify_compile=False, verify_linter=False, verify_tests=False` and monkeypatch `_m27_verify` to return a `NEEDS_WORK` status so each `verify_fix` fails. Configure runtime so `_check_escalation` runs.

```python
def test_repeated_rule_violation_escalates_for_opus_host(tmp_path, monkeypatch):
    import sqlite3

    from muscle.project_memory import ProjectMemory

    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    pm = ProjectMemory(str(tmp_path))
    pm._init_db()

    target = tmp_path / "f.py"
    target.write_text("original\n")

    loop = VerificationLoop(
        m27_client=object(),  # type: ignore[arg-type]
        verify_compile=False,
        verify_linter=False,
        verify_tests=False,
    )
    loop.configure_runtime(project_path=str(tmp_path), session_id="s1")
    monkeypatch.setattr(loop, "_m27_verify", lambda issue, fixed: ("NEEDS_WORK: nope", None))
    monkeypatch.setattr(loop, "_m27_analyze_failure", lambda issue, text: "analysis")

    issue = ReviewIssue(
        file_path=str(target),
        line_number=1,
        severity=Severity.HIGH,
        category=IssueCategory.CORRECTNESS,
        cwe_id="CWE-89",
        title="SQL injection",
        description="d",
        code_snippet="c",
    )
    # Two failed verifications of the SAME rule (cwe_id="CWE-89").
    loop.verify_fix(issue, "fixed-1\n")
    loop.verify_fix(issue, "fixed-2\n")

    db = tmp_path / ".muscle" / "project_memory.db"
    with sqlite3.connect(db) as conn:
        reasons = [r[0] for r in conn.execute("SELECT reason FROM escalations").fetchall()]
    assert "repeated_rule_violation" in reasons


def test_repeated_rule_violation_absent_for_default_host(tmp_path, monkeypatch):
    import sqlite3

    from muscle.project_memory import ProjectMemory

    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    pm = ProjectMemory(str(tmp_path))
    pm._init_db()

    target = tmp_path / "f.py"
    target.write_text("original\n")

    loop = VerificationLoop(
        m27_client=object(),  # type: ignore[arg-type]
        verify_compile=False,
        verify_linter=False,
        verify_tests=False,
    )
    loop.configure_runtime(project_path=str(tmp_path), session_id="s1")
    monkeypatch.setattr(loop, "_m27_verify", lambda issue, fixed: ("NEEDS_WORK: nope", None))
    monkeypatch.setattr(loop, "_m27_analyze_failure", lambda issue, text: "analysis")

    issue = ReviewIssue(
        file_path=str(target),
        line_number=1,
        severity=Severity.HIGH,
        category=IssueCategory.CORRECTNESS,
        cwe_id="CWE-89",
        title="SQL injection",
        description="d",
        code_snippet="c",
    )
    loop.verify_fix(issue, "fixed-1\n")
    loop.verify_fix(issue, "fixed-2\n")

    db = tmp_path / ".muscle" / "project_memory.db"
    with sqlite3.connect(db) as conn:
        reasons = [r[0] for r in conn.execute("SELECT reason FROM escalations").fetchall()]
    # Default host still gets the generic session-global escalation, never the rule-attributed one.
    assert "repeated_rule_violation" not in reasons
    assert "verification_failure" in reasons
```

(Add `IssueCategory` to the test's top imports if not already present — check the file's existing imports; `ReviewIssue`/`Severity` are likely already imported. Keep all imports at the top EXCEPT the in-test `sqlite3`/`ProjectMemory` locals shown, which match the repo's established in-test-import style for DB helpers — or hoist them to the top, your call, ruff-clean either way.)

Run → FAIL (no `repeated_rule_violation` reason emitted).

- [ ] **Step 2: Implement**

In `verification_loop.py`:

1. Add a per-rule failure counter field to the dataclass (after `_failed_fixes`):
```python
    _rule_failure_counts: dict[str, int] = field(default_factory=dict)
```

2. In `verify_fix`, in the failure branch, increment the per-rule counter BEFORE calling `_check_escalation`:
```python
        if result.fix_verified:
            self._verified_fixes.append(result)
        else:
            self._failed_fixes.append(result)
            rule_id = result.issue.cwe_id or result.issue.title
            self._rule_failure_counts[rule_id] = self._rule_failure_counts.get(rule_id, 0) + 1
            self._check_escalation(result)
```

3. In `_check_escalation`, after the existing session-global escalation block, add the host-gated rule-attributed escalation:
```python
    def _check_escalation(self, result: VerificationResult) -> None:
        """Emit escalation if verification failures exceed the policy threshold."""
        project_path = self._runtime_context.get("project_path")
        session_id = self._runtime_context.get("session_id")
        if not project_path or not session_id:
            return

        policy = EscalationPolicy()
        recorder = EscalationRecorder(project_path, policy)
        attempt_count = len(self._failed_fixes)
        if recorder.should_escalate("verification_failure", attempt_count):
            recorder.emit(
                EscalationRecord(
                    session_id=session_id,
                    reason="verification_failure",
                    source_module="verification_loop",
                    issue_summary=(
                        f"Fix verification failed for {result.issue.file_path}:"
                        f"{result.issue.line_number} — {result.issue.title}."
                        f" {attempt_count} cumulative failure(s)."
                    ),
                    attempt_count=attempt_count,
                )
            )

        # Opus host: additionally flag a repeatedly-violated SAME rule with a
        # sharper, rule-attributed escalation (treat repeated rule-violation as an
        # escalation signal). Gated on the host profile; default host is untouched.
        if self._host_repeated_violation_escalation():
            rule_id = result.issue.cwe_id or result.issue.title
            rule_count = self._rule_failure_counts.get(rule_id, 0)
            if rule_count >= policy.escalate_on_verification_failure_count:
                recorder.emit(
                    EscalationRecord(
                        session_id=session_id,
                        reason="repeated_rule_violation",
                        source_module="verification_loop",
                        issue_summary=(
                            f"Rule '{rule_id}' failed verification {rule_count} time(s) "
                            f"(latest: {result.issue.file_path}:{result.issue.line_number})."
                        ),
                        attempt_count=rule_count,
                    )
                )

    def _host_repeated_violation_escalation(self) -> bool:
        project_path = self._runtime_context.get("project_path")
        if not project_path:
            return False
        try:
            from ..model_profiles import resolve_host_learning_posture

            return resolve_host_learning_posture(project_path).repeated_violation_escalation
        except Exception:
            logger.debug("learning posture resolution failed in verification loop", exc_info=True)
            return False
```

(Confirm `field` is imported from `dataclasses` at the top of the module — it is, since `_failed_fixes` uses `field(default_factory=list)`. Confirm a module-level `logger` exists — it does.)

NOTE on the escalation artifact: `EscalationRecorder.emit` writes `.muscle/reports/escalations/{session_id}.md`, so a second emit in the same session overwrites that markdown file — but each emit inserts a distinct DB row (which the tests assert on). That overwrite is pre-existing behavior and acceptable; the DB is the record of truth.

Run: `uv run pytest tests/unit/test_verification_loop.py -v` → PASS (incl. the 2 pre-existing tests, which don't call `configure_runtime` → `_check_escalation` early-returns → untouched).

- [ ] **Step 3: Gates + commit**

```
uv run ruff check src/muscle/code_review/verification_loop.py tests/unit/test_verification_loop.py
uv run ruff format src/muscle/code_review/verification_loop.py tests/unit/test_verification_loop.py
uv run mypy src/muscle/code_review/verification_loop.py
```

```bash
git add src/muscle/code_review/verification_loop.py tests/unit/test_verification_loop.py
git commit -m "feat(learning): verification loop emits rule-attributed escalation under repeated_violation_escalation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Full gate sweep

- [ ] **Step 1: Type/lint/format**

```bash
uv run mypy src/muscle/
uv run ruff check src/muscle/
uv run ruff format --check src/muscle/
```
Auto-fix + re-run until clean.

- [ ] **Step 2: Full suite (background, ~1–5 min)**

Run: `uv run pytest tests/ -q` (background). Expected: PASS (baseline 3045 passed / 3 skipped after Plan 5; Plan 6 adds ~6 tests). Intended changes: published `CLAUDE.md` bolds the top-3 Critical Rules for an Opus host; the verification loop emits a `repeated_rule_violation` escalation for an Opus host when the same rule repeatedly fails. Default host: unchanged.

- [ ] **Step 3: Commit any straggler auto-fixes** (only if needed)

```bash
git add -A && git commit -m "chore(learning): Plan 6 gate sweep

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

**Spec coverage (Plan 6 scope = §2.3 learning / §4 wiring row):**
- ✅ `point_of_action_reinforcement` re-surfaces high-value rules — Task 2 (bold top-N in the published doc).
- ✅ `repeated_violation_escalation` treats repeated rule-violation as an escalation — Task 3 (rule-attributed escalation in the verification loop).
- ✅ Host-driven via `resolve_host_learning_posture` — Task 1.
- ✅ No-op guarantee: default host → both `False` → publisher renders identically; `_check_escalation` rule branch gated off.

**Type/consistency:** `resolve_host_learning_posture(project_path) -> LearningPosture` (default posture on failure). `REINFORCED_RULE_COUNT = 3`. `_rule_failure_counts: dict[str, int]`. `_host_repeated_violation_escalation() -> bool` (defensive).

**Risk notes:**
- The bold marker is in-place (`**text**`) — no extra lines, no duplication, no reordering — so existing publisher tests (sort/cap/dedup/idempotent) pass even with the Opus host resolved on this box. If one breaks, isolate that test's host (Plan 5 pattern), do not weaken.
- The rule-attributed escalation is additive and host-gated; default host behavior (session-global escalation) is byte-identical. Pre-existing verification-loop tests don't configure runtime, so `_check_escalation` early-returns and is unaffected.
- `_get_recurrence_count` remains a stub (returns 1) — real cross-run recurrence counting is a deliberate out-of-scope follow-up; Plan 6 uses the in-session per-rule failure counter for escalation, not scoring.
- Decisions 2 & 3 (in-place bold; rule-attributed-not-earlier escalation) are the low-risk readings — flagged for review in case a louder reinforcement or an earlier-escalation variant is wanted.
