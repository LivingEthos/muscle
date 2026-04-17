# 💪 MUSCLE

### *MiniMax Unified Self-Correcting Learning Engine*

---

> **Give your code more muscle.**  
> A local-first, project-first code review and iterative code-generation CLI
> that compounds useful memory per repo while keeping cross-project and
> model-specific knowledge optional and bounded.

---

## ⚡ What Is MUSCLE?

MUSCLE is a CLI tool that makes your AI coding workflow improve over time
without turning one project's lessons into another project's defaults.

| What it does | Why it matters |
|---|---|
| 🔍 **Reviews code** with static analyzers + M2.7 semantic analysis | Catches bugs, risky fixes, and design flaws |
| 🧠 **Stores project-owned memory** in `.muscle/project_memory.db` and bounded markdown files | Keeps the current repo authoritative |
| 🔄 **Runs generate → evaluate → evolve loops** | Produces working, validated code instead of one-shot drafts |
| 🔗 **Suggests related-project lessons** | Reuses overlap when helpful without auto-importing it |
| 📦 **Supports model-specific packs** | Applies portable model lessons only when identity is confident or manually selected |
| 📊 **Enforces benchmark gates** | Proves overlays help without regressing the default project-only path |

**Core rule:** project-local memory always stays primary. Related-project lessons
and model packs are overlays, not replacements.

---

## 🎬 Quick Start

```bash
# 1. Install
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash

# 2. Set your API key
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"

# 3. Initialize this project
muscle init --related-mode suggest --pack-mode suggest

# 4. Inspect the project-first state
muscle status
muscle settings show
muscle model status

# 5. Review code
muscle review --target ./src --mode review

# 6. Or run the generation loop
muscle run --task "Build a REST API with auth" --language python --output ./out
```

---

## 🚀 Core Workflows

### Review and Fix

```bash
muscle review --target ./src --mode auto-fix
```

- Runs local static analysis plus M2.7 semantic review
- Classifies issues by severity, category, and fixability
- Auto-fixes safe issues and hands off risky ones
- Learns from the review and updates bounded project memory

### Project-First Growth

```bash
muscle memory related --refresh
muscle memory import-project --project /path/to/other/project --mode snapshot
muscle memory history
```

- Related-project overlap is suggested, never auto-imported
- Imported lessons stay provisional until current-project validation or explicit
  user promotion
- Audit and history views show where external lessons came from and whether they
  helped

### Model Identity and Packs

```bash
muscle model status
muscle model select --canonical-model minimax/m2.7@1
muscle model packs install --canonical-model minimax/m2.7@1
muscle model history
```

- MUSCLE stores both the requested model label and the resolved canonical model
- Anthropic-compatible custom endpoints stay unresolved unless MUSCLE gets
  trustworthy provider evidence or you pick the model manually
- Model packs are explicit overlays keyed to canonical model families

### Benchmarks and Release Gates

```bash
muscle long-eval benchmark --enforce-gates
```

- Runs project-only, related-project, neutral, and model-pack benchmark suites
- Writes release evidence under `.muscle/reports/release_evidence/`
- Fails when overlays regress baseline behavior or violate offline/runtime
  guardrails

---

## 🗂️ Storage Model

### Per-project state

```text
.muscle/
├── config.yaml
├── project_memory.db
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

### Shared global state

```text
~/.muscle/
├── system.db
├── model-pack-cache/
├── shadow_jobs.json
├── cache/
│   └── cache.db
└── prompts/
```

Project-local `project_memory.db` is authoritative for one repo. Shared
`~/.muscle/system.db` stores project fingerprints, model aliases, installed
packs, and submission metadata that are not owned by a single project.

---

## 🧠 Memory Rules

MUSCLE manages three bounded markdown files alongside its database state:

| File | What it stores |
|---|---|
| `.muscle/CLAUDE.md` | Project conventions, anti-patterns, high-signal learned rules |
| `.muscle/AGENT.md` | Repo-specific agent guidance |
| `.muscle/MEMORY.md` | General learned context, recurring issues, and retained notes |

Only project-local lessons can publish directly into authoritative local memory.
Transferred lessons and model-pack lessons must prove themselves first.

---

## 🔌 Claude Code Plugin

Install as a plugin for day-to-day use inside Claude Code:

```bash
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

High-value slash commands:

```text
/muscle:review
/muscle:pressure
/muscle:setup
/muscle:status
/muscle:memory-related
/muscle:memory-history
/muscle:model-status
/muscle:model-history
/muscle:model-select
/muscle:model-pack-install
/muscle:model-pack-submit
/muscle:long-eval-benchmark
```

The plugin follows the same rule as the CLI: project-local memory stays primary;
related-project lessons and model packs are overlays.

---

## 🛠️ Command Families

MUSCLE now has a broader surface than the original review-only workflow. Use
`muscle --help` for the complete command tree.

| Surface | Main commands |
|---|---|
| Project control | `muscle init`, `muscle enable`, `muscle disable`, `muscle status`, `muscle settings show`, `muscle settings model` |
| Review and generation | `muscle review`, `muscle run`, `muscle check`, `muscle history`, `muscle resume`, `muscle abort` |
| Memory and overlays | `muscle memory status`, `muscle memory history`, `muscle memory related`, `muscle memory import-project`, `muscle memory linked` |
| Model and packs | `muscle model status`, `muscle model history`, `muscle model select`, `muscle model packs list/install/update/export-candidate/submit` |
| Evidence and operations | `muscle long-eval run`, `muscle long-eval reports`, `muscle long-eval benchmark --enforce-gates`, `muscle audit list`, `muscle backups list/show/restore` |
| Auxiliary surfaces | `muscle kb`, `muscle cost`, `muscle improve`, `muscle notes`, `muscle skills list`, `muscle agents list`, `muscle optimize` |

---

## 📚 Additional Docs

- [Architecture guide](/Users/frisson1/Desktop/PROJECTS/Minimax-Self-Improving/docs/architecture.md)
- [Migration and data safety](/Users/frisson1/Desktop/PROJECTS/Minimax-Self-Improving/docs/migration-and-data-safety.md)
- [Project-first growth and model-pack roadmap](/Users/frisson1/Desktop/PROJECTS/Minimax-Self-Improving/docs/project-first-growth-model-pack-roadmap.md)
- [Release notes: project-first growth and model-pack release](/Users/frisson1/Desktop/PROJECTS/Minimax-Self-Improving/docs/release-notes-2026-04-16-project-first-growth.md)

---

## 🌐 Supported Languages

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![JavaScript](https://img.shields.io/badge/JavaScript-ES2024+-yellow) ![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue) ![Go](https://img.shields.io/badge/Go-1.21+-00ADD8) ![Rust](https://img.shields.io/badge/Rust-1.70+-orange) ![Java](https://img.shields.io/badge/Java-17+-red) ![C++](https://img.shields.io/badge/C++-17+-00599C)

---

## 🔒 Security & Privacy

- **Local-first**: normal review and run flows stay local and do not add new
  overlay network calls
- **Project-first**: one project's memory does not silently become another
  project's policy
- **Explicit sharing only**: related-project import and model-pack submission
  are opt-in
- **Memory is yours**: `.muscle/` stays in your repo, while shared state lives
  in `~/.muscle/`

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.
