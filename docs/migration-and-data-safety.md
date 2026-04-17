# MUSCLE Migration and Data Safety

Last updated: 2026-04-16

This note explains how MUSCLE stores state, how upgrades behave, and what is
and is not covered by project-local backups.

## Storage Surfaces

MUSCLE now uses two SQLite surfaces:

- Project-local state:
  `/path/to/project/.muscle/project_memory.db`
- Global shared state:
  `~/.muscle/system.db`

`project_memory.db` is authoritative for one project's runs, reviews, learned
rules, backups, optimization telemetry, transferred-lesson validation, and
other project-owned history.

`system.db` is shared across projects and stores non-project-owned state such
as:

- registered project fingerprints
- model alias mappings
- installed model packs
- pack submission history

## Upgrade Behavior

For existing projects, opening MUSCLE against an older
`.muscle/project_memory.db` automatically runs additive migrations through the
project migration framework.

Upgrade guarantees:

- existing project rows are preserved
- new tables and columns are added additively
- drift-repair hooks restore known missing optimization, cross-project, and
  model-identity schema surfaces

The global `system.db` now records its schema version and runs integrity checks,
but it is still intentionally lightweight compared with the per-project
migration framework.

## Backup Boundary

Project-local backups created through `muscle backups ...` cover only
project-owned state.

Included in project-local backups:

- `.muscle/`
- `.muscle/project_memory.db`
- `.muscle/config.yaml`
- project-root `CLAUDE.md` when using the `claude_md` backup type

Not included in project-local backups:

- `~/.muscle/system.db`

That exclusion is intentional. The global system database is shared across
projects, so restoring it as part of one project's snapshot would risk mixing
unrelated global state into the wrong recovery flow.

## Recommended Backup Practice

Before high-risk upgrades or manual recovery work:

1. create a normal project backup with `muscle backups list/show/restore` as
   needed
2. separately copy `~/.muscle/system.db` if you need to preserve cross-project
   memory, model packs, aliases, or submission history

If you only care about recovering one project's MUSCLE state, the project-local
backup is usually sufficient.

If you care about cross-project and model-pack behavior too, back up both
surfaces.

## Existing User Upgrade Checklist

For existing MUSCLE projects moving onto the project-first growth and model-pack
release:

1. create a normal project backup
2. separately copy `~/.muscle/system.db` if you use related-project memory or
   model packs
3. open the project and run `muscle status` or `muscle settings show` once so
   additive migrations and drift-repair hooks can settle
4. run `muscle model status` to confirm the effective canonical model and
   model-pack policy
5. run `muscle memory related --refresh` if you want the related-project catalog
   refreshed against the current repo fingerprint
6. if this project will rely on overlays in production, run
   `muscle long-eval benchmark --enforce-gates` before depending on them

## Restore Order

When recovering both project and global state:

1. close MUSCLE or stop active flows using the databases
2. restore the project-local backup first
3. restore `~/.muscle/system.db` separately if you need shared model-pack or
   cross-project state
4. reopen MUSCLE and verify the project config, related-project links, and
   model-pack status

## Safety Boundary

The project and global stores are intentionally separate SQLite files. They do
not share tables, and restoring a project backup does not overwrite the global
system database.

Release-hardening tests cover:

- upgrade of existing project databases without data loss
- system-db version and integrity checks
- explicit separation between project-local and global tables
- backup guidance that calls out the global-system exclusion clearly
