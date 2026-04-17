# MUSCLE — Remaining Pre-Release TODOs

**Date:** 2026-04-17 (updated)
**Status:** All 7 🔴 High items resolved 2026-04-17. All 20 🟠 Medium items resolved 2026-04-17
(commit 58b9710). Features B.3/B.4/B.5 shipped same session. 2004 tests pass on `main`.
Remaining work is 🟡 Low only.
**Scope:** Only items still open or unverified are listed here. Each entry is
self-contained and dispatchable to a remediation agent using the handoff format
at the bottom of this file.

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

**[PL-02]** `tools/muscle/plugin/` `CLAUDE.md` and misc docs — 🟠 Medium / Stale Docs — Non-existent `muscle shadow …` and `muscle settings platform --hooks` flows still referenced
- *Fix:* Audit every `.md` under `tools/muscle/plugin/` for CLI examples that no longer exist; remove or rewrite; add a CI check that every `muscle …` example in plugin docs maps to a live `--help` subcommand.

**[PL-03]** `tools/muscle/plugin/commands/` — 🟠 Medium / Stale Docs — `nightly-status.md` exists but isn't advertised; ensure single source of truth
- *Fix:* Decide between "filesystem is truth" (generate the `plugin.json` description from the `commands/` directory at build time) or "manifest is truth" (trim `commands/` to match). Recommend filesystem-as-truth so new commands self-advertise.

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

**[PM-01]** `project_memory.py` (multiple) — 🟠 Medium / Code Quality — ~15 repeated `try / conn = sqlite3.connect(...) / finally: conn.close()` blocks
- *Fix:* Add `@contextmanager def _conn(self): …` + `_with_connection(fn)` helper; migrate all call sites. Keeps the WAL/busy_timeout pragma in one place.

---

## 7. Migrations

**[MG-01]** `migrations/_0001_*` – `_0012_*` — 🟠 Medium / Code Quality — Idempotency patterns inconsistent
- *Why:* Some migrations rely on `schema_version`, some on `IF NOT EXISTS` only; running twice is unsafe on a subset.
- *Fix:* Adopt a single template: `version check → run → version insert` wrapped in `BEGIN; … COMMIT;`; refactor each migration to match.

**[MG-02]** — 🟠 Medium / Test Gap — No double-apply tests
- *Fix:* Parametrized test that applies each migration twice against a fresh `sqlite3` DB and asserts no error + idempotent schema.

---

## 8. Tests

Remaining gaps and flakes (separate from the targeted fixes above):

- **[TEST-01]** 🟠 Shadow worker crash / recovery / heartbeat tests
  - Kill a worker mid-job, reopen the broker, assert the job is marked `orphaned` after the timeout and not silently stuck in `running`.
- **[TEST-02]** 🟠 Fix-verification tests
  - Exercise `FixGenerator.apply_fix` against Python / JS / TS inputs that deliberately fail their syntax check; assert rollback + no `.bak`.
- **[TEST-03]** 🟠 Concurrent review tests
  - Spawn 3 `ReviewController.run()` calls against the same project; assert no deadlock, no crossed-write on `MEMORY.md`, and all sessions complete.
- **[TEST-04]** 🟠 Migration double-apply (see MG-02).
- **[TEST-05]** 🟠 `tests/integration/test_shadow_nightly.py` still imports the removed `SHADOW_JOBS_FILE` constant (6 references). Rewrite against the current `ProjectMemory`-backed `ShadowBroker`. (From the 2026-04-04 evaluation, still open.)
- **[TEST-06]** 🟠 `TestEvolver` fixtures — pass `use_kb=False` (or a `tmp_path`-scoped KB) so tests don't reach the real `~/.muscle/knowledge/strategies.db` in sandboxed environments. (From the 2026-04-04 evaluation, still open.)
- **[TEST-07]** 🟠 `TestMemoryGroup` / `TestProbeCommand` / `TestDiagnosisCommand` — mock `ProjectMemory` / `ShadowBroker` construction so they don't depend on CWD having `.muscle/project_memory.db` writable. (From the 2026-04-04 evaluation, still open.)
- **[TEST-08]** 🟡 `TestAgentsGroup::test_agents_list_no_dir` — use an isolated `CliRunner` working directory so the test doesn't pick up the real repo's `.muscle/agents/`. (From the 2026-04-04 evaluation, still open.)
- **[TEST-09]** 🟡 `TestTuiCommand::test_tui_runs` — mock `readkey` at the module level so the TUI test survives `CliRunner`'s non-TTY stdin. Currently fails with `io.UnsupportedOperation: fileno`. (From the 2026-04-04 evaluation, still open.)
- **[TEST-10]** 🟡 `test_cross_project_learning.py::test_relatedness_explanation_surfaces_overlap_reasons` and `test_cli_model_memory.py::test_memory_related_command_surfaces_registered_overlap` — both assert `"fastapi"` appears in the relatedness summary, but `project_fingerprint.explain_relatedness` currently only surfaces `languages` and `shape`. Either extend the summary to include deps or update the tests. (Observed in the 2026-04-16 pytest run.)

---

## 9. Docs

**[DOC-03]** `MUSCLE_PLAN.md` — 🟡 Low — Phases not labelled current vs speculative
- *Fix:* Mark each phase with a status line (`status: shipped | in-progress | planned`) and a date; cross-reference the open finding IDs in this document.

---

## 10. Packaging / ops

**[PKG-02]** `pyproject.toml` — 🟡 Low — Consider `uv.lock` hygiene
- *Fix:* Commit `uv.lock` explicitly (if not already under VCS) and document the `uv sync --frozen` flow for release builds; the upper-bound pinning done in PKG-01 only helps if resolution is reproducible.

**[PKG-03]** `pyproject.toml` — 🟡 Low — mypy env mismatch risk
- *Fix:* Either pin mypy to a known-good version in `[project.optional-dependencies].dev` or document `uv run mypy` as the only supported invocation. (From the 2026-04-04 evaluation.)

**[CHK-01]** `muscle check --target <single file>` — 🟡 Low / UX — Fails with `[Errno 20] Not a directory` on file inputs despite help text advertising file support
- *Fix:* Either support file-level `check` in the linter dispatcher or scope the `--help` text to directories-only. (From the 2026-04-04 evaluation.)

---

## Pre-release verification plan

Before tagging a release, run in order:

```bash
uv sync --extra dev
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
