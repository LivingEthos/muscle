# MUSCLE Release Notes: Project-First Growth and Model Packs

Release date: 2026-04-16

This release finishes the project-first growth, related-project transfer,
model-identity, and model-pack initiative tracked in
[docs/project-first-growth-model-pack-roadmap.md](docs/project-first-growth-model-pack-roadmap.md).

## What shipped

- project-local `project_memory.db` is now the authoritative store for
  project-owned memory, lesson usage, transferred-lesson validation, model
  identity history, and related telemetry
- related-project lessons can be suggested, imported, attached, audited,
  validated, promoted, or archived without outranking the local project
- canonical model identity is stored explicitly, supports trusted provider
  introspection where available, and always allows manual override
- model packs now support validation, local install, remote install/update,
  export, and draft PR submission to the community pack repository
- benchmark fixtures and release gates now prove overlay value without allowing
  regressions to the default project-only workflow
- operator visibility now includes model identity history, lesson-usage history,
  readable audit logs, and explicit model-pack lifecycle logging

## Important product rules

- project-local memory remains authoritative
- related-project lessons are provisional overlays
- model-pack lessons are provisional overlays tied to canonical model identity
- normal `muscle review` and `muscle run` do not perform new network fetches for
  overlays
- community sharing is explicit export plus draft PR, never silent upload

## New or expanded command surfaces

- `muscle memory related`
- `muscle memory import-project`
- `muscle memory history`
- `muscle model status`
- `muscle model history`
- `muscle model select`
- `muscle model packs list/install/update/export-candidate/submit`
- `muscle settings show`
- `muscle settings model`
- `muscle long-eval benchmark --enforce-gates`

## Upgrade notes

Existing users should read
[docs/migration-and-data-safety.md](docs/migration-and-data-safety.md)
before depending on overlays in production.

High-signal post-upgrade checks:

1. run `muscle status`
2. run `muscle settings show`
3. run `muscle model status`
4. run `muscle memory related --refresh` if you use cross-project suggestions
5. run `muscle long-eval benchmark --enforce-gates` before relying on overlays

## Validation snapshot

This release track closed with:

- migration and backup hardening
- observability and auditability for lesson and model identity decisions
- benchmark evidence and release-gate enforcement
- documentation and plugin help updated to match shipped behavior

Use the roadmap document for the implementation log and validation evidence by
workstream.
