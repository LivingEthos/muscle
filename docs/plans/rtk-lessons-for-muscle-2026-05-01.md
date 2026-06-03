# RTK Lessons for MUSCLE

Source inspected: `https://github.com/rtk-ai/rtk` at commit
`4338f029ec43b69eb959748ec02cd7885200c264`.

This is a research note only. No MUSCLE code was changed.

## Summary

RTK is not a code-review engine. It is a command-output proxy that compresses
terminal output before it reaches an LLM context. The useful lesson for MUSCLE
is therefore operational: make every analyzer, verifier, hook, and host-facing
surface produce compact, structured, recoverable evidence instead of raw noisy
logs.

MUSCLE already has project memory, LLM-call telemetry, review artifacts, and
prompt compaction. RTK's strongest missing patterns are:

- a first-class raw-output to compact-output contract
- parser degradation tiers instead of silent fallback
- full-output recovery hints for truncated or failed tool runs
- adoption and missed-opportunity analytics over host sessions
- trust and integrity checks around hook-installed behavior
- simple declarative filters with inline tests for boring output cleanup

## Borrow Now

### 1. Add a `CommandEvidence` contract

RTK routes commands through one skeleton: execute, filter, print, track, and
preserve exit code. MUSCLE's evaluators and static analyzers currently return
lists of strings or `StaticAnalysisResult` objects, with local truncation but no
shared evidence shape.

MUSCLE should add a small internal type used by evaluator/static-analyzer
execution:

- `command`
- `cwd`
- `exit_code`
- `duration_ms`
- `raw_stdout_path`
- `raw_stderr_path`
- `compact_stdout`
- `compact_stderr`
- `parser_tier`
- `tokens_raw_estimate`
- `tokens_compact_estimate`
- `warnings`

This should feed `.muscle/review_artifacts/<session>/` and the existing
project-memory telemetry. It does not need to become a public RTK-style proxy.

### 2. Make parser tiers explicit

RTK's parser model is useful: full structured parse, degraded parse with
warnings, then passthrough. MUSCLE already prefers JSON for Ruff, Pyright,
Bandit, ESLint, and related analyzers, but JSON parse failures often degrade
quietly.

For MUSCLE, every analyzer parser should return:

- `FULL`: structured JSON or validated machine-readable format
- `DEGRADED`: regex or partial extraction, with warning text
- `PASSTHROUGH`: no trusted parse, raw output saved and compacted only

This is a good fit for `tools/muscle/code_review/static_analyzer.py`,
`tools/muscle/evaluators/base.py`, and the review artifact manifest.

### 3. Save full output whenever MUSCLE truncates

RTK's tee mechanism is the most directly useful feature. When output is
truncated or parsing fails, RTK writes full raw output to disk and prints a
short recovery pointer.

MUSCLE should do the same inside review artifacts. If an evaluator caps output
at 20K chars or a test parser keeps only the first 20 failures, the artifact
should include the raw output file path and a compact hint in the summary.

This would improve review follow-up because the host can inspect evidence
without rerunning expensive or flaky commands.

### 4. Turn token-savings telemetry into a user-facing command

RTK's `gain` command makes savings visible. MUSCLE already has `llm_calls`,
`token_savings_ledger`, prompt compaction metrics, and benchmark evidence, but
the value is scattered.

Add a focused `muscle savings` or extend `muscle status --refresh` with:

- LLM input/output tokens by stage
- prompt compaction savings
- analyzer output compaction savings once `CommandEvidence` exists
- cache hit impact
- recent high-cost stages
- parse failure/degradation counts

This should be local and project-owned, not anonymous product telemetry.

### 5. Add host-session discovery for missed opportunities

RTK's `discover` scans Claude Code JSONL sessions to find commands that could
have used RTK. MUSCLE's equivalent would be more valuable if it looked for
missed review/check opportunities:

- code edits followed by no `muscle review`
- repeated failed test/lint commands that could be captured as project memory
- direct host fixes to files MUSCLE had open findings for
- review runs where static analyzers were missing from PATH
- repeated CLI mistakes worth publishing into project guidance

This should start read-only and write a report, not auto-edit memory.

### 6. Add a small declarative output-filter layer

RTK has TOML filters for simple line cleanup with inline tests. MUSCLE does not
need RTK's broad command catalog, but it would benefit from a project-local
filter format for evaluator outputs that are too boring for Python parser code.

Conservative scope:

- support strip/keep regexes, line caps, short-circuit success messages, and
  inline tests
- load built-ins first; allow project-local filters only after trust or explicit
  CLI flag
- never let filters hide failure indicators without an `unless` guard

Use this for formatter/package-manager/noise-heavy logs, not semantic review.

### 7. Harden hook and plugin lifecycle with integrity checks

RTK treats installed hooks as security-sensitive artifacts: idempotent install,
hash verification, audit reporting, and explicit permission precedence.

MUSCLE's plugin work should borrow the spirit, not the shell rewrite behavior:

- `muscle doctor` should verify plugin manifests, hook files, and expected
  command docs
- hook actions should fail open but record degraded state
- generated host assets should have digest checks in project memory
- local hook expansion should keep clear platform-specific capability notes

## Do Not Borrow Blindly

- Do not make MUSCLE a broad shell-command proxy. RTK already owns that product
  surface, and MUSCLE's value is review, verification, learning, and memory.
- Do not auto-rewrite arbitrary host commands. For MUSCLE, explicit review/check
  workflows are safer than invisible interception.
- Do not adopt global anonymous telemetry. MUSCLE should keep project-local
  evidence as the default and make any external sharing explicit.
- Do not compact source context aggressively before semantic review unless a
  benchmark gate proves quality does not regress.

## Suggested Implementation Order

1. `CommandEvidence` and raw-output artifact writing for evaluators.
2. Parser-tier status for static analyzers and evaluator parsers.
3. Compact analyzer/test summaries with full-output recovery hints.
4. `muscle savings` backed by existing telemetry plus command-output savings.
5. Read-only `muscle discover` for missed review/check opportunities.
6. Trust-gated declarative filters with inline tests.

The first three items are the highest leverage because they reduce host-context
noise while improving evidence quality and rerunability.
