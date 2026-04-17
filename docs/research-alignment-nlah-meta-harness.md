# MUSCLE Research Alignment Report

Date: 2026-04-15

Scope: read-only assessment of the active `tools/muscle/` implementation against two March 2026 papers:

- `Natural-Language Agent Harnesses` (arXiv:2603.25723, submitted March 26, 2026)
- `Meta-Harness: End-to-End Optimization of Model Harnesses` (arXiv:2603.28052v1, submitted March 30, 2026)

Method:

- Read the two papers directly from arXiv.
- Inspected the current MUSCLE repo and architecture docs.
- Did not run write-producing tests, did not generate artifacts, and did not modify existing project files as part of the comparison itself.

## Executive Summary

MUSCLE is already pointed in the same general direction as both papers. It has durable project-local state, explicit review workflows, benchmark fixtures, structured artifact storage, DB-backed learning, and bounded publication of learned rules into `CLAUDE.md`. Those are not superficial similarities; they are real implementation choices.

The main gap is that MUSCLE still treats the harness mostly as implementation spread across Python controllers, YAML workflows, markdown skills, and memory rules, rather than as one first-class executable harness object. That means MUSCLE only partially captures the central NLAH lesson.

The second major gap is trace fidelity. MUSCLE stores sessions, findings, reports, review artifacts, and LLM-call telemetry, and it can import external agent transcripts. But it does not yet appear to archive the full raw prompt/response/tool/state trace history of its own native loops in the way Meta-Harness treats as the key enabler for outer-loop harness search. That means MUSCLE only partially captures the central Meta-Harness lesson too.

Bottom line:

- Against `Natural-Language Agent Harnesses`: `partial alignment`, with strong infrastructure but incomplete first-class harness representation.
- Against `Meta-Harness`: `partial alignment`, with meaningful evaluation and persistence machinery but no full-history harness search loop yet.

## Sources Reviewed

Papers:

- `https://arxiv.org/pdf/2603.25723`
- `https://arxiv.org/abs/2603.28052`
- `https://arxiv.org/pdf/2603.28052v1`

Primary MUSCLE repo anchors:

- `README.md`
- `MUSCLE_PLAN.md`
- `docs/architecture.md`
- `CLAUDE.md`
- `tools/muscle/loop_controller.py`
- `tools/muscle/session_manager.py`
- `tools/muscle/code_generator.py`
- `tools/muscle/evolver.py`
- `tools/muscle/code_review/review_controller.py`
- `tools/muscle/code_review/review_artifacts.py`
- `tools/muscle/code_review/review_workflows.py`
- `tools/muscle/code_review/review_benchmark.py`
- `tools/muscle/code_review/long_eval_runner.py`
- `tools/muscle/workflows/review-smart.yaml`
- `tools/muscle/project_memory.py`
- `tools/muscle/optimization/importers.py`
- `tools/muscle/m27_client.py`

## Paper 1: Natural-Language Agent Harnesses

## What the paper argues

The NLAH paper argues that harness logic should stop being buried in controller code and framework defaults and should instead become a portable, executable object. The paper's key design ideas are:

- separate shared runtime policy from task-family harness logic
- make contracts, roles, stages, adapters, state semantics, and failure handling explicit
- use file-backed, path-addressable durable state
- enable controlled ablations at the harness-pattern level rather than only controller-bundle comparisons

In other words, the paper is not just about using markdown instructions. It is about making the harness itself explicit enough to compare, migrate, ablate, and execute under a shared runtime.

## Alignment Matrix: NLAH vs MUSCLE

| Dimension | Paper expectation | MUSCLE evidence | Judgment |
|---|---|---|---|
| First-class harness representation | Harness logic should be an explicit object instead of remaining buried in controller code | MUSCLE externalizes some behavior into workflow YAML and markdown skills, but the primary control logic still lives in Python controllers such as `ReviewController` and `LoopController` | Partial |
| Shared runtime vs harness logic separation | Runtime policy should be cleanly separated from task-family harness logic | MUSCLE deliberately separates orchestration from model calls, generation from evaluation, and review findings from persistence in `docs/architecture.md:420-426`, but it does not define an explicit runtime charter / harness skill split | Partial |
| Explicit contracts, roles, stages, gates | Contracts, roles, stage structure, and gates should be explicit and executable | MUSCLE has stage-like review workflows in `tools/muscle/workflows/review-smart.yaml:1-34` and review modes in `tools/muscle/code_review/review_controller.py:142-187`, but it does not expose a unified contract schema for required outputs, permissions, budgets, and completion conditions | Partial |
| Explicit failure taxonomy | Failure modes should be named and drive recovery behavior | MUSCLE has stop conditions, evaluation failures, and mode-specific flows, but no first-class harness-wide failure taxonomy surface comparable to the paper's formulation | Missing |
| File-backed state semantics | State should be externalized, path-addressable, and stable across steps | MUSCLE is strong here: sessions, reports, review artifacts, and project-local DB state are all durable and path-addressable | Aligned |
| Adapters and deterministic hooks | Harnesses should expose adapters and scripts for deterministic operations | MUSCLE has evaluators, static analyzers, verifiers, git/MCP/GitHub adapters, and workflow nodes such as `validate` and `gate` | Partial |
| Controlled module ablation | Harness patterns should be benchmarked and ablated under shared assumptions | MUSCLE has a genuine benchmark runner for review workflow comparisons in `tools/muscle/code_review/review_benchmark.py:53-115`, but it is narrower than the paper's harness-wide controlled ablation story | Partial |
| Code-to-text migration of harness logic | Native harness logic should be reconstructable into a portable textual form | MUSCLE does not currently appear to support systematic code-to-text harness migration | Missing |

## Repo Evidence Behind the NLAH Judgment

### 1. MUSCLE already externalizes some harness logic

The strongest NLAH-like move in MUSCLE is not the generation loop; it is the review workflow layer.

`tools/muscle/workflows/review-smart.yaml:1-34` defines an explicit DAG-like sequence:

- `classify`
- one or more `review_agent` nodes
- `synthesize`
- `gate`

That is already much closer to a harness artifact than a purely hard-coded controller. Similarly, `tools/muscle/code_review/review_workflows.py:17-121` limits the node vocabulary and validates dependencies, which gives the workflow a portable and inspectable shape.

This matters because it shows MUSCLE is not fully controller-buried. It already has the beginnings of an external harness layer.

### 2. The externalization is incomplete

The problem is that MUSCLE's real control policy is still spread across several layers:

- Python controllers (`tools/muscle/code_review/review_controller.py:86-187`, `tools/muscle/loop_controller.py`)
- workflow YAML (`tools/muscle/workflows/*.yaml`)
- markdown skills (`skills/code-loop/SKILL.md:1-93`, `tools/muscle/plugin/skills/code-review/SKILL.md`)
- architecture docs and memory surfaces (`README.md:120-145`, `docs/architecture.md:25-69`)

That is useful engineering, but it is not yet one explicit executable harness object of the kind the NLAH paper is arguing for.

### 3. MUSCLE has good durable state, but not explicit state semantics

MUSCLE does a lot right on persistence:

- `tools/muscle/session_manager.py:59-110` creates per-session directories
- `tools/muscle/session_manager.py:112-156` appends iteration summaries and copies artifacts
- `tools/muscle/code_review/review_artifacts.py:37-90` persists scope, findings, synthesis, fixes, validation, and summaries
- `tools/muscle/project_memory.py` provides a DB-backed memory spine
- `docs/architecture.md:346-377` and `CLAUDE.md:99-117` describe the project-local storage model

This strongly aligns with the paper's emphasis on durable, path-addressable artifacts.

However, MUSCLE does not yet make the semantics of that state explicit at the harness level. It stores artifacts, but it does not expose a first-class specification for:

- what must persist across stages
- what is reopened by path
- which artifacts are required vs optional
- how child workspaces and ledgers are supposed to compose

So the storage pattern is aligned, while the explicit state-semantics layer is only partial.

### 4. MUSCLE has stages and gates, but not contract-first execution

The NLAH paper is very specific that an agent call should be bounded by an execution contract covering outputs, budgets, permissions, and completion conditions.

MUSCLE has neighboring mechanisms:

- `LoopController` stop conditions in `docs/architecture.md:171-180`
- review workflow `gate` and `validate` nodes
- fix verification logic in the review pipeline
- budgets and telemetry in the optimization layer

But those are still distributed behaviors, not a unified contract object attached to each stage or agent call. That is why this dimension is `partial`, not `aligned`.

### 5. MUSCLE is closer to NLAH on review than on run

`muscle review` already has:

- workflow externalization
- structured artifacts
- fixed stage vocabulary
- learning after execution
- benchmark comparisons across workflow variants

`muscle run`, by contrast, is still much more code-coupled:

- generate
- evaluate
- evolve
- repeat

That flow is described in docs and skills, but it is not yet materialized as a first-class harness spec. The code loop skill in `skills/code-loop/SKILL.md:57-63` explains the loop, but it remains descriptive rather than contract-executable.

## NLAH Conclusion

MUSCLE is following the paper's direction, especially in its review workflow layer, artifact persistence, and explicit subsystem separation. But it has not yet taken the final step of making the harness itself the primary executable and benchmarkable object. Today, MUSCLE has externalized workflow ingredients, not a full NLAH-style harness representation.

## Paper 2: Meta-Harness

## What the paper argues

The Meta-Harness paper argues that harness optimization needs a different outer loop from prior text optimizers. Its core claim is that compressing prior feedback into short summaries is too lossy for harness engineering. Instead, the proposer should be able to inspect the full prior history of source code, scores, and execution traces through the filesystem, and then decide what to inspect, diagnose, and edit.

The practical implications are:

- the harness itself becomes the object being searched
- every candidate gets persisted with code, scores, and traces
- future proposals can inspect raw prior evidence selectively
- benchmarked harness search matters more than ad hoc improvement stories

## Alignment Matrix: Meta-Harness vs MUSCLE

| Dimension | Paper expectation | MUSCLE evidence | Judgment |
|---|---|---|---|
| Harness as search object | The outer loop should search over harness implementations | MUSCLE evolves strategies, review behavior, and skills, and benchmarks review workflows, but it does not broadly search over full MUSCLE harness implementations as first-class candidates | Partial |
| Full prior experience available for inspection | Prior candidates should expose code, scores, and execution traces in durable storage | MUSCLE stores sessions, reports, review artifacts, and telemetry, but native loop storage is mostly summary-level; full raw trace history is not clearly archived | Partial |
| Selective raw inspection by proposer | The proposer should inspect prior raw artifacts via filesystem operations | MUSCLE's current `Evolver` and generation loop do not appear to inspect prior candidate directories as an agentic proposer would; they mostly use errors, current prompts, and KB retrieval | Missing |
| Raw traces, not just summaries | Prior prompts, tool calls, outputs, and state updates should remain available | Review artifacts and session logs are useful, but they do not appear to preserve complete raw prompt/response/tool/state traces for native MUSCLE runs | Missing |
| Candidate benchmarking and comparison | Harness variants should be compared under fixed scenarios | MUSCLE has a real workflow benchmark runner with fixture manifests and aggregate metrics | Aligned for review workflows, Partial overall |
| Population / frontier style search | Search should retain and compare multiple candidates over time | MUSCLE persists sessions and benchmark reports, but it does not currently expose a Meta-Harness-style candidate population / Pareto frontier for its own harness search | Missing |
| External transcript reuse | Prior agent behavior can inform optimization if kept separate from live memory | MUSCLE's external benchmark importers are a strong building block here | Partial |

## Repo Evidence Behind the Meta-Harness Judgment

### 1. MUSCLE has more evaluation discipline than many agent tools

This is where MUSCLE already looks unusually strong.

`tools/muscle/code_review/review_benchmark.py:53-115` defines a fixture-based benchmark runner that:

- loads named scenarios from a manifest
- runs a baseline and candidate workflow
- computes aggregate metrics
- writes structured reports

That is not yet full Meta-Harness, but it is absolutely in the same family of thinking: treat the review workflow as something that can be compared against alternatives under stable tasks.

### 2. MUSCLE stores useful history, but not full native traces

MUSCLE's native persistence is meaningful:

- sessions in `.muscle/sessions/<session_id>/`
- iteration summaries in `iterations.jsonl`
- report and context files
- review artifacts under `.muscle/review_artifacts/<session_id>/`
- DB-backed `llm_calls`

But the stored contents are much lighter than the Meta-Harness paper's model of prior experience.

`tools/muscle/session_manager.py:128-137` stores iteration number, success, errors, warnings, token cost, duration, and evolved strategy.

`tools/muscle/session_manager.py:181-186` stores a compact final context with task, evolved strategy, and iteration count.

`tools/muscle/code_review/review_artifacts.py:49-81` stores scope, agent findings, synthesis, fixes, validation, and markdown summary.

`tools/muscle/project_memory.py:1502-1668` stores LLM-call telemetry such as token counts, duration, success, context size, and metadata.

That is all valuable. But it is not the same as storing, for each native candidate/run:

- raw prompts
- raw model outputs
- tool-call traces
- explicit state transitions
- full execution traces that later optimization loops can reopen and inspect causally

That difference is the biggest reason MUSCLE is only partially aligned with Meta-Harness.

### 3. MUSCLE's own outer loop is still summary-driven

Look at the native `generate` and `evolve` paths:

- `tools/muscle/code_generator.py:208-242` builds a prompt and sends it to the model
- `tools/muscle/evolver.py:171-206` builds another prompt from task, errors, previous strategy, and similar strategies

Those prompts are used at runtime, and telemetry is recorded, but the repo evidence does not show a native mechanism that archives the full prompt/response pair for every loop step and then exposes that archive back to a future agentic proposer.

So MUSCLE does have historical memory, but it is mostly compressed memory:

- summaries
- findings
- scores
- telemetry
- KB entries

That is exactly the kind of compression the Meta-Harness paper argues is insufficient for harness search in harder settings.

### 4. The external benchmark importers are a promising bridge

One of MUSCLE's most interesting building blocks is `tools/muscle/optimization/importers.py:31-235`.

That subsystem can import Codex and Claude session data into project-local benchmark tables. This is highly relevant to the Meta-Harness lesson because it acknowledges that prior agent traces matter and should be queryable separately from live project memory.

However, even here the imported data is normalized rather than preserved as a fully reopenable raw trace archive. For example, the importer records:

- session identity
- timestamps
- token counts
- tool names
- retry counts
- a reduced category
- selected metadata such as user messages

That is useful for analytics and benchmarking, but it is still not equivalent to a filesystem of prior candidate directories containing full code, scores, prompts, tool traces, model outputs, and state updates.

### 5. MUSCLE has telemetry, not yet causal trace archives

`tools/muscle/m27_client.py:206-242` records telemetry through `LLMCallEvent`, and `tools/muscle/project_memory.py:1502-1668` persists it.

This is good instrumentation. It helps answer:

- how many tokens were used
- how long a stage took
- whether the call succeeded
- what context strategy was used

But Meta-Harness needs more than instrumentation. It needs causal debugging surfaces: enough raw evidence for a future proposer to inspect why a prior harness failed and which earlier decisions contributed to the failure.

MUSCLE is not there yet for its own native loops.

## Meta-Harness Conclusion

MUSCLE already has serious ingredients for harness-level optimization:

- benchmark comparisons
- durable project-local persistence
- review artifacts
- telemetry
- imported external agent history

But it does not yet implement the core Meta-Harness move: searching over harness implementations using agentic selective inspection of full prior code-and-trace history. Its current learning loop is stronger on memory curation than on raw-history-driven harness search.

## What MUSCLE Already Does Well

These are the areas where MUSCLE is genuinely ahead of many comparable agent tools and already reflects the spirit of the papers:

### 1. Durable project-local state

MUSCLE has real project-local memory and artifacts, not just transient prompts:

- `.muscle/sessions/`
- `.muscle/review_artifacts/`
- `.muscle/reports/`
- `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, `.muscle/MEMORY.md`
- DB-backed `project_memory.db`

This is a major prerequisite for both papers.

### 2. Structured review workflows

The review system is not just one big prompt. It has:

- scope classification
- agent-specific review passes
- synthesis
- fix
- validate
- gate

That externalized structure is an important step toward first-class harnesses.

### 3. Evidence-driven learning pipeline

`tools/muscle/code_review/learning_pipeline.py:71-230` gives MUSCLE a real post-review learning cycle:

- ingest findings into DB
- score decisions
- publish promoted rules
- track lower-severity issues
- detect patterns
- generate skills and agents

That is much closer to a research-style compounding loop than a typical one-shot review tool.

### 4. Benchmarking as a first-class subsystem

The presence of `tools/muscle/code_review/review_benchmark.py` is important. It shows MUSCLE is already capable of evaluating workflow variants on stable fixtures rather than relying only on anecdotal wins.

### 5. Honest internal maturity notes

`MUSCLE_PLAN.md:36-50` is unusually clear that:

- the DB-first architecture is only partially wired
- specialization lifecycle is not finished
- project controls are incomplete
- some surfaces are still only partially real

That honesty is an asset. It makes it easier to turn the paper lessons into an implementation roadmap without pretending the repo is already there.

## Where MUSCLE Is Only Partially Aligned

These are the areas where MUSCLE has the right building blocks but not yet the full paper-grade formulation:

### 1. Harness externalization is real but fragmented

Harness behavior currently lives across:

- Python controllers
- YAML workflows
- markdown skills
- DB-backed rules
- architecture docs

That is useful, but it is not yet a single versioned harness representation.

### 2. State is durable but not semantically specified

MUSCLE stores a lot of state, but the rules of that state are not yet first-class:

- what each artifact means
- which artifacts are contractually required
- how state should be reopened
- what survives delegation, branching, truncation, or replay

### 3. Benchmarking is narrower than the papers

MUSCLE benchmarks review workflow variants. The papers aim higher:

- harness-wide behavioral ablation
- runtime vs harness factorization
- migration fidelity
- outer-loop search over the harness itself

MUSCLE has a foothold here, not the finished system.

### 4. Optimization loops remain mostly summary-based

The current loop learns from:

- error lists
- review findings
- telemetry summaries
- KB entries

It does not yet learn by reopening the full raw history of prior native runs in the way Meta-Harness emphasizes.

## What Is Still Missing

These are the biggest missing pieces if the goal is to explicitly apply the papers' lessons to MUSCLE.

### 1. A first-class MUSCLE harness spec

MUSCLE needs a versioned harness object that can represent, at minimum:

- stages
- roles
- contracts
- adapters
- state semantics
- failure taxonomy
- budgets and stopping rules

Without this, MUSCLE cannot fully claim NLAH-style harness externalization.

### 2. A runtime charter distinct from task-family harness logic

The repo currently separates subsystems, but it does not yet formalize:

- shared runtime policy
- task-family harness logic
- backend/tool semantics
- child lifecycle semantics

That explicit split is central to the NLAH design.

### 3. Full raw trace capture for native MUSCLE loops

For Meta-Harness-style learning, MUSCLE would need to preserve for its own runs:

- raw prompts
- raw model outputs
- tool-call history
- state updates
- candidate source snapshots
- evaluation traces linked back to those snapshots

Today it mostly stores summaries and telemetry instead.

### 4. Agentic inspection of prior candidates

The proposer in Meta-Harness is a coding agent that decides what prior artifacts to inspect. MUSCLE's `Evolver` is still closer to a prompt transformer than to a filesystem-inspecting harness proposer.

### 5. Harness-level search over candidate implementations

MUSCLE does not yet expose a native loop where:

- multiple harness candidates are proposed
- all are evaluated under fixed tasks
- the results are stored in a unified candidate archive
- future proposals can inspect any earlier candidate and its traces

### 6. Controlled migration / ablation framework for run harnesses

MUSCLE has review benchmarking. It does not yet have a comparable framework for:

- `muscle run` harness variants
- code-coupled vs externalized harness comparisons
- runtime-charter vs task-harness ablations

## Highest-Leverage Next Steps

If the goal is to make MUSCLE meaningfully more aligned with these papers, this is the best order of work.

### Priority 1: Define a first-class harness schema

Create a versioned harness spec for both `muscle review` and `muscle run` that makes explicit:

- stages
- roles
- contracts
- validators
- adapters
- state surfaces
- failure taxonomy
- stop and retry rules

This is the single highest-leverage NLAH-inspired change.

### Priority 2: Separate runtime charter from harness logic

Lift shared execution semantics into a runtime policy layer and keep task-family behavior in the harness spec. That would let MUSCLE benchmark:

- same runtime, different harness
- same harness, different runtime policy

which is exactly the kind of clean comparison the NLAH paper wants.

### Priority 3: Upgrade native trace capture from telemetry to replayable traces

Extend session persistence so every native run can retain:

- prompt files
- model output files
- tool and verification traces
- state snapshots
- candidate manifests

This is the highest-leverage Meta-Harness-inspired change.

### Priority 4: Standardize candidate directories

Give every harness candidate a stable directory layout containing:

- harness definition
- code snapshot
- scores
- traces
- notes / diagnostics

That would make selective future inspection possible.

### Priority 5: Add harness-search benchmarks

Generalize `review_benchmark.py` into a broader harness benchmark layer covering:

- review harness variants
- run harness variants
- contract ablations
- state-module ablations
- runtime-charter ablations

### Priority 6: Let future proposers inspect prior candidates directly

Once raw traces and candidate directories exist, promote the outer loop from summary-based evolution to agentic inspection:

- inspect prior candidates
- compare regressions
- identify causal changes
- generate targeted edits

That is the move that would make MUSCLE meaningfully Meta-Harness-like.

## Final Assessment

MUSCLE is not ignoring these research directions. In fact, it already shares several of their deepest instincts:

- control logic matters as much as model quality
- durable artifacts matter
- memory should be project-local and evidence-backed
- workflow variants should be benchmarked
- learning should survive across runs

What MUSCLE has not yet done is make the harness itself the central object of execution and optimization. Today, MUSCLE has strong scaffolding around self-improvement. The papers suggest the next step: turn that scaffolding into an explicit harness substrate, then optimize it with richer trace access and cleaner experimental control.

That would move MUSCLE from "self-improving tool with strong memory and workflow infrastructure" toward "research-grade harness engineering system."
