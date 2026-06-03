# Storage Map

| Field | Value |
|---|---|
| Audience | Maintainers, operators, and agents debugging state |
| Status | Current storage guide with known stale-doc caveat |
| Source of truth | [`tools/muscle/project_memory.py`](../../tools/muscle/project_memory.py), [`tools/muscle/system_db.py`](../../tools/muscle/system_db.py), [`docs/migration-and-data-safety.md`](../../docs/migration-and-data-safety.md), [`tools/muscle/code_review/shadow_broker.py`](../../tools/muscle/code_review/shadow_broker.py) |

## Per-Project State

```text
.muscle/
  config.yaml
  project_memory.db
  active-review.md
  CLAUDE.md
  AGENT.md
  MEMORY.md
  logs/
  skills/
  agents/
  packs/
  knowledge/
    strategies.db
  review_kb/
    review_kb.db
  sessions/
  reports/
    release_evidence/
```

## Shared User State

```text
~/.muscle/
  system.db
  model-pack-cache/
  cache/
    cache.db
  prompts/
  global/
  global_review/
```

## Authoritative Stores

| Store | Authority |
|---|---|
| `.muscle/project_memory.db` | Current project memory, reviews, findings, transferred lessons, model history, automation state, shadow job records. |
| `~/.muscle/system.db` | Registered projects, model aliases, installed model packs, pack submission history. |
| `.muscle/config.yaml` | Project configuration; JSON-compatible content despite `.yaml` extension. |

## Generated Or Compatibility Surfaces

| Surface | Rule |
|---|---|
| `.muscle/active-review.md` | Generated snapshot only; never hand-edit. |
| `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, `.muscle/MEMORY.md` | Marker-bounded compatibility memory. |
| Root `CLAUDE.md`, root `AGENTS.md` | Optional bounded host-published guidance. |

## Shadow Jobs

Current implementation stores shadow jobs through project-local
`project_memory.db` via `ShadowBroker`. If older docs mention
`~/.muscle/shadow_jobs.json`, treat that as stale for current behavior unless
code changes reintroduce it.

## Backup Boundary

Use [`docs/migration-and-data-safety.md`](../../docs/migration-and-data-safety.md)
for backup and restore procedures before migration or release work.

