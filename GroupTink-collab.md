# MUSCLE Consensus Supervision and Nightly Escalation

## Summary

Add a first-class MUSCLE feature for external model supervision and multi-model consensus, powered by Consensus Engine but owned by MUSCLE's CLI, plugin UX, storage, and learning pipeline.

Default behavior:

- Manual entrypoint: `muscle consensus`
- Review integration: `muscle review --backend local|supervisor|consensus|hybrid`
- Automatic mode: escalate on risk, not on every review
- Credit strategy: balanced by default
- Memory publishing: selective; only important or repeated lessons reach root `CLAUDE.md`

The product shape is:

- MUSCLE remains the local operator, fixer, learner, and nightly runner
- Consensus Engine is the remote supervisor/consensus backend accessed through MUSCLE
- Agents in Claude Code get explicit instructions on when to request a supervisor pass, when to request full consensus, which method to choose, and which models fit the task

## Core Product Changes

### 1. Dedicated consensus feature in MUSCLE

Add a new command surface in `tools/muscle/cli.py`:

- `muscle consensus --target <path|diff|text>`
- `muscle consensus --mode supervisor|consensus|gate`
- `muscle consensus --method auto|fan_out_fan_in|debate|swarm|delphi|generator_verifier|weighted_voting|sequential_refinement|moe_routing|tree_of_thoughts`
- `muscle consensus --profile balanced|premium|budget`
- `muscle consensus --models ...`
- `muscle consensus --apply-memory`
- `muscle consensus --output json|markdown|summary`

Also extend `muscle review`:

- `--backend local` keeps current behavior
- `--backend supervisor` sends the target to one strong outside model for a second opinion
- `--backend consensus` runs a true multi-model consensus review
- `--backend hybrid` runs MUSCLE local review first, then escalates only selected issues/targets to supervisor or consensus

Agent/plugin entrypoints:

- Add `/muscle:consensus`
- Add `/muscle:gate`
- Update `/muscle:review` skill so agents know to choose local, supervisor, or consensus paths based on risk and ambiguity

### 2. New processing/orchestration layer

Add a MUSCLE-owned orchestration layer between CLI/plugin calls and the external service.

New subsystem responsibilities:

- Resolve target input: file, directory slice, git diff, staged diff, branch diff, explicit text
- Choose review mode:
  - `supervisor` for "another strong model should sanity-check this"
  - `consensus` for "we need multi-model convergence"
  - `gate` for pass/fail verdict
- Choose method and model set automatically from task/risk
- Submit the request to Consensus Engine
- Normalize external findings into MUSCLE-native issue/result types
- Merge, dedupe, rank, and label provenance/confidence
- Hand final findings to the learning pipeline

Recommended modules:

- `consensus_adapter.py`: API/SDK wrapper
- `consensus_orchestrator.py`: target resolution, policy, method/model selection
- `consensus_processor.py`: normalization, dedupe, severity mapping, confidence handling
- `consensus_policy.py`: auto-escalation rules and credit guardrails

### 3. Memory intake and storage

Extend MUSCLE's DB-first learning flow in `tools/muscle/code_review/learning_pipeline.py`:

- Treat consensus/supervisor results as first-class review evidence
- Record provenance:
  - source backend
  - mode (`supervisor`, `consensus`, `gate`)
  - method
  - selected models
  - confidence
  - cost/credits used
  - external review or pipeline IDs
- Split outputs into three buckets:
  - `critical lessons`: high severity or repeated, eligible for root `CLAUDE.md`
  - `working memory`: short-lived notes for ongoing repo/task context
  - `archival evidence`: raw findings, synthesis, and metadata in DB/report files

Publishing rules:

- Root `CLAUDE.md`: only repeated or high-severity lessons, concise and deduped
- `.muscle/MEMORY.md` or DB short-term notes: issue summaries, review heuristics, current hotspots
- `.muscle/reports/`: raw consensus summaries, nightly escalations, cost/confidence metadata
- No automatic raw dump of full external reviews into `CLAUDE.md`

Add project-note helpers for:

- "supervisor note"
- "consensus lesson"
- "nightly escalation summary"

### 4. Automatic escalation policy

Implement decision-complete default rules:

- Always run local MUSCLE review first unless user explicitly calls `muscle consensus`
- Escalate to `supervisor` when:
  - local review marks an issue high/critical
  - fix verification fails
  - static and semantic signals disagree
  - user requests a second opinion
  - changed files touch auth, payments, persistence, concurrency, migrations, deploy, or CI gating paths
- Escalate to `consensus` when:
  - issue is critical or cross-cutting
  - there are multiple competing diagnoses
  - architecture, security, concurrency, rollback, or scope-drift risk is high
  - nightly review finds unresolved critical/high findings
  - gate mode is requested
- Fall back gracefully:
  - if external auth, credits, or network fail, preserve local result and surface a warning
  - never block normal local review because consensus is unavailable unless the user explicitly requested hard gate behavior

Credit policy:

- `balanced` default:
  - cheap classifier/router or MUSCLE local signals first
  - one strong supervisor model for second opinions
  - 3-model consensus only for critical/ambiguous cases
  - premium consensus methods only when justified by severity or complexity

## Method and Model Guidance for Agents

Create a MUSCLE-owned consensus playbook, sourced from Consensus Engine's catalog and methods, and make it available to CLI agents and plugin skills.

### 1. Consensus method guide

Create a single source-of-truth doc and skill content that explains:

- `supervisor`
  - Use for quick second opinion, sanity check, or confirmation
  - Cheapest escalation path
- `fan_out_fan_in`
  - Default general code review consensus
  - Parallel reviewers plus synthesis
- `debate`
  - Best when design tradeoffs or hidden flaws are likely
  - Use for adversarial critique, pressure review, or uncertainty
- `swarm`
  - Best for comprehensive code review with archetypes like security, performance, architecture, testing, concurrency
  - Use on complex or critical areas
- `delphi`
  - Use when careful convergence matters more than speed
- `generator_verifier`
  - Best for "proposed fix plus independent verification"
- `weighted_voting`
  - Best for narrow classification or verdict-style decisions
- `sequential_refinement`
  - Best for iterative improvement of summaries or remediation plans
- `moe_routing`
  - Best when task spans distinct domains and specialist dispatch helps
- `tree_of_thoughts`
  - Reserve for hard reasoning and alternative-path exploration
- `gate`
  - Binary pass/fail wrapper over consensus with thresholds

### 2. Model roster guide

Generate a MUSCLE-facing model guide from Consensus Engine's catalog in `packages/consensus-engine-core/src/models/curated_catalog.json`, not hand-maintained prose only.

For each supported model family include:

- provider
- role/purpose
- strengths
- weaknesses
- best use cases
- cost tier
- context window
- important benchmarks available in catalog
- recommended use in MUSCLE workflows

Initial default guidance:

- Strong supervisors:
  - GPT-5.4
  - Claude Opus 4.6
  - Gemini 2.5 Pro
  - O3 for adversarial reasoning
- Balanced supervisors:
  - Claude Sonnet 4.6
  - GPT-5.4 Mini
  - Gemini 2.5 Flash
  - O4 Mini for verification/challenge
- Budget specialists:
  - Claude Haiku 4.5
  - Gemini 2.5 Flash Lite
  - DeepSeek V3.2 for low-cost coding/reasoning passes
- Task-special hints:
  - adversarial challenge: O3 or O4 Mini
  - broad code review synthesis: Claude Sonnet/Opus or GPT-5.4
  - large-context repo slices: GPT-5.4, Claude Sonnet/Opus, Gemini 2.5 Pro/Flash
  - cheap nightly triage: Gemini Flash, Haiku, DeepSeek

### 3. Agent instructions

Update MUSCLE's Claude/plugin skill docs so agents know:

- when to stay local
- when to ask for `supervisor`
- when to ask for `consensus`
- which method to choose by problem type
- how to cap cost under balanced mode
- how to interpret and ingest results into memory

Add a dedicated "Consensus Playbook" document plus plugin skill updates in `tools/muscle/plugin/skills/code-review/SKILL.md` and the new consensus command docs.

## Nightly Review Upgrade

Upgrade nightly review from a simple local JSON summary into a multi-stage escalation pipeline.

Nightly flow:

1. Run standard MUSCLE local review over configured targets
2. Cluster findings by severity, subsystem, and recurrence
3. For high/critical clusters:
   - run supervisor pass if a second opinion is needed
   - run full consensus if findings are complex, cross-file, security-sensitive, architectural, or still unresolved
4. Generate:
   - nightly raw report
   - escalation report
   - distilled lessons for memory intake
5. Feed results into the learning pipeline with provenance and retention rules

Nightly defaults:

- low/medium findings: local only
- high findings: supervisor unless confidence already high
- critical or complex multi-file findings: consensus
- cap external nightly spend by profile; skip lower-priority escalations when budget is exhausted

Nightly report sections:

- local findings summary
- escalated findings summary
- consensus verdicts and confidence
- recommended follow-up actions
- promoted lessons
- skipped escalations due to budget/timeout

## Interfaces and Types

Add or extend MUSCLE types to include:

- `ReviewBackend = local | supervisor | consensus | hybrid`
- `ConsensusMode = supervisor | consensus | gate`
- `ConsensusProfile = budget | balanced | premium`
- `ConsensusMethod`
- `ConsensusSelectionReason`
- `ExternalReviewProvenance`
- `confidence_score`
- `credit_cost`
- `external_run_id`
- `selected_models`
- `selected_method`
- `memory_disposition = publish | short_term | archive_only`

Persist these fields alongside review runs/findings so later pattern detection and publishing can distinguish "local issue found repeatedly" from "confirmed by external consensus."

## Test Plan

- Command tests for `muscle consensus` and new `muscle review --backend` modes
- Policy tests:
  - risk-based escalation chooses supervisor vs consensus correctly
  - balanced credit mode downgrades to cheaper configurations when severity is lower
- Mapping tests:
  - external findings normalize into MUSCLE issue types with provenance preserved
  - duplicate local/external issues merge correctly
- Memory tests:
  - critical repeated lessons publish to root `CLAUDE.md`
  - low-signal findings stay in internal memory only
  - raw consensus payloads stay in reports/DB, not root memory
- Nightly tests:
  - nightly local pass works unchanged when external consensus is disabled
  - high/critical findings trigger supervisor/consensus escalation
  - timeout/auth/credit failures degrade cleanly without breaking nightly reporting
- Skill/docs tests:
  - plugin instructions mention the new command and decision rules consistently
  - generated model guide matches catalog entries and does not drift silently

## Assumptions and Defaults

- MUSCLE owns UX, local storage, fixing, and learning; Consensus Engine is a backend capability, not the primary product surface
- A dedicated `muscle consensus` command is required, even though review backends also expose the feature
- Auto mode uses risk-based escalation
- Default credit profile is `balanced`
- Default publish policy is selective
- v1 auto-fix remains local-only; external consensus influences diagnosis, gating, and memory, not direct code mutation
- Model and method guidance should be generated from the Consensus catalog/configs where possible so future catalog updates do not require hand-editing every instruction file
