# Evidence, Savings, And Filters

| Field | Value |
|---|---|
| Audience | Operators and agents evaluating review evidence quality |
| Status | Current evidence surfaces |
| Source of truth | [`tools/muscle/command_evidence.py`](../../tools/muscle/command_evidence.py), [`tools/muscle/output_filters.py`](../../tools/muscle/output_filters.py), [`tools/muscle/savings.py`](../../tools/muscle/savings.py), [`docs/release-notes-2026-05-01-plugin-readiness.md`](../../docs/release-notes-2026-05-01-plugin-readiness.md) |
| Primary commands | `muscle savings`, `muscle discover`, `muscle filters verify`, `muscle filters trust` |

MUSCLE records local evidence about what commands ran, what output was retained,
how parser quality degraded, and where review/check opportunities were missed.

## Command Evidence

Command evidence can include:

- command identity
- exit state
- parser tier
- output digest
- retained excerpt
- estimated token savings
- recovery hints

This evidence is local diagnostic data. It should not be marketed as public
telemetry.

## Parser Tiers

Parser tiers expose whether output was structured and trustworthy:

| Tier | Meaning |
|---|---|
| Full | Structured parser succeeded. |
| Partial | Parser recovered useful data from degraded output. |
| Passthrough | Output was retained without strong structure. |

Agents should mention degraded parser tiers when they materially affect
confidence.

## Savings

```bash
muscle savings
muscle savings --json
```

Savings can summarize:

- LLM token totals by stage.
- Prompt compaction estimates.
- Cache impact.
- Command-output compaction estimates.
- Parser-tier counts.
- High-cost stages.

## Discovery

```bash
muscle discover
muscle discover --since 14
muscle discover --json
```

Discovery reports missed review/check opportunities from imported host sessions.
It is read-only and should not mutate project memory.

## Filters

```bash
muscle filters verify
muscle filters verify --require-all
muscle filters trust
muscle filters untrust
```

Project-local output filters require explicit digest-based trust before they
affect output. Filters are for compacting boring command output; they must not
hide failures.

