# Security And Privacy

| Field | Value |
|---|---|
| Audience | Users, operators, and release reviewers |
| Status | Current safety boundary summary |
| Source of truth | [`SECURITY.md`](../../SECURITY.md), [`docs/PRIVACY.md`](../../docs/PRIVACY.md), [`docs/TERMS.md`](../../docs/TERMS.md), [`README.md`](../../README.md), [`docs/release-notes-2026-05-01-plugin-readiness.md`](../../docs/release-notes-2026-05-01-plugin-readiness.md) |

MUSCLE is designed to be explicit, local-first, and inspectable.

## Secret Handling

- API keys should come from environment variables or local settings.
- Diagnostics should report key state as present or missing.
- Commands and docs should not print actual API key values.
- Do not commit `.muscle/` state or local secret files unless explicitly
  intended and reviewed.

## Memory Boundary

- Project-local memory stays in the project.
- Related-project lessons are not imported automatically.
- Model packs are optional overlays and do not replace local memory.
- Export or submission flows should be explicit.
- `muscle review --no-db` skips project-memory, learning, and optimization
  writes for that review run.

## Filter Boundary

- Project-local filters require digest trust before use.
- Filters are for compacting output, not hiding failures.
- `muscle filters verify --require-all` should pass before trusting filters.

## Discovery Boundary

`muscle discover` reports missed review/check opportunities from imported host
sessions and is read-only by default.

## Doctor Boundary

`muscle doctor` is observational. `--refresh` updates local active-review state
and importer snapshots; it should not mutate host installations or secrets.

## JSON Automation Boundary

JSON output modes are intended for automation. Progress text should stay off
stdout for machine-readable commands such as:

```bash
muscle review --format json
muscle savings --json
muscle discover --json
muscle doctor --json
```

## Public Claims

Do not turn local command evidence, savings estimates, or release snapshots into
broad telemetry claims. They are local evidence for the checked project and
checkout.
