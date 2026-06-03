# Agents And Skills

| Field | Value |
|---|---|
| Audience | Plugin users, host agents, and maintainers |
| Status | Current bundled agents and skill |
| Source of truth | [`tools/muscle/plugin/agents/`](../../tools/muscle/plugin/agents/), [`tools/muscle/plugin/skills/code-review/SKILL.md`](../../tools/muscle/plugin/skills/code-review/SKILL.md), [`tools/muscle/code_review/agent_generator.py`](../../tools/muscle/code_review/agent_generator.py), [`tools/muscle/code_review/skill_generator.py`](../../tools/muscle/code_review/skill_generator.py) |

The plugin bundle includes static host-facing agents and a code-review skill.
MUSCLE can also generate project-local `.muscle/skills/` and `.muscle/agents/`
as learning matures.

## Bundled Skill

| Skill | Purpose |
|---|---|
| `code-review` | Tells the host model to plan and synthesize while delegating bulk review execution to MUSCLE/M2.7. |

The skill includes command forms for:

- standard review
- pressure review
- auto-fix mode
- hybrid mode
- plan-only mode

## Bundled Agents

| Agent | Purpose | Expected output |
|---|---|---|
| `rescue_agent.md` | Deep-dive root cause analysis for complex issues, flaky tests, race conditions, leaks, bottlenecks, and integration failures. | Structured JSON with root cause, confidence, evidence, fix suggestions, and affected files. |
| `verification_agent.md` | Validate fixes with tests, linters, and type checks. | Structured JSON with validity, test/lint state, breaks, and warnings. |

## Project-Generated Assets

After repeated reviews, MUSCLE may generate project-local assets:

```text
.muscle/skills/
.muscle/agents/
```

Generated assets should be treated as project-local guidance. They are not
automatically part of the published plugin bundle.

## Agent Operating Rule

The host agent remains planner and synthesizer. MUSCLE/M2.7 does the bulk
review/investigation execution when scoped commands are invoked.

