# CLI Command Map

| Field | Value |
|---|---|
| Audience | Terminal users, automation authors, and plugin maintainers |
| Status | Current command-family map |
| Source of truth | [`src/muscle/cli.py`](../../src/muscle/cli.py), [`README.md`](../../README.md) |

The `muscle` CLI can be used without any plugin host. It is also the source of
truth behind `/muscle:*` slash commands.

## Main Families

| Area | Commands |
|---|---|
| Setup and lifecycle | `init`, `enable`, `disable`, `status`, `settings`, `uninstall`, `doctor` |
| Review and validation | `review`, `check`, `lifeline`, `probe`, `diagnosis` |
| Iterative generation | `run`, `history`, `resume`, `abort` |
| Evidence and savings | `savings`, `discover`, `filters`, `cache`, `cost`, `optimize` |
| Memory and learning | `memory`, `kb`, `improve`, `skills`, `agents`, `notes`, `optimize-host-docs` |
| Model and routing | `model`, `route`, `pack` |
| Evaluation and release gates | `long-eval`, `escalation` |
| Operations | `backups`, `audit`, `tui` |

## Useful Help Commands

```bash
muscle --help
muscle review --help
muscle settings --help
muscle memory --help
muscle model --help
muscle long-eval --help
```

## High-Value Command Examples

```bash
muscle init --non-interactive --related-mode suggest --pack-mode suggest
muscle doctor --json
muscle review --target ./src --mode review --severity low
muscle review --target ./src --mode pressure --focus design,failure,reliability
muscle review --target ./src --mode hybrid --execution worktree
muscle check --target .
muscle lifeline --target ./src --prompt "Find the root cause of this failing test"
muscle long-eval benchmark --enforce-gates
```

## Hidden Runtime Command

`muscle _host-hook` is intentionally hidden. It is called by plugin hook files
and should not be promoted as a user command.

```bash
muscle _host-hook --platform claude-code --event session_start
muscle _host-hook --platform codex --event post_write
```

