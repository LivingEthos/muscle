<p align="center">
  <img src="docs/assets/muscle-github-hero.svg" alt="MUSCLE project-first code review loop" width="100%">
</p>

<h1 align="center">MUSCLE</h1>

<p align="center">
  <strong>MiniMax Unified Self-Correcting Learning Engine</strong>
</p>

<p align="center">
  Project-local code review memory, Claude/Codex plugin workflows, and evidence-backed
  diagnostics for AI-assisted software teams.
</p>

<p align="center">
  <a href="https://github.com/LivingEthos/muscle"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-LivingEthos%2Fmuscle-113B2C?logo=github"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-2E6F95?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-8A6F3D">
  <img alt="Plugin" src="https://img.shields.io/badge/Claude%20%2B%20Codex-plugin-1F7A5B">
</p>

---

## What MUSCLE Is

MUSCLE is a local-first review companion for AI coding workflows. It lets a host
agent such as Claude Code or Codex delegate focused review work to MUSCLE, then
keeps the useful lessons inside the current repository instead of turning one
project's history into a global default.

It is built around one rule:

> **Project-local memory stays primary.** Related-project lessons, model packs,
> filters, and discovery reports are optional overlays until they are trusted or
> validated for the current repo.

## Why It Is Different

| Capability | What it gives you |
|---|---|
| **Self-learning review** | Static analyzers plus MiniMax semantic review, with bounded project memory that improves future runs. |
| **Claude and Codex plugin bundle** | Slash-command workflows, hooks, command docs, assets, and diagnostics packaged together. |
| **Evidence over vibes** | Command evidence records parser tier, exit state, compact excerpts, digests, and token-saving estimates. |
| **Release-oriented diagnostics** | `muscle doctor` checks plugin manifests, hooks, command-doc parity, assets, runtime state, and local setup warnings. |
| **Cost visibility** | `muscle savings` summarizes local token, cache, parser, and command-output compaction evidence. |
| **Safe discovery** | `muscle discover` reports missed review/check opportunities without mutating project memory. |
| **Trust-gated filters** | `muscle filters verify` only accepts project-local output filters after digest-backed trust checks. |

## Quick Start

### 1. Install the CLI

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
```

For development from a checkout:

```bash
uv sync --extra dev
uv run muscle --help
```

### 2. Configure an API key

MUSCLE review and generation flows call a model API. Claude Code subscription
access is useful as the host UI, but it is separate from the API key MUSCLE uses
for its own review calls.

```bash
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"
```

China endpoint:

```bash
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
```

### 3. Initialize a project

```bash
muscle init --related-mode suggest --pack-mode suggest
muscle status
muscle doctor
```

### 4. Review code

```bash
muscle review --target ./src --mode review
```

Machine-readable output:

```bash
muscle review --target ./src --mode review --format json
```

### 5. Inspect evidence

```bash
muscle savings
muscle discover
muscle filters verify
muscle doctor --json
```

## Claude Code Plugin

Install from the marketplace:

```text
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

Or load a local checkout while developing:

```bash
claude --plugin-dir ./tools/muscle/plugin
```

High-value slash commands:

| Command | Use it for |
|---|---|
| `/muscle:review` | Standard project review with severity-ranked findings. |
| `/muscle:pressure` | Adversarial review that challenges assumptions and failure modes. |
| `/muscle:rescue` | Deep investigation when a bug needs focused analysis. |
| `/muscle:doctor` | Plugin lifecycle, manifest, hook, asset, and local-state diagnostics. |
| `/muscle:savings` | Token, cache, parser, and command-output savings evidence. |
| `/muscle:discover` | Read-only missed-opportunity discovery from imported host sessions. |
| `/muscle:filters` | Trust-gated command-output filter verification. |
| `/muscle:status` | Shadow review and runtime status. |
| `/muscle:setup` | Review-gate and hook configuration. |

The plugin bundle lives in `tools/muscle/plugin/` and includes:

```text
tools/muscle/plugin/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── .codex-plugin/
│   └── plugin.json
├── assets/
│   └── muscle-mark.svg
├── commands/
├── hooks/
│   └── hooks.json
└── hooks.json
```

## Codex Plugin Bundle

The same plugin directory also carries a Codex manifest and root hook file.
MUSCLE does not create repo-local `.codex/` assets during setup; the bundle is
kept inside `tools/muscle/plugin/` so packaging and diagnostics can verify it.

If your local Codex build has a plugin validator, run it against:

```text
tools/muscle/plugin/.codex-plugin/plugin.json
tools/muscle/plugin/hooks.json
```

If no Codex validator command is available, treat that check as skipped rather
than failed. `muscle doctor --json` still reports manifest, hook, asset, and
command-doc parity evidence.

## How The Review Loop Works

```text
Host agent plans scope
        |
        v
MUSCLE reviews targeted code
        |
        v
Static analyzers + model review produce findings
        |
        v
Command evidence, savings, and parser tiers are recorded locally
        |
        v
Useful lessons update bounded project memory
        |
        v
doctor / long-eval / tests validate release readiness
```

Generated `.muscle/active-review.md` files are convenience snapshots. The
authoritative state remains in project-local databases and bounded memory files.

## Command Families

Use `muscle --help` for the complete command tree.

| Surface | Main commands |
|---|---|
| Project control | `muscle init`, `muscle enable`, `muscle disable`, `muscle status`, `muscle settings show` |
| Review and generation | `muscle review`, `muscle run`, `muscle check`, `muscle history`, `muscle resume`, `muscle abort` |
| Evidence and operations | `muscle doctor`, `muscle savings`, `muscle discover`, `muscle filters verify` |
| Memory and overlays | `muscle memory status`, `muscle memory history`, `muscle memory related`, `muscle memory import-project` |
| Model and packs | `muscle model status`, `muscle model history`, `muscle model select`, `muscle model packs install` |
| Evaluation | `muscle long-eval run`, `muscle long-eval reports`, `muscle long-eval benchmark --enforce-gates` |
| Utilities | `muscle kb`, `muscle cost`, `muscle improve`, `muscle notes`, `muscle skills list`, `muscle agents list` |

## Storage Model

Per-project state:

```text
.muscle/
├── config.yaml
├── project_memory.db
├── active-review.md
├── CLAUDE.md
├── AGENT.md
├── MEMORY.md
├── skills/
├── agents/
├── sessions/
├── reports/
│   └── release_evidence/
├── knowledge/
│   └── strategies.db
└── review_kb/
    └── review_kb.db
```

Shared state:

```text
~/.muscle/
├── system.db
├── model-pack-cache/
├── shadow_jobs.json
├── cache/
│   └── cache.db
└── prompts/
```

## Privacy And Safety

- API keys are read from environment variables or explicit local settings; they
  should not be committed to the repository.
- Project memory stays in the project unless you explicitly import, export, or
  submit a model-pack candidate.
- Discovery is read-only by default.
- Project-local output filters are ignored until they pass trust checks.
- `muscle doctor` is observational unless you ask it to refresh local snapshots.

## Development

```bash
uv sync --extra dev
uv run mypy tools/muscle/
uv run ruff check tools/muscle/
uv run ruff format --check tools/muscle/
uv run pytest tests/ -v
```

Build and inspect a package:

```bash
uv build --out-dir /tmp/muscle-dist
python -m zipfile -l /tmp/muscle-dist/*.whl | rg 'plugin|savings|discover|filters'
```

## Release Evidence

The current plugin-readiness pass validates:

- Claude plugin manifest and marketplace metadata
- Codex manifest, root hooks, and shared assets
- command-doc parity across plugin commands
- `muscle review --format json` as parseable JSON from the first stdout byte
- `muscle savings --json`, `muscle discover --json`, and `muscle filters verify --json`
- full type, lint, format, package, and test gates

See [release notes: plugin readiness and evidence surfaces](docs/release-notes-2026-05-01-plugin-readiness.md).

## License

MUSCLE is released under the [MIT License](LICENSE).

Related policy docs:

- [Privacy notes](docs/PRIVACY.md)
- [Security policy](SECURITY.md)
- [Terms](docs/TERMS.md)
