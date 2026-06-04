# MUSCLE v2 Snapshot vs Current App

Date: 2026-05-15

Compared sources:

- v2 snapshot: `<muscle-v2-snapshot>`
- current app: `<repo-root>`

Important context:

- The v2 snapshot is not a git repository. I treated it as a dated filesystem
  snapshot.
- The current checkout is dirty. I treated "current app" as the working tree,
  not just `HEAD`.
- The active current implementation is `tools/muscle/`; `tools/scle/` is legacy
  and excluded from this comparison.

## Executive Summary

MUSCLE v2 is a compact clean-architecture rewrite of the review engine. It has
better internal seams: async I/O, dependency injection, explicit provider
interfaces, in-memory repository mode, AST/cross-reference analyzers, custom
rules, file-level review caching, provider fallback, circuit breakers, and
diff-focused review primitives.

The current app is much larger and more operationally complete. It is no longer
just a review engine. It is a project-first harness around AI coding workflows:
CLI install/init/status, Claude and Codex plugin bundles, host memory publishing,
shadow/background review, isolated worktree fixes, long evals, model identity
and model packs, cross-project learning, command evidence, savings/discovery,
trust-gated filters, Visual DevFlow, and a large migration-backed project memory
database.

The short version:

- v2 is cleaner as a library and easier to reason about module by module.
- current is far more complete as a product, CLI, plugin, and self-learning
  workflow.
- v2 should not replace current wholesale. Its best pieces are architectural
  and analyzer/runtime slices that can be ported behind current contracts.
- The highest-value v2 imports are: async provider abstraction/fallbacks,
  in-memory no-db review mode, AST and cross-reference analyzers, rule engine,
  confidence scoring, targeted review cache, and diff review UX.

## Size and Surface Area

| Area | v2 snapshot | current app |
|---|---:|---:|
| Total tracked-ish files inspected | 145 | 421 |
| Python source files in app package | 82 under `src/muscle_v2` | 133 under `tools/muscle` |
| Python test files | 30 | 107 |
| Test cases collected | 235 | 2247 |
| Full test run in this pass | `uv run --extra dev pytest -q` succeeded | not run; collect-only succeeded |
| Top-level CLI commands | 4 (`review`, `learn`, `fix`, `config`) | 38 visible commands |
| Plugin command docs | 0 | 36 |
| Markdown docs | 11 | 87 |

The current app has roughly 7x the collected test surface and a much broader
user-facing command surface. v2 is a narrower engine prototype with concentrated
test coverage around the rewrite's internals.

## Packaging and Runtime Assumptions

v2 packages as `muscle-v2` with a `src/muscle_v2` layout, Python 3.11+, Typer,
async-first dependencies (`aiofiles`, `aiosqlite`, `httpx`), and direct provider
adapters.

Current packages as `muscle` with `tools.muscle` as the installed package,
Python 3.10+, Click, synchronous `requests`-based MiniMax access, and a large
plugin/docs/install lifecycle. Dependencies are pinned with upper bounds, which
is more conservative for release stability.

One current local packaging issue reproduced during inspection:

- `uv run muscle --help` can hit `ModuleNotFoundError: No module named 'tools'`
  from a stale editable console script.
- `uv pip install -e .` refreshed the editable install and restored CLI help.

That issue is already a known local release-prep footgun in this checkout; it is
not a v2-vs-current behavioral difference by itself, but it reinforces that the
current app has more release/lifecycle complexity.

## Architecture

### v2

v2 uses explicit clean architecture:

- `domain/`: entities, events, value objects, exceptions
- `application/`: orchestrator, event bus, review/learning/fix services
- `infrastructure/`: LLM adapters, repositories, filesystem, analyzers,
  circuit breaker, security, config, telemetry
- `cli/`: Typer entrypoint and DI container

The design is intentionally "no god classes." The largest source file is
`application/services/batch_reviewer.py` at 515 lines; most core classes are far
smaller. Dependencies flow through `DIContainer`, and the orchestrator receives
LLM, repository, filesystem, and event bus interfaces.

### current

Current uses a pragmatic subsystem architecture centered on `tools/muscle/cli.py`
and project-local runtime state:

- `cli.py`: one large command/router surface, 5689 lines
- `project_memory.py`: migration-backed SQLite facade, 3916 lines
- `code_review/`: review controller, semantic reviewer, fix generator,
  verification loop, learning pipeline, worktree manager, shadow jobs
- `plugin/`: Claude/Codex bundle, commands, hooks, assets, skills, agents
- `optimization/`: context budgeting, compaction, recording/import
- `migrations/`: schema evolution through `_0017_delegation_event_metadata.py`
- `tui/`, `adapters/`, `evaluators/`, `workflows/`, `model_packs`, etc.

Current has more real capability, but it is less modular. Several files are
large enough to slow change safety: `cli.py`, `project_memory.py`,
`review_controller.py`, `code_reviewer.py`, `m27_client.py`, and
`code_generator.py`.

### Practical contrast

v2 is a better base for a library-quality review core. Current is a better base
for a shipped tool. A rewrite toward v2 structure would improve maintainability,
but replacing current directly would discard a lot of hard-earned product and
workflow surface.

## CLI and Product Workflow

v2 CLI:

- `muscle review <project> --root ./src [--no-db] [--diff-base ...]`
- `muscle learn`
- `muscle fix`
- `muscle config show`

Current CLI:

- install/lifecycle: `init`, `enable`, `disable`, `status`, `settings`,
  `doctor`, `uninstall`
- review/check/fix: `review`, `check`, `lifeline`, `probe`, `diagnosis`,
  `long-eval`
- generation: `run`, `history`, `resume`, `abort`
- memory: `memory`, `notes`, `kb`, `skills`, `agents`, `backups`, `audit`
- optimization: `route`, `pack`, `optimize`, `optimize-host-docs`, `savings`,
  `discover`, `filters`, `cache`, `cost`, `model`
- UI/integration: `tui`, `visualize`, plugin slash commands

v2 has the cleaner command ergonomics for a narrow review engine. Current is the
actual operator tool.

## Review Pipeline

### v2 review pipeline

The v2 review path is straightforward:

1. `DIContainer` builds config, repository, filesystem, event bus, and LLM.
2. `ScopeService` resolves Python files, optionally from git diff.
3. `Orchestrator.review_project()` creates or loads a project.
4. `ReviewService.create_review()` reads files, builds one structured prompt,
   calls `LLMClient.complete()`, parses structured output, deduplicates, saves
   review state, and emits events.
5. Optional CLI interactive mode applies accepted suggestions.

Strengths:

- Easy to follow.
- Async and interface-driven.
- Supports memory-only `--no-db`.
- Structured-output parser is clear and provider-independent.
- Diff scope is first-class in `ReviewScope`.

Limits:

- It mostly reviews Python files in `ScopeService`.
- It does not yet wire all analyzers into the main review pipeline as deeply as
  the current app wires static analyzers, semantic review, verification, and
  learning.
- It has no current equivalent of shadow reviews, worktree execution modes,
  pressure workflows, host hooks, model packs, project-memory learning, or
  plugin command parity.

### current review pipeline

Current `ReviewController` coordinates:

- static analyzers (`ruff`, `pyright`, `bandit`, `eslint`, `tsc`,
  `svelte-check`, `golangci-lint`, `clippy`, `cppcheck`, `checkstyle`)
- M2.7 semantic review with structured JSON recovery
- pressure and fragility prompts
- smart/comprehensive review scope classification
- review workflow YAML DAG execution
- auto-fix, plan, hybrid, pressure modes
- verification before learning
- project memory recording and learning pipeline
- worktree execution and sync-back support
- artifacts, command evidence, trace policy, escalation records
- shadow/background job queues and diagnosis

Strengths:

- Much broader language/tool support.
- Much more complete run/review/fix/learn lifecycle.
- Release-facing evidence surfaces already exist.
- Plugin and host-memory workflows are wired to real commands.

Limits:

- The orchestration is complex and concentrated in large classes.
- It is harder to test or reuse as a library.
- Provider abstraction is mostly MiniMax/M2.7-specific rather than
  provider-agnostic.

## LLM and Provider Runtime

v2 has the better provider architecture:

- `LLMClient` interface with `complete`, `stream`, `health_check`,
  `provider_name`, `max_rpm`, and context-window helpers
- adapters for OpenRouter, Anthropic, OpenAI, MiniMax, Kimi, and Z.AI
- circuit breaker wrapper
- fallback wrapper
- retry middleware
- token budget wrapper and token budget model
- `TokenTracker`

Current has the better integrated MiniMax runtime:

- direct `M27Client` with shared `requests.Session`, retry/backoff, rate and
  concurrency limiters
- structured JSON calls with parser telemetry and response cache integration
- model identity resolution and provider endpoint introspection
- prompt compaction and telemetry context integration
- token savings ledger, cache metrics, and cost reporting

The best merge direction is not to port v2 wholesale. Current should keep its
telemetry/identity/cache behavior and introduce a provider interface layer
behind it. v2's `LLMClient` shape is a good starting point.

## Static Analysis and Code Understanding

v2 adds internal analyzers that current does not have in the same direct form:

- `ASTSecurityAnalyzer`: detects `eval`, `exec`, unsafe YAML/pickle,
  subprocess shell, SQL interpolation, hardcoded secrets, debug mode
- `CrossReferenceAnalyzer`: import graph, unused exports, circular imports,
  missing dependencies, inconsistent signatures
- `RuleEngine`: built-in and custom regex/AST rules with ReDoS checks
- `DiffAnalyzer`: changed-line extraction, new-secret/debug/TODO checks
- `BatchReviewer`: async per-file review with provider-aware concurrency
- `ConfidenceScorer`: confidence score by category, severity, context, pattern
  strength, and historical feedback

Current relies more on external tool integration plus M2.7 semantic analysis:

- external analyzers across Python, JS/TS, Svelte, Go, Rust, C/C++, Java
- parser tiers (`FULL`, `DEGRADED`, `PASSTHROUGH`)
- command evidence artifacts and raw-output recovery
- code-review prompts with severity, category, CWE, fixability, pressure modes
- proactive context windows and issue-centered prompt budgets
- source context fetching for packages

v2's internal analyzers would improve current as an additional cheap pre-pass.
Current's external analyzer/evidence stack is more mature for real projects.

## Fixing and Verification

v2:

- `AutoFixer` applies explicit suggestion fixes with git backup or `.bak`
  fallback.
- It validates path traversal and Python syntax before writes.
- It supports dry-run behavior and direct fix strategies like line replacement,
  find/replace, regex, and string replacement.

Current:

- `FixGenerator` asks M2.7 for full-file fixed code and validates syntax.
- `VerificationLoop` runs M2.7 semantic verification plus compiler/linter/test
  checks, reverts on failure, tracks verification results, and can emit
  escalations.
- Review modes split into review-only, auto-fix, plan, hybrid, and pressure.
- Worktree mode isolates fixes from the host checkout.
- Fix attempts and outcomes feed learning and review KB state.

v2 is simpler and safer for small targeted patches. Current is more suitable
for autonomous/hybrid workflow because it has verification, escalation, and
worktree isolation.

## Memory, Learning, and Storage

v2 storage is deliberately simple:

- SQLite tables: `projects`, `reviews`, `learning_entries`
- in-memory repositories for `--no-db`
- event bus for `ReviewCreated`, `LearningRecorded`, etc.
- learning service records category/content entries

Current storage is a mature project memory system:

- `.muscle/project_memory.db`
- migration framework through at least 17 migrations
- tasks, conversation events, review runs, findings, fix attempts, learned
  rules, memory decisions, skills, agents, shadow jobs, action logs,
  optimization records, cross-project learning, LLM calls, model identity,
  escalations, packs, delegation events, and more
- host publishing to `CLAUDE.md` and `AGENTS.md`
- project-first learning, related-project provisional overlays, model-pack
  overlays, promotion/archive flows

v2 has a cleaner repository abstraction. Current has the real data model. If
adopted, v2 repository interfaces should wrap current `ProjectMemory` instead of
creating a parallel storage path.

## Plugins, Host Integration, and Docs

v2 has no plugin bundle.

Current has:

- Claude plugin manifest and marketplace metadata
- Codex plugin manifest and assets
- nested hook files plus root hook metadata
- 36 slash-command docs
- rescue and verification subagents
- code-review skill
- wiki documentation database with YAML command/page/plugin catalogs
- release notes, privacy, security, terms, install scripts, examples, and public
  README presentation

This is the largest current advantage. v2 is an engine snapshot. Current is a
plugin-ready product.

## Observability and Evidence

v2 has basic metrics and a no-op telemetry placeholder. It has useful token
budget/tracking primitives, but limited product-facing evidence.

Current has:

- command evidence artifacts with raw output paths, compact output, parser
  tiers, token estimates, and truncation warnings
- `muscle savings`
- `muscle discover`
- trust-gated output filters with digest trust
- richer `muscle doctor`
- active-review snapshots
- Visual DevFlow bridge and `muscle visualize`
- response cache with hit counters and savings estimates

Current is ahead here. v2's token budget model could still strengthen current's
per-provider hard/soft limit handling.

## Validation Notes

Commands run during this comparison:

- Current `uv run muscle --help`: worked after `uv pip install -e .`
- v2 `uv run muscle --help`: worked and exposed 4 commands
- v2 `uv run --extra dev pytest --collect-only -q`: collected 235 tests
- v2 `uv run --extra dev pytest -q`: completed successfully
- Current `uv run pytest --collect-only -q`: collected 2247 tests

I did not run the current full suite in this pass. The current tree is dirty and
the full suite is much larger; collect-only was enough to compare test surface
without turning this into a release validation run.

## What v2 Has That Current Should Consider Borrowing

1. Provider-agnostic `LLMClient` interface

Current is deeply M2.7-shaped. A narrow adapter interface would make current's
model-routing ambitions cleaner without throwing away current telemetry.

2. Fallback provider wrapper

Current has routing and model identity, but not a simple primary/fallback chain
with health checks. This would be useful for review resilience.

3. Memory-only `--no-db` mode

Current is project-memory-first, which is right for learning. But CI, smoke
tests, and one-off audits would benefit from a no-persistence review path.

4. AST security analyzer

Cheap AST findings would reduce dependence on installed tools like Bandit and
could catch obvious security issues even when external analyzers are absent.

5. Cross-reference analyzer

Current's review scope classifier is strong, but it lacks a simple internal
import graph for "defined but not used", circular import, and signature drift
signals.

6. Custom rule engine

Current has output filters and learned rules, but not a general local rule
engine for regex/AST checks. This could bridge learned project memory into
deterministic local checks.

7. Confidence scorer

Current records evidence and outcomes, but review findings do not have a small,
consistent confidence model like v2's category/severity/history scorer.

8. Review cache

Current has response caching, but v2's file-content review cache is a simpler
primitive for skipping unchanged file-level review work.

9. Diff review UX

Current has changed-file/scope concepts, but v2's explicit
`--diff-base/--diff-target/--diff-context` CLI contract is clean and easy to
understand.

## What Current Has That v2 Does Not

1. Plugin lifecycle

Claude/Codex bundles, slash commands, hooks, assets, docs, doctor checks, and
install lifecycle are current-only.

2. Project memory maturity

Current's migration-backed database is far beyond v2's project/review/learning
tables.

3. Review modes and worktree safety

Review, auto-fix, plan, hybrid, pressure, shadow, lifeline, worktree execution,
and verification loops are current-only or much more mature in current.

4. Generate/evaluate/evolve loop

Current still has `muscle run`, sessions, history, resume, abort, evaluators,
strategy KB, budget manager, self-improver, and git auto-commit behavior.

5. Evidence economics

Command evidence, parser tiers, savings, discovery, filters, response cache, and
cost reporting are current-only.

6. Model identity and packs

Canonical model identity, model-pack overlays, related-project overlays, and
long-eval gates are current-only.

7. Documentation and release readiness

Current has public-facing README/docs/wiki/release notes/security/privacy/terms;
v2 has design and experiment reports but not a release documentation system.

## Risks in v2

- It is not a git checkout, so provenance and change history are missing.
- It claims "no god classes," but several files already exceed 300-500 lines;
  still much smaller than current, but the rule is not literally enforced at
  file level.
- The review service currently makes one large LLM prompt from all resolved
  files; batch review exists separately but is not the main CLI path.
- The two diff analyzer modules (`infrastructure/diff_analyzer.py` and
  `infrastructure/analysis/diff_analyzer.py`) overlap enough to invite drift.
- Some fallback setup is incomplete: fallback model is read but not really
  applied to client requests in `DIContainer`.
- v2 is Python-heavy. Current's external analyzer support spans more languages.
- It lacks the plugin, host-memory, worktree, and learning safeguards that make
  current useful as an agent harness.

## Risks in Current

- Large orchestration files make feature work slower and riskier.
- Provider abstractions are weaker than v2's.
- The CLI surface is very broad, so command-doc parity is a real maintenance
  burden.
- The project-memory database is powerful but complex; local corruption can
  affect broad test runs and operator confidence.
- The stale editable install issue can make local CLI smoke results noisy until
  the venv is refreshed.

## Recommended Adoption Plan

Do not merge v2 as a replacement. Treat it as a reference implementation for
specific internal upgrades.

Suggested order:

1. Add an internal provider interface modeled on v2 `LLMClient`, but backed by
   current `M27Client` telemetry, identity, cache, and prompt compaction.
2. Add a memory-only review option for CI/no-state smoke use. Keep project
   memory as default.
3. Port v2 AST analyzer as an optional pre-static-analysis source that emits
   current `StaticIssue` or `ReviewIssue` shapes.
4. Port v2 cross-reference analyzer behind current scope classifier and command
   evidence/artifact conventions.
5. Port v2 confidence scoring into current review findings and memory decisions.
6. Add file-content review cache only after it can report savings through
   current `savings` and response-cache telemetry.
7. Adopt v2's explicit diff review CLI flags if they can map cleanly to current
   review modes and worktree/shadow paths.
8. Revisit large-file decomposition only after the above slices land, because
   current behavior coverage is broad and easy to regress.

## Bottom Line

v2 is the better architectural sketch. Current is the better application.

The useful path is selective absorption: port v2's cleaner provider/analyzer
runtime pieces into the current product while preserving current's plugin,
project-memory, evidence, review modes, worktree safety, and release-doc
surface.
