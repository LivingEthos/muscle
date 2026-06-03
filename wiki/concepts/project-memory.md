# Project Memory

| Field | Value |
|---|---|
| Audience | Maintainers, agents, and users debugging learning behavior |
| Status | Current DB-first memory model |
| Source of truth | [`tools/muscle/project_memory.py`](../../tools/muscle/project_memory.py), [`tools/muscle/code_review/learning_pipeline.py`](../../tools/muscle/code_review/learning_pipeline.py), [`tools/muscle/code_review/memory_manager.py`](../../tools/muscle/code_review/memory_manager.py), [`docs/migration-and-data-safety.md`](../../docs/migration-and-data-safety.md) |
| Primary commands | `muscle memory status`, `muscle memory history`, `muscle memory related`, `muscle memory import-project` |

MUSCLE is project-first. The local project database is authoritative for learned
review evidence and should be treated as the primary memory source.

## Memory Surfaces

| Surface | Role |
|---|---|
| `.muscle/project_memory.db` | Authoritative project-local SQLite database. |
| `.muscle/CLAUDE.md` | Bounded compatibility memory for Claude-style hosts. |
| `.muscle/AGENT.md` | Bounded compatibility memory for agent-specific guidance. |
| `.muscle/MEMORY.md` | Bounded compatibility memory for miscellaneous findings. |
| Root `CLAUDE.md` / `AGENTS.md` | Optional host-published guidance through bounded `MUSCLE_PUBLISHED` markers. |
| `.muscle/active-review.md` | Generated convenience snapshot; never authoritative. |

## Learning Pipeline

After review completion, `LearningPipeline` can:

1. Store review evidence in `project_memory.db`.
2. Score whether findings should become memory rules.
3. Publish high/critical rules into bounded host-memory sections.
4. Track lower-severity findings for future pattern detection.
5. Validate and age older rules.
6. Generate project-specific skills or agents when patterns justify it.

## Related Projects

MUSCLE can suggest related projects and import lessons, but lessons from other
projects stay provisional until validated or explicitly promoted in the current
project.

```bash
muscle memory related
muscle memory import-project --project /path/to/other/project --mode snapshot
muscle memory import-project --project /path/to/other/project --mode attach
muscle memory history
```

## Promotion And Archive

Transferred lessons have lifecycle state. Operators can inspect promotion or
archive candidates, provide feedback, promote validated lessons, or archive
lessons that do not fit the current project.

```bash
muscle memory promotion-candidates
muscle memory lesson-feedback --lesson-key <key> --accept
muscle memory promote-lesson --lesson-id <id>
muscle memory archive-lesson --lesson-id <id>
```

## Marker-Bounded Writes

MUSCLE memory writers should edit only inside managed marker regions. User
content outside markers must remain untouched.

## Agent Rule

When in doubt, trust `project_memory.db` and current code over generated markdown
snapshots.

