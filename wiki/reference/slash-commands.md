# Slash Commands

| Field | Value |
|---|---|
| Audience | Plugin users, maintainers, and agents |
| Status | Catalog of current `src/muscle/plugin/commands/*.md` files |
| Source of truth | [`src/muscle/plugin/commands/`](../../src/muscle/plugin/commands/), [`src/muscle/plugin/.claude-plugin/plugin.json`](../../src/muscle/plugin/.claude-plugin/plugin.json), [`tests/unit/test_plugin_manifest.py`](../../tests/unit/test_plugin_manifest.py), [`tests/unit/test_plugin_docs.py`](../../tests/unit/test_plugin_docs.py) |

The plugin currently ships 36 command docs under `src/muscle/plugin/commands/`.
Every advertised `/muscle:*` command should have a matching markdown file, and
every markdown file should be advertised by the Claude manifest.

## Review And Investigation

| Slash command | CLI behavior | Use when |
|---|---|---|
| `/muscle:review` | `muscle review --target . --mode review --severity low` | Run standard code review. |
| `/muscle:pressure` | `muscle review --target . --mode pressure --intensity intensive` | Challenge design decisions and failure modes. |
| `/muscle:rescue` | `muscle lifeline --target . --prompt "$ARGUMENTS"` | Investigate a specific bug or suspicious behavior. |
| `/muscle:lifeline` | `muscle lifeline --target . --prompt "$ARGUMENTS"` | Direct deep investigation through M2.7. |
| `/muscle:check` | `muscle check --target .` | Run compiler/linter/test validation without semantic review. |

`/muscle:review` can forward CLI options such as `--format json --output <file>`
and `--no-db`. Use `--no-db` only when the review should skip project-memory,
learning, and optimization writes.

## Lifecycle And Status

| Slash command | CLI behavior | Use when |
|---|---|---|
| `/muscle:setup` | `muscle init`, `enable`, `disable`, settings, and status examples | Initialize or configure a project. |
| `/muscle:doctor` | `muscle doctor`, `muscle doctor --refresh`, `muscle doctor --json` | Diagnose plugin, manifest, hook, asset, and project health. |
| `/muscle:status` | `muscle status`, `muscle status --refresh` | Show project status and active-review state. |
| `/muscle:visualize` | `muscle visualize` | Open Visual DevFlow and stream MUSCLE activity into the project dashboard. |
| `/muscle:settings-show` | `muscle settings show` | Inspect current project configuration. |
| `/muscle:settings-api-key` | `muscle settings api-key` | Inspect or configure API key source. |
| `/muscle:settings-review` | `muscle settings review --execution local|worktree` | Configure review execution mode. |
| `/muscle:settings-model` | `muscle settings model ...` | Configure model, related-project, and pack policy. |

## Evidence And Optimization

| Slash command | CLI behavior | Use when |
|---|---|---|
| `/muscle:savings` | `muscle savings`, `muscle savings --json` | Inspect token/cache/parser/output savings evidence. |
| `/muscle:discover` | `muscle discover`, `muscle discover --since 14`, `--json` | Find missed opportunities without writing memory. |
| `/muscle:filters` | `muscle filters verify|trust|untrust` | Verify and trust command-output filters. |
| `/muscle:optimize-host-docs` | `muscle optimize-host-docs --yes` | Non-destructively optimize root host guidance files. |
| `/muscle:pack` | `muscle pack --task ... --scope ...` | Build reusable context packs. |
| `/muscle:route` | `muscle route --task "$ARGUMENTS" --json` | Classify work for M2.7 vs host execution. |

## Memory And Model Overlays

| Slash command | CLI behavior | Use when |
|---|---|---|
| `/muscle:memory-related` | `muscle memory related` | Find related MUSCLE projects. |
| `/muscle:memory-import-project` | `muscle memory import-project --project ... --mode snapshot|attach` | Import or attach provisional lessons. |
| `/muscle:memory-history` | `muscle memory history` | Inspect lesson usage and memory decisions. |
| `/muscle:model-status` | `muscle model status` | Show resolved model identity and active packs. |
| `/muscle:model-history` | `muscle model history` | Inspect recent model identity events. |
| `/muscle:model-select` | `muscle model select --canonical-model ...` | Set or clear canonical model override. |
| `/muscle:model-pack-install` | `muscle model packs install ...` | Install or update model-pack overlays. |
| `/muscle:model-pack-submit` | `muscle model packs export-candidate`; `muscle model packs submit --draft` | Export and submit candidate packs. |

## Background Work And Evaluation

| Slash command | CLI behavior | Use when |
|---|---|---|
| `/muscle:probe` | `muscle probe` | Check shadow review jobs. |
| `/muscle:diagnosis` | `muscle diagnosis` | Read completed shadow job results. |
| `/muscle:result` | `muscle diagnosis` | Compatibility wrapper for shadow job results. |
| `/muscle:long-eval-reports` | `muscle long-eval reports` | List recent long evaluation reports. |
| `/muscle:long-eval-benchmark` | `muscle long-eval benchmark` | Compare review strategies and release gates. |

## Maintenance And Compatibility

| Slash command | CLI behavior | Use when |
|---|---|---|
| `/muscle:history` | `muscle history` | List generation/review sessions. |
| `/muscle:kb-stats` | `muscle kb stats` | Inspect knowledge-base stats. |
| `/muscle:cancel` | Explains `muscle abort`, `probe`, and `diagnosis` | Stop foreground sessions or inspect background work. |
| `/muscle:nightly-status` | Points to `muscle long-eval reports` | Compatibility command; nightly wording is deprecated. |

## Maintenance Rule

When adding or removing a command:

1. Add or remove the markdown file under `src/muscle/plugin/commands/`.
2. Update `src/muscle/plugin/.claude-plugin/plugin.json`.
3. Update tests if the command maps to a new CLI surface.
4. Update this page and [`../data/commands.yml`](../data/commands.yml).
