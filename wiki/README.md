# MUSCLE Plugin Wiki

| Field | Value |
|---|---|
| Audience | Users, maintainers, release operators, and coding agents |
| Scope | `tools/muscle/` runtime and `tools/muscle/plugin/` bundle |
| Status | Current repo-local wiki database |
| Source of truth | Current repository files, especially [`README.md`](../README.md), [`tools/muscle/cli.py`](../tools/muscle/cli.py), and [`tools/muscle/plugin/`](../tools/muscle/plugin/) |
| Online-docs readiness | Pages are split by topic, use stable slugs, and have matching YAML catalogs under [`data/`](data/) |

MUSCLE is a self-learning code review and developer-ops plugin for Claude Code,
Codex-style hosts, and direct terminal workflows. The plugin layer is intentionally
thin: slash commands, agents, skills, manifests, and hooks route into the `muscle`
CLI, and the CLI/runtime remains the authoritative behavior boundary.

This wiki is designed to work in three ways:

1. GitHub browsing from the repository.
2. Agent reference during future code or release work.
3. Seed content for a future online documentation site.

## Start Here

| Need | Page |
|---|---|
| Install MUSCLE and run the first review | [Quickstart](getting-started/quickstart.md) |
| Understand the plugin bundle | [Plugin Bundle Reference](reference/plugin-bundle.md) |
| Choose the right slash command | [Slash Commands](reference/slash-commands.md) |
| Understand review, fix, and learning flow | [Review Workflows](concepts/review-workflows.md) |
| Give another agent a compact orientation | [Agent Reference](agent-reference.md) |
| Prepare release evidence | [Release Validation](operations/release-validation.md) |
| Build an online docs site from this folder | [Content Model](content-model.md) |

## Wiki Sections

- [Getting Started](getting-started/quickstart.md): installation, first review,
  Claude Code setup, and Codex bundle notes.
- [Concepts](concepts/architecture.md): architecture, review modes, memory,
  model routing, evidence, savings, discovery, and filters.
- [Reference](reference/slash-commands.md): command catalog, CLI map, bundle files,
  hooks, configuration, storage, agents, and skills.
- [Operations](operations/troubleshooting.md): troubleshooting, release gates,
  and security/privacy boundaries.
- [Data](data/pages.yml): structured catalogs for future documentation tooling.

## Current Implementation Notes

- Active runtime package: [`tools/muscle/`](../tools/muscle/).
- Legacy package: `tools/scle/`; do not use it as source-of-truth for current
  plugin docs.
- Plugin command docs: [`tools/muscle/plugin/commands/`](../tools/muscle/plugin/commands/).
- Claude plugin metadata: [`tools/muscle/plugin/.claude-plugin/`](../tools/muscle/plugin/.claude-plugin/).
- Codex plugin metadata: [`tools/muscle/plugin/.codex-plugin/`](../tools/muscle/plugin/.codex-plugin/).
- Per-project state is DB-first in `.muscle/project_memory.db`; markdown memory
  files and `active-review.md` are compatibility or convenience surfaces.

## Important Boundaries

- Do not document `tools/scle/` as active behavior.
- Do not invent a Codex install command unless a target Codex build documents or
  exposes it. This repo currently ships a Codex bundle and hook file.
- Do not treat related-project lessons or model packs as global defaults. They
  are optional overlays; project-local memory remains authoritative.
- Do not hand-edit `.muscle/active-review.md`; it is generated convenience output.
