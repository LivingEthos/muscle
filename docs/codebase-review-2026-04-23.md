# MUSCLE Codebase Review - 2026-04-23

## Scope

This review covers the current on-disk checkout at
`<repo-root>`. I did not change
production code. The only artifact produced by this pass is this review
document.

The working tree was not clean at review time. The branch was
`main...origin/main [behind 1]`, with 54 tracked files changed, multiple tracked
deletions, and new untracked modules/tests plus an untracked `muscle-main/`
directory. Findings below are therefore about the current working tree, not a
known released commit.

## What MUSCLE Is Trying To Be

MUSCLE is a local-first, self-learning code review and code generation companion
centered on MiniMax M2.7. It has two primary loops:

1. `muscle run`: Generate -> Evaluate -> Evolve -> Repeat for code creation.
2. `muscle review`: Static review -> Semantic review -> Fix or handoff -> Verify -> Learn.

The project goal is strong: keep project-local memory authoritative, learn from
validated fixes/reviews, optionally reuse related-project/model-pack lessons,
and provide plugin surfaces for Claude/Codex while using M2.7 for cheaper bulk
execution.

Major implemented areas:

- CLI orchestration in `src/muscle/cli.py`.
- MiniMax Anthropic-compatible client, rate limiting, caching, and telemetry in
  `src/muscle/m27_client.py`.
- Generate/evaluate/evolve loop in `src/muscle/loop_controller.py`.
- Review/fix/verify/learn pipeline in `src/muscle/code_review/`.
- Project-local SQLite memory in `src/muscle/project_memory.py` and migrations.
- Plugin command bundles under `src/muscle/plugin/`.
- TUI/project setup support under `src/muscle/tui/`.

The architecture is ambitious and coherent, but the codebase is now large enough
that a few safety contracts are drifting: isolated execution, validation
strictness, language support claims, and scope filtering are the highest-risk
areas.

## Quality Gates Run

I first ran `uv run` checks and found the dev tools missing from the fresh
environment. I then ran `uv sync --extra dev` to install the declared optional
dev dependencies.

Results after syncing:

| Command | Result |
|---|---|
| `uv run ruff check src/muscle/` | Passed |
| `uv run ruff format --check src/muscle/` | Failed: `src/muscle/delegation_metrics.py` and `src/muscle/migrations/_0017_delegation_event_metadata.py` would be reformatted |
| `uv run mypy src/muscle/` | Failed: `src/muscle/code_review/__init__.py:76` missing return type annotation |
| `uv run pytest tests/ -q` | Passed: `2139 passed, 3 skipped in 174.83s` |

Test run caveat: after pytest printed its passing summary, background worker
logs continued briefly:

- `Default job processor failed: API key is required...`
- `Worker thread did not stop gracefully`

The process still exited with code 0, but this points to a test/process cleanup
gap around shadow worker lifecycle.

## Findings

### P1. Isolated worktree mode appears to reject its own mapped target

`ReviewController.run()` validates target containment before it dispatches to
worktree mode:

- `src/muscle/code_review/review_controller.py:304`
- `src/muscle/code_review/review_controller.py:366`

In `_run_in_isolated_worktree()`, the controller maps the target into the temp
worktree, then builds a child controller with `target_path=mapped_target` but
still passes `project_path=self.project_path`:

- `src/muscle/code_review/review_controller.py:403`
- `src/muscle/code_review/review_controller.py:410`
- `src/muscle/code_review/review_controller.py:416`
- `src/muscle/code_review/review_controller.py:423`
- `src/muscle/code_review/review_controller.py:426`

The child controller then runs the same containment check and compares the temp
worktree path against the original repository root. That should raise
`ValueError` for normal temp worktree paths.

Impact: `execution_mode="worktree"` for auto-fix/hybrid can fail before doing
the very safety-isolated work it is meant to provide.

Recommendation: have the child controller use the worktree root as its
`project_path`, while retaining original-root metadata separately for remapping
artifacts and applying deltas. Add an integration test that exercises the real
`ReviewController.run()` worktree path rather than only helper behavior.

### P1. Verification can accept fixes the semantic verifier rejected

The verifier prompt asks M2.7 to answer `VERIFIED`, `BREAKS`, or `NEEDS_WORK`:

- `src/muscle/code_review/verification_loop.py:203`

But the code only fails on text containing `BREAKS` or `FAILS`:

- `src/muscle/code_review/verification_loop.py:133`
- `src/muscle/code_review/verification_loop.py:262`

`NEEDS_WORK` can fall through to local validation and become verified if syntax,
lint, and tests pass. The local validation checks also fail open on exceptions:

- `src/muscle/code_review/verification_loop.py:446`
- `src/muscle/code_review/verification_loop.py:472`
- `src/muscle/code_review/verification_loop.py:495`

Impact: a fix that the semantic verifier explicitly says is incomplete can be
recorded as verified and fed into the learning pipeline. Missing tools or
timeouts can also silently convert validation uncertainty into success.

Recommendation: parse the verifier status as a strict enum. Treat anything other
than explicit `VERIFIED` as non-verified. Local validator execution errors should
be represented as degraded/unknown and should not produce learning signals as if
the fix was validated.

### P1. Loop token accounting double-counts generation tokens and enforces budget late

`LoopController._run_iteration()` adds generation usage directly:

- `src/muscle/loop_controller.py:454`

It also returns the same `gen_usage.total` as `IterationResult.token_cost`:

- `src/muscle/loop_controller.py:480`
- `src/muscle/loop_controller.py:483`

Then `LoopController.run()` adds `iteration_result.token_cost` again:

- `src/muscle/loop_controller.py:714`
- `src/muscle/loop_controller.py:718`

Budget enforcement also happens after an iteration's generation/evaluation work,
using only `iteration_result.token_cost`:

- `src/muscle/loop_controller.py:762`

Impact: generation tokens are counted twice, while other model spend can be
handled inconsistently. Reports, cost tracking, webhook payloads, and budget
overspend events can be wrong. Budget limits can also be exceeded before the
system checks whether it should proceed.

Recommendation: make one layer own accounting. Prefer explicit per-call deltas
and check projected budget before every model call. Count generator, evolver,
reviewer, and verifier spend under one budget model.

### P1. Auto-fix validation is stricter than advertised language support and brittle for TypeScript

`FixGenerator._commit_fix()` stages fixed content as `<original suffix>.muscle.tmp`:

- `src/muscle/code_review/fix_generator.py:385`
- `src/muscle/code_review/fix_generator.py:386`

For TypeScript it then runs:

- `src/muscle/code_review/fix_generator.py:458`
- `src/muscle/code_review/fix_generator.py:460`

The staged path for `foo.ts` becomes `foo.ts.muscle.tmp`, which is likely not
treated as a TypeScript source file by normal tooling. For every language except
Python, JSON, JavaScript, and TypeScript, validation returns a hard failure:

- `src/muscle/code_review/fix_generator.py:462`
- `src/muscle/code_review/fix_generator.py:464`

Impact: auto-fix can fail for valid TypeScript fixes due to the temp suffix, and
advertised review/fix flows for Go, Rust, Java, C/C++, etc. cannot apply fixes
when compile verification is enabled.

Recommendation: preserve the original final suffix when staging, for example
`.muscle.tmp.ts`, or validate in a temporary mirror path with the real suffix.
For unsupported languages, either implement validators or mark the result as
"not locally verified" instead of treating the fix as a write failure.

### P1. Review scope filtering is declared but not enforced by static analysis

`ReviewConfig` exposes `include_patterns` and `exclude_patterns`:

- `src/muscle/code_review/types.py:132`
- `src/muscle/code_review/types.py:133`

`ReviewController` passes them to `StaticAnalyzer`:

- `src/muscle/code_review/review_controller.py:155`
- `src/muscle/code_review/review_controller.py:158`

`StaticAnalyzer` stores them and defines `_should_include()`:

- `src/muscle/code_review/static_analyzer.py:165`
- `src/muscle/code_review/static_analyzer.py:228`

But `analyze()` and `_run_tool()` do not call `_should_include()`. For directory
targets, tools run against the whole target directory:

- `src/muscle/code_review/static_analyzer.py:276`
- `src/muscle/code_review/static_analyzer.py:280`

Language detection also scans every nested file without applying default
exclusions:

- `src/muscle/code_review/static_analyzer.py:205`
- `src/muscle/code_review/static_analyzer.py:206`

Impact: user-configured scope controls can be silently ignored. Large directories
such as `.venv`, `.git`, generated artifacts, or the untracked `muscle-main/`
copy can skew language detection and static analysis.

Recommendation: centralize scope resolution once, produce a filtered file list,
and pass either tool-native filters or temporary target manifests to analyzers.
Add tests that prove excluded files are not analyzed, not just that patterns are
stored.

### P1. Semantic review scans too broadly and hides per-file failures

When static analysis produces no issues, `CodeReviewer.review()` recursively
adds all files matching many source extensions:

- `src/muscle/code_review/code_reviewer.py:422`
- `src/muscle/code_review/code_reviewer.py:429`
- `src/muscle/code_review/code_reviewer.py:442`

This does not appear to apply ignore rules for `.git`, `.muscle`, `.venv`,
`node_modules`, generated outputs, or duplicate repo copies.

If a per-file review future raises, the exception is only logged:

- `src/muscle/code_review/code_reviewer.py:483`
- `src/muscle/code_review/code_reviewer.py:499`

The summary returned to callers does not count failed/skipped files.

Impact: "clean" review summaries can hide review failures. Proactive review can
also become expensive or noisy on repositories with vendored, generated, or
duplicated code.

Recommendation: reuse a shared scope classifier for static and semantic review,
cap proactive file counts by profile, and include `files_failed`,
`files_skipped`, and `scope_limited` in review summaries/artifacts.

### P2. Java and C# evaluator registration falls back to dummy evaluators

The evaluator registry advertises Java and C# mappings:

- `src/muscle/evaluator_registry.py:31`
- `src/muscle/evaluator_registry.py:35`

But `_load_evaluator()` has no cases for `javac_compiler`, `junit_runner`,
`checkstyle_linter`, `csc_compiler`, `nunit_runner`, or `dotnet_linter`:

- `src/muscle/evaluator_registry.py:108`
- `src/muscle/evaluator_registry.py:184`
- `src/muscle/evaluator_registry.py:185`

Some Java/dotnet evaluator classes exist under `src/muscle/evaluators/`, but
they are not wired into the registry.

Impact: `muscle check --language java` and generated/evaluated Java/C# sessions
can silently use the dummy evaluator and report success without meaningful
validation.

Recommendation: wire existing evaluators, implement missing ones, or explicitly
remove/mark unsupported language mappings until real evaluators exist. Add a
test that every `LANGUAGE_EVALUATORS` entry loads at least one non-dummy
evaluator.

### P2. `muscle run --language` is not included in generation prompts

The CLI builds an evaluator with `config.language`:

- `src/muscle/cli.py:1328`
- `src/muscle/cli.py:1332`

But the code-generation wrapper does not pass the language to `CodeGenerator`:

- `src/muscle/cli.py:1334`
- `src/muscle/cli.py:1340`
- `src/muscle/cli.py:1344`

`CodeGenerator.generate()` calls `_build_user_prompt()` with `language=None`:

- `src/muscle/code_generator.py:221`
- `src/muscle/code_generator.py:225`

Impact: the generator may create code in a different language than the evaluator
or user requested unless the task text itself repeats the language.

Recommendation: add a `language` parameter to `CodeGenerator.generate()` and
`generate_streaming()`, pass it from `RunConfig`, and include it in the cache key
so cached output cannot cross language boundaries.

### P2. Generated-file tracking is shallow and misses modified/deleted nested artifacts

`LoopController._run_iteration()` snapshots only top-level names under the output
directory:

- `src/muscle/loop_controller.py:386`
- `src/muscle/loop_controller.py:396`
- `src/muscle/loop_controller.py:399`

After generation, it again compares only top-level names:

- `src/muscle/loop_controller.py:470`
- `src/muscle/loop_controller.py:478`

Impact: nested generated files, modified existing files, and deletions are not
reflected in `files_generated` or downstream session reports. This weakens
session persistence, artifact auditability, and auto-commit evidence.

Recommendation: take a recursive relative-path snapshot with content hashes,
excluding caches and build outputs. Report added, modified, and deleted files.

### P2. GolangCI parser and tests encode the wrong file path contract

`_parse_golangci_json()` sets `file_path` from `FromLinter`:

- `src/muscle/code_review/static_analyzer.py:473`
- `src/muscle/code_review/static_analyzer.py:480`

The unit test expects this behavior:

- `tests/unit/test_static_analyzer.py:494`
- `tests/unit/test_static_analyzer.py:513`

But `FromLinter` is the linter/rule source, not the source filename. Modern
golangci-lint JSON reports location under a `Pos` object; older shapes may use a
file/location field, but not `FromLinter` as the source file.

Impact: Go findings can point to `golint` or another linter name instead of the
actual file, making handoff and auto-fix routing wrong.

Recommendation: parse `Pos.Filename` and `Pos.Line`, tolerate legacy fields, and
change the test to assert source file paths.

### P2. Host-doc publishing backs up only `CLAUDE.md`, even when writing `AGENTS.md`

`ClaudePublisher` defaults to publishing identical content to both `CLAUDE.md`
and `AGENTS.md`:

- `src/muscle/claude_publisher.py:88`
- `src/muscle/claude_publisher.py:95`

Before every target write, it calls:

- `src/muscle/claude_publisher.py:412`
- `src/muscle/claude_publisher.py:416`

`BackupManager` resolves `claude_md` backups to the root `CLAUDE.md` only:

- `src/muscle/backup_manager.py:469`
- `src/muscle/backup_manager.py:470`

Impact: writing `AGENTS.md` is not backed up as advertised. In an AGENTS-only
project, publishing can skip `AGENTS.md` because backing up `CLAUDE.md` fails.

Recommendation: add a generic single-file host-doc backup path, or extend the
backup type to carry the actual target file.

### P2. Structured workflow fallback can rerun after partial side effects

`ReviewController.run()` catches all structured workflow exceptions and falls
back to legacy review modes:

- `src/muscle/code_review/review_controller.py:322`
- `src/muscle/code_review/review_controller.py:329`
- `src/muscle/code_review/review_controller.py:330`

Impact: if a structured workflow applied fixes or wrote artifacts before a later
node failed, fallback can run a second review/fix pass over a partially changed
tree. That undermines reproducibility and safety.

Recommendation: allow fallback only before mutating workflow nodes. After any
write/fix stage, surface the structured workflow failure with artifact pointers
or roll back via worktree/session transaction before fallback.

### P2. M27 client limiter configuration is process-global and first-client-wins

`M27Client` stores rate and concurrency limiters as class-level state. It only
configures them if `_rate_limiter` is `None`:

- `src/muscle/m27_client.py:262`
- `src/muscle/m27_client.py:264`

Environment values are parsed directly:

- `src/muscle/m27_client.py:265`
- `src/muscle/m27_client.py:266`

`RateLimiter` divides by `calls_per_second` without validation:

- `src/muscle/m27_client.py:96`
- `src/muscle/m27_client.py:99`

Impact: the first client constructed in a process silently controls all later
clients, even if a command requests different limits. Invalid env values can
raise at startup, and a zero rate can divide by zero.

Recommendation: validate env/config values, clamp or reject invalid limits, and
either document singleton limiter semantics or support explicit reconfiguration
for command-scoped clients.

### P2. Plugin install script can report success while leaving no runnable `muscle`

The Claude plugin manifest embeds a one-line install script:

- `src/muscle/plugin/.claude-plugin/plugin.json:13`
- `src/muscle/plugin/.claude-plugin/plugin.json:14`

It installs with `uv pip install -e .` or `python -m pip install -e .`, then
creates a symlink to `${INSTALL_DIR}/.venv/bin/muscle` only in the fresh-clone
path. `uv pip install -e .` does not by itself guarantee that `${INSTALL_DIR}/.venv`
exists, and the pip fallback may install into a different environment. The
symlink command is also skipped if `$HOME/.local/bin/muscle` already exists.

Impact: plugin installation can print success while the CLI is not on PATH or
the symlink points at a non-existent virtualenv script.

Recommendation: use `uv tool install`, `uv venv && uv pip install`, or
`python -m pipx` style installation with an explicit executable check at the end:
`command -v muscle && muscle --version`.

### P3. `muscle check` on a file evaluates the parent directory

For a file target, the CLI infers language from the suffix but sets
`eval_target` to the parent directory:

- `src/muscle/cli.py:1757`
- `src/muscle/cli.py:1762`

Impact: `muscle check --target src/foo.py` can fail or pass based on unrelated
files in `src/`. It does not perform the narrow validation implied by the file
target.

Recommendation: update evaluators to accept a file target where possible, or
rename CLI messaging to make the parent-directory behavior explicit.

### P3. TUI language detection has a glob bug for extension-only projects

`ProjectManager._detect_languages()` turns `"*.py"` into `".py"` before calling
`rglob()`:

- `src/muscle/tui/project_manager.py:93`
- `src/muscle/tui/project_manager.py:106`
- `src/muscle/tui/project_manager.py:107`

Impact: projects with source files but no package metadata can miss language
detection for Python and CMake/C++ indicators.

Recommendation: call `path.rglob(pattern)` for glob patterns.

### P3. `.muscle/config.yaml` is still written as JSON

`ProjectManager` defines:

- `src/muscle/tui/project_manager.py:23`

It writes the file with `json.dump()`:

- `src/muscle/tui/project_manager.py:134`
- `src/muscle/tui/project_manager.py:157`

It also reads updates with `json.load()`:

- `src/muscle/tui/project_manager.py:409`
- `src/muscle/tui/project_manager.py:411`

`TuiDataProvider` now documents the ambiguity and supports JSON first, then YAML:

- `src/muscle/tui/data_provider.py:112`
- `src/muscle/tui/data_provider.py:129`

Impact: users and external tools reasonably expect YAML from the extension.
Tests currently lock in the JSON-in-YAML-file behavior.

Recommendation: migrate to `config.json` with compatibility, or write actual
YAML while accepting existing JSON.

### P3. Documentation and index drift

Examples:

- README "More docs" links point to `<absolute-user-path>/...`
  absolute paths instead of repo-relative paths:
  `README.md:227`.
- `PROJECT_INDEX.md` lists `pressure_reviewer.py`, but that file is not present
  in the active tree:
  `PROJECT_INDEX.md:37`.
- `PROJECT_INDEX.md` says the 2026-04-17 baseline has ruff + format clean and
  mypy has four pre-existing errors:
  `PROJECT_INDEX.md:102`.
  The current checkout instead has ruff check clean, format failing on two files,
  and mypy failing on one missing return type.

Impact: contributors can follow stale links or trust stale quality-baseline
claims.

Recommendation: keep the project index generated or add a docs consistency test
for file references and absolute local paths.

### P3. Repo hygiene increases review and tool noise

The checkout contains a dirty working tree, deleted planning docs, many modified
tests/modules, and an untracked `muscle-main/` directory. The active package is
already about 50,335 Python LOC under `src/muscle/`, with several very large
modules:

- `src/muscle/cli.py`: 5,363 lines
- `src/muscle/project_memory.py`: 3,916 lines
- `src/muscle/code_review/review_controller.py`: 1,511 lines
- `src/muscle/code_review/code_reviewer.py`: 1,174 lines
- `src/muscle/m27_client.py`: 1,046 lines

Impact: broad recursive scanners and semantic review paths are more likely to
scan unintended code. Large orchestration modules also make regression isolation
harder.

Recommendation: remove or ignore duplicate repo copies, commit or separate the
current working set, and gradually split large modules by stable boundaries
without removing features.

## Mechanism Improvements That Preserve Features

1. Add a shared `ReviewScope` object used by static analysis, semantic review,
   fix generation, artifact capture, and code-generation context. It should own
   include/exclude rules, ignore defaults, and file caps.

2. Introduce a `ValidationStatus` enum: `passed`, `failed`, `skipped`,
   `unknown`, `errored`. Use it for fix validation, verification loop, evaluator
   registry, and release evidence. Avoid converting "tool unavailable" into
   success.

3. Make execution isolation transactional. Worktree execution should have a
   clear project root, temp root, baseline snapshot, mutation phase, apply-back
   phase, and cleanup phase. Fallback should not cross a mutation boundary unless
   rollback succeeds.

4. Consolidate token/cost accounting. One subsystem should receive every M2.7
   call usage event and derive session totals, budget warnings, delegation
   metrics, and webhook payloads from the same source.

5. Add contract tests for "advertised surface area": every plugin command should
   map to a CLI command, every registered evaluator should instantiate or be
   explicitly unsupported, every config field should affect behavior, and every
   public language mode should have at least one meaningful validation path.

6. Treat learning as safety-sensitive. Only validated fixes and reviews with
   complete scope/error accounting should update durable project memory or model
   pack candidates.

## Suggested Fix Order

1. Fix the two quality gate failures: ruff format drift and the missing mypy
   return annotation.
2. Fix worktree containment so isolated auto-fix/hybrid works.
3. Make verifier status strict and stop failing open on local validator errors.
4. Correct token accounting and add a budget regression test.
5. Enforce scope filters across static and semantic review.
6. Wire or de-advertise Java/C# evaluators and fix GolangCI parsing.
7. Fix `CodeGenerator` language propagation and cache keying.
8. Repair host-doc backup behavior for `AGENTS.md`.
9. Harden plugin installation with an end-to-end executable check.
10. Clean docs/index drift and add docs consistency checks.

## Tests To Add

- Worktree auto-fix/hybrid integration test that actually enters
  `_run_in_isolated_worktree()` and verifies child containment passes.
- Verification tests for `NEEDS_WORK`, empty verifier output, missing tools, and
  timeout behavior.
- Budget accounting test with generator and evolver token usage in the same
  iteration.
- Static analyzer include/exclude behavior test that proves excluded files are
  not handed to tools.
- CodeReviewer proactive review test with ignored directories and a per-file
  exception that must be surfaced in summary.
- Evaluator registry coverage test for every name in `LANGUAGE_EVALUATORS`.
- `muscle run --language typescript` prompt/cache test.
- Host-doc publish test for AGENTS-only projects.
- Plugin install lifecycle test that checks `command -v muscle` after install.

## Bottom Line

The codebase has the right product shape: a review companion that learns from
verified outcomes, preserves local project ownership, and exposes practical CLI
and plugin workflows. The biggest risks are not missing features; they are
feature contracts that look wired but are partially bypassed: worktree isolation,
scope filters, strict verification, language-specific validation, and accounting.

Fixing those contracts should make the existing feature set safer without
removing capabilities.
