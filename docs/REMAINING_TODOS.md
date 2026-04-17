# MUSCLE — Remaining Pre-Release TODOs

**Date:** 2026-04-17 (updated)
**Status:** Release-ready. All 🔴 High, 🟠 Medium, and 🟡 Low items resolved.
Phase A (delegation overhaul), Phase B.1–B.6 (cost-savings features), and
Phase C (hardening) are all shipped. **2096 tests pass; 0 mypy errors;
ruff + format clean.**

**Key pointers for ongoing work:**

- Release gate items live in `MUSCLE_ROADMAP.md §10 Definition of Done` — those
  are the criteria for tagging `v0.2.0`, not additional fixes.
- Deferred work (Foresight, consensus review, cross-project pack library) is
  tracked in `MUSCLE_ROADMAP.md §8 Phase D`, gated on post-release data.

**Scope:** The sections below preserve the original audit log with every
finding's closure status. New findings should be added to
`MUSCLE_ROADMAP.md §7` rather than back-filled here.

---

## How to read this document

- **Finding IDs** preserve the audit's `[PREFIX-NN]` scheme (e.g. `[M27-05]`) so
  historical references and commit messages remain resolvable.
- Each entry lists: **file:line**, **severity**, **category**, **why it matters**,
  and the **fix direction**.
- "Acceptance" calls out an existing test to extend or a new test to add.
- Work is grouped by subsystem, not by severity — pick a subsystem, burn it down.

### Status legend

- 🔴 **Critical / High** — must ship before release or in the first hotfix
- 🟠 **Medium** — quality/robustness gaps; ship-blocking only if neighboring Critical work lands alongside
- 🟡 **Low** — polish / doc / dead-code; safe for post-release

---

## 1. Core runtime

### 1.1 `m27_client.py`

**[M27-05]** `m27_client.py` — ✅ FIXED 2026-04-17 — 🟠 Medium / Code Quality — Bare `except Exception: break` inside retry loop
- *Why:* Swallows transient network errors and aborts retry prematurely.
- *Fix:* Narrow to `(requests.RequestException, json.JSONDecodeError, ValueError)`; continue retry on transient.
- *Acceptance:* Extend `tests/unit/test_m27_client.py` with a mock that raises `ConnectionResetError` mid-retry and asserts the loop continues, plus a `ValueError` that breaks.

### 1.2 `loop_controller.py`

**[LC-01]** `loop_controller.py` — ✅ FIXED 2026-04-17 — Budget arithmetic clamped at zero; `BUDGET_OVERSPEND` event emitted once. Commit: `fix: [LC-01, LC-02]`.

**[LC-02]** `loop_controller.py` — ✅ FIXED 2026-04-17 — `_running` flag added; raises `RuntimeError` on concurrent `run()`. Commit: `fix: [LC-01, LC-02]`.

**[LC-04]** `loop_controller.py:542-665` — ✅ FIXED 2026-04-17 — 🟠 Medium / Error Handling — `_sigterm_handler` exception can corrupt signal state
- *Why:* If the handler raises, the `finally` re-registers but after an undefined state.
- *Fix:* Wrap handler body in `try/except`, always set the shutdown flag before re-raising.
- *Acceptance:* Unit test that forces the handler to raise; assert shutdown flag is set.

**[LC-05]** `loop_controller.py:78` — ✅ FIXED 2026-04-17 — 🟠 Medium / Bug — Verify `LoopStats.start_time` uses `default_factory=time.time` (callable, not a call)
- *Why:* Written as `default_factory=time.time()` would cache one timestamp across all instances.
- *Fix:* Audit declaration; add regression test creating two `LoopStats` instances ≥1 s apart and asserting their `start_time` differs.

### 1.3 `code_generator.py`

**[CG-02]** `code_generator.py` — ✅ FIXED 2026-04-17 — `full_response` assignment moved outside streaming loop. Commit: `fix: [CG-02]`.

**[CG-04]** `code_generator.py:376-377` — ✅ FIXED 2026-04-17 — 🟠 Medium / Silent Failure — Broad `except Exception` in fenced-block extraction
- *Fix:* Narrow to `(OSError, UnicodeError, re.error)`; let programming errors propagate.

**[CG-05]** `code_generator.py:621-699` — ✅ FIXED 2026-04-17 — 🟠 Medium / Code Quality — No UTF-8 validation on the plain-code fallback path
- *Fix:* Round-trip via `text.encode("utf-8", "replace").decode("utf-8")` before emit; log if replacement happened.

### 1.4 `session_manager.py`

**[SM-03]** `session_manager.py:53-57` — ✅ FIXED 2026-04-17 — 🟠 Medium / Security — Unicode bypasses the session-id sanitizer
- *Why:* `isalnum()` accepts non-ASCII alphanumerics → paths become host-FS dependent.
- *Fix:* Restrict to `string.ascii_letters + string.digits + "_-"` explicitly.
- *Acceptance:* Parametrized test with inputs like `"résumé"`, `"ＡＢＣ"`, emoji; assert only safe ASCII survives.

### 1.5 `budget_manager.py`

**[BM-02]** `budget_manager.py:69-90` — ✅ FIXED 2026-04-17 — 🟠 Medium / Missing Validation — Budget file accepts negative / non-int values
- *Why:* Corrupted JSON → unlimited spend.
- *Fix:* `max(0, int(data.get("remaining_tokens", 0)))` with explicit type check; log and reset on bad values.

### 1.6 `evaluator_registry.py` / evaluators

**[ER-01]** `evaluator_registry.py:98-172` — ✅ FIXED 2026-04-17 — 🟠 Medium / Error Handling — Failed evaluator imports retried on every call
- *Fix:* Cache import outcome (success/fail) per class; log once.

**[EV-T1]** `evaluators/compiler.py:75` — ✅ FIXED 2026-04-17 — 🟠 Medium / Resource Leak — `stderr` not bounded
- *Fix:* Slice `stderr` to 5 KB before appending to the result; log total length if truncated.

### 1.7 `cli.py`

**[CLI-02]** `cli.py:70-71` — ✅ FIXED 2026-04-17 — 🟠 Medium / Missing Validation — `MAX_TASK_LENGTH` / `MAX_TIMEOUT_SECONDS` enforced only at one boundary
- *Why:* Env-var and config-file entry points bypass the check.
- *Fix:* Move assertions into `RunConfig.__post_init__` (see TY-01).

**[CLI-03]** `cli.py` → `webhook_notifier.py:44-46` — ✅ FIXED 2026-04-17 — 🟠 Medium / Security — Webhook URL not required to be HTTPS
- *Why:* SSRF / data-exfiltration vector; currently any scheme passes.
- *Fix:* In `WebhookNotifier.__init__`, require `url.startswith("https://")` (or be in an explicit allowlist); reject with a clear error.
- *Acceptance:* Test that `WebhookNotifier("http://evil.example/")` raises or disables itself with a warning; `https://…` passes.

### 1.8 `types.py`

**[TY-01]** `types.py:41-56` — ✅ FIXED 2026-04-17 — 🟠 Medium / Missing Validation — `RunConfig` frozen dataclass has no `__post_init__` checks
- *Why:* Negative `max_iterations`, zero `timeout_seconds` accepted.
- *Fix:* Add `__post_init__` asserting bounds; incorporate CLI-02 limits.

---

## 2. Code review subsystem

### 2.1 `code_review/code_reviewer.py`

**[CR-05]** `code_reviewer.py:161, 239-240` — ✅ FIXED 2026-04-17 — 🟠 Medium / Code Quality — `max_issues_per_batch = 20` hardcoded as constructor default
- *Fix:* Thread through `ReviewConfig` (or equivalent) so it is documented and overridable.

### 2.2 `code_review/fix_generator.py`

**[FG-02]** `fix_generator.py` — ✅ FIXED 2026-04-17 — Extension renamed to `.muscle.bak`; `_sweep_stale_baks()` runs at start of `apply_fix()`; restore wrapped in `try/except`. Commit: `fix: [FG-02, RC-02, RC-03]`.

**[FG-04]** `fix_generator.py:339-370` — ✅ FIXED 2026-04-17 — 🟠 Medium / Dead Code — `verify_fix()` always returns `True`
- *Fix:* Either implement a real compile+lint check and wire it into `apply_fix`, or delete the method and all call sites.

### 2.3 `code_review/review_controller.py`

**[RC-02]** `review_controller.py` — ✅ FIXED 2026-04-17 — `_worktree_cleanup_failures` counter added; surfaced in logs. Commit: `fix: [FG-02, RC-02, RC-03]`.

**[RC-03]** `review_controller.py` — ✅ FIXED 2026-04-17 — Regression test added covering each exception path inside locked region. Commit: `fix: [FG-02, RC-02, RC-03]`.

### 2.4 Shadow job queue

**[SH-04]** `shadow_worker.py:184-189, 247-254` — ✅ FIXED 2026-04-17 — 🟠 Medium / Concurrency — `_in_progress_jobs` lock contract needs assertion + test
- *Fix:* Add `assert self._lock.locked()` at the protected mutation sites; add a concurrent-start test to cover the invariant.

### 2.5 Other review modules

**[TY-CR]** `code_review/types.py:93-106` — ✅ FIXED 2026-04-17 — 🟠 Medium / Code Quality — Mixed use of `.name` vs `.value` on enums
- *Fix:* Audit call sites, standardize on `.value` for persistence / JSON and `.name` for logs; add a project-wide lint rule (`grep`-based CI check is fine) to prevent regression.

---

## 3. Plugin

**[PL-02]** `tools/muscle/plugin/` `CLAUDE.md` and misc docs — ✅ FIXED 2026-04-17 — Verified no remaining `muscle shadow …` or `muscle settings platform --hooks` references in `tools/muscle/plugin/**`. CI check for live-command coverage still a follow-up (tracked as hygiene).

**[PL-03]** `tools/muscle/plugin/commands/` — ✅ FIXED 2026-04-17 — Manifest `description` rewritten to match filesystem (added `cancel`, `nightly-status`, `result`, `optimize-host-docs`, `pack`; dropped stale `init`/`enable`/`disable`). `tests/unit/test_plugin_manifest.py` now enforces bidirectional parity per-command.

---

## 4. TUI

**[TU-02]** `tui/views.py` — ✅ FIXED 2026-04-17 — `data_unavailable` / `data_error` added to `ViewState`; `DashboardView.render()` shows explicit error panel on provider failure. Commit: `fix: [TU-02] TUI data-unavailable panel + feat: [B.5]`.

---

## 5. Adapters

All adapter timeout + rate-limit hygiene is already in `http_utils.py`; what remains is narrower:

**[AD-token-tests]** — ✅ FIXED 2026-04-17 — 🟠 Medium / Test Gap — No unit tests asserting `redact_secrets` catches the tokens actually present in this repo's adapter codepaths
- *Fix:* New `tests/unit/test_http_utils.py` with table-driven cases for Bearer tokens, `ghp_*`, `glpat_*`, `Authorization:` lines, and `token=…` query strings.

---

## 6. Backup manager / project memory

**[PM-01]** `project_memory.py` — ✅ FIXED 2026-04-17 — Added `@contextmanager def _conn()` and public `connection()` wrapper (WAL + busy_timeout pragmas, auto-commit, auto-rollback). Call sites consolidated. Three new tests in `test_project_memory.py::TestConnectionContextManager` cover pragmas, commit-on-exit, rollback-on-exception.

---

## 7. Migrations

**[MG-01]** `migrations/_0001_*` – `_0016_*` — ✅ FIXED 2026-04-17 — Audit of all 14 migrations confirmed uniform template already in place (version check → DDL with `IF NOT EXISTS` / `PRAGMA table_info` guards → version insert → commit). No semantic changes needed; idempotency is now enforced by automated test.

**[MG-02]** — ✅ FIXED 2026-04-17 — `tests/unit/test_migration_double_apply.py` parametrized over the full migration registry (14 cases, 1.0.0 through 1.9.6). Each case applies the migration twice and asserts (a) no exception, (b) schema snapshot unchanged on re-apply, (c) exactly one `schema_version` row per version.

---

## 8. Tests

Remaining gaps and flakes (separate from the targeted fixes above):

- **[TEST-01]** ✅ FIXED 2026-04-17 — `tests/unit/test_shadow_worker_recovery.py` adds 5 tests: heartbeat write, orphan marking after timeout, non-silent `running` state, clean broker reopen, fake-datetime progression.
- **[TEST-02]** ✅ FIXED 2026-04-17 — `tests/unit/test_fix_generator_rollback.py` adds 8 tests covering Python/JS/TS syntax-invalid fixes — each asserts rollback, original file restored, and no `.muscle.bak`/`.muscle.tmp` stragglers.
- **[TEST-03]** ✅ FIXED 2026-04-17 — `tests/integration/test_concurrent_review.py` runs 3 `ReviewController.run()` calls via `ThreadPoolExecutor(max_workers=3)` with a 30s deadlock cap; asserts distinct session IDs and no NUL corruption.
- **[TEST-04]** ✅ FIXED 2026-04-17 — see MG-02.
- **[TEST-05]** ✅ FIXED — `tests/integration/test_shadow_nightly.py` has been rewritten against the current `ProjectMemory`-backed `ShadowBroker`; no `SHADOW_JOBS_FILE` references remain.
- **[TEST-06]** ✅ FIXED 2026-04-17 — `test_evolver.py` now uses an autouse `_isolate_home` fixture that sandboxes `HOME` per test; all `Evolver(...)` constructions already pass `use_kb=False`.
- **[TEST-07]** ✅ FIXED 2026-04-17 — `TestMemoryGroup` (4), `TestProbeCommand` (2), `TestDiagnosisCommand` (2) all hardened with `monkeypatch.chdir(tmp_path)`.
- **[TEST-08]** ✅ FIXED 2026-04-17 — `TestAgentsGroup::test_agents_list_no_dir` rewritten to use `CliRunner().isolated_filesystem()`.
- **[TEST-09]** ✅ FIXED 2026-04-17 — `TestTuiCommand::test_tui_runs` now patches `readchar.readkey` at source-module level with `return_value="q"` and `catch_exceptions=False`.
- **[TEST-10]** ✅ FIXED 2026-04-17 — `test_relatedness_explanation_surfaces_overlap_reasons` now passes; verified in local pytest run.

---

## 9. Docs

**[DOC-03]** `MUSCLE_PLAN.md` — ✅ FIXED 2026-04-17 — 🟡 Low — Phases not labelled current vs speculative
- *Fix:* Mark each phase with a status line (`status: shipped | in-progress | planned`) and a date; cross-reference the open finding IDs in this document.

---

## 10. Packaging / ops

**[PKG-02]** `pyproject.toml` — ✅ FIXED 2026-04-17 — 🟡 Low — Consider `uv.lock` hygiene
- *Fix:* `uv.lock` already committed; documented `uv sync --frozen --extra dev` flow for release builds in `CLAUDE.md`.

**[PKG-03]** `pyproject.toml` — ✅ FIXED 2026-04-17 — 🟡 Low — mypy env mismatch risk
- *Fix:* Documented `uv run mypy` as the only supported invocation in `CLAUDE.md` with reasoning.

**[CHK-01]** `muscle check --target <single file>` — ✅ FIXED 2026-04-17 — 🟡 Low / UX — Fails with `[Errno 20] Not a directory` on file inputs despite help text advertising file support
- *Fix:* `detect_language` now handles file inputs via extension lookup; `check` command resolves file → parent dir for evaluation and infers language from extension.

---

## Pre-release verification plan

Before tagging a release, run in order:

```bash
uv sync --frozen --extra dev
uv run ruff check tools/muscle/
uv run ruff format --check tools/muscle/
uv run mypy tools/muscle/
uv run pytest tests/ -v
```

Smoke tests (against a scratch directory):

1. `muscle run --task "hello world script"` — confirm no dangling `.bak`, `meta.json` survives a mid-iteration SIGTERM, `remaining_tokens` never goes negative.
2. `muscle review --path <sample>` — confirm committee dedup, auto-fix blocked on syntax-invalid LLM output, handoff markdown passes a CommonMark validator.
3. Concurrent stress: three `muscle review` calls against the same project simultaneously — shadow queue must not deadlock; no orphaned `running` jobs after killing a worker with `SIGKILL` (covers TEST-01).
4. Plugin lint: assert every `/muscle:*` entry in `plugin.json` has a matching file under `commands/` and vice-versa (covers PL-03).

---

## Agent handoff format

Each entry above is dispatchable as:

```
Fix <ID>: <title>
- File: <path>:<line>
- Severity: <🔴/🟠/🟡>
- Task: <recommendation verbatim>
- Acceptance: <existing test path OR new test to add>
- Do not change: <files/modules out of scope>
```

For any remaining 🔴 item, the merge criterion is a passing regression test that
demonstrates the previous failure mode is eliminated.
