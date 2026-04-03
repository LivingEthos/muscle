# MUSCLE Master Plan

Last updated: 2026-04-02
Status: Active

This is the high-level product plan for MUSCLE.

Completed implementation handoffs and point-in-time review reports have been
retired so this file stays focused on the current product direction.

`Forsight-plan.md` remains a separate experimental track and is intentionally
out of scope for this execution plan.

## Product Goal

MUSCLE should become a per-project Claude Code companion that uses MiniMax M2.7
to capture evidence from work, compress it into durable project memory, safely
publish the right rules into the real root `CLAUDE.md`, and gradually create
useful project-specific skills and agents.

## Verified Current State

The current worktree already contains a substantial refactor foundation.

Verified on 2026-04-02:

- targeted implementation suite passed:
  `520 passed, 1 skipped in 23.69s`
- project-local `project_memory.db` scaffolding exists
- migrations and legacy import paths exist
- learning ingestion, change capture, notes, and correction-signal plumbing exist
- root `CLAUDE.md` publishing exists
- backup inspection and restore CLI exists
- a memory decision engine exists

## Where Implementation Stopped

The repo is no longer at the prototype-only stage, but the refactor is not yet
fully consolidated.

Current stop point:

- the DB-first architecture is partially wired, but some old and new paths still
  coexist
- review evidence ingestion is still split across more than one layer
- publishing and backup logic still need to converge on one shared runtime path
- explicit Claude Code project controls are incomplete
- skill generation exists, but full DB-backed specialization lifecycle is not done
- agent generation exists, but it is not yet a fully integrated closed loop
- the TUI is still only partially data-backed
- background review state still needs project-local discipline

## Active Plan Files

- `MUSCLE_PLAN.md`
- `Forsight-plan.md`
- `GroupTink-collab.md`

These are now the only active planning documents.

## Delivery Phases

### Phase 1: Stabilize the DB-First Spine

Finish the integration work that is already underway:

- unify review ingestion
- unify publishing and backup ownership
- make the database the clear source of truth
- define the remaining role of `.muscle/*.md`

### Phase 2: Complete Claude Code Project Controls

Make MUSCLE understandable and controllable per project:

- real Claude Code init behavior
- `enable`, `disable`, and `status`
- memory, skill, agent, and backup inspection commands
- truthful plugin docs and help text

### Phase 3: Finish Skill and Agent Lifecycle

Turn learning into specialization:

- DB-backed skill lifecycle
- evidence-driven agent creation
- bounded agent and skill revision flows
- root `CLAUDE.md` references for active specializations

### Phase 4: Make the Management Surfaces Real

Finish the day-to-day UX:

- project-local background job tracking
- live TUI dashboard and inspection views
- basic TUI actions
- audit and observability surfaces

### Phase 5: Hardening and Release

Prepare for a production push:

- changed-files-first background scope
- token and automation guardrails
- quality gates
- smoke coverage
- docs and release cleanup

## Success Criteria

MUSCLE is ready for the next release when all of the following are true:

- `project_memory.db` is the authoritative per-project memory store
- the real root `CLAUDE.md` is updated safely and predictably
- project-local enable/disable/status is reliable
- skills and agents are created from evidence, not ad hoc helpers
- the TUI reflects live project state
- background work is project-scoped and budget-aware
- full quality gates pass
