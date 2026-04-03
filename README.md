# 💪 MUSCLE

### *MiniMax Unified Self-Correcting Learning Engine*

---

> **Give your code more muscle.**  
> A local-first, self-learning code review and iterative code-generation CLI that remembers your codebase — powered by MiniMax M2.7.

---

## ⚡ What Is MUSCLE?

MUSCLE is a CLI tool that makes your AI coding assistant **get smarter every time you use it**.

| What it does | Why it matters |
|---|---|
| 🔍 **Reviews code** with static analyzers + M2.7 semantic analysis | Catches bugs *and* design flaws |
| 🧠 **Remembers your codebase** in `.muscle/CLAUDE.md`, `.muscle/AGENT.md`, `.muscle/MEMORY.md` | Claude never makes the same mistake twice |
| 🔄 **Iterative generation** with generate → evaluate → evolve loops | Produces working, tested code |
| 🛠️ **Auto-fixes** safe issues, plans risky ones | Saves hours of manual review |
| 🌙 **Nightly background reviews** | Wakes up to a report of what changed |

**Core philosophy:** M2.7 is cheap enough to run constantly. If it learns your project, it approximates Claude Opus quality at a fraction of the cost.

---

## 🎬 Quick Start

```bash
# 1. Install (one line)
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash

# 2. Set your API key
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"

# 3. Initialize your project
muscle init

# 4. Review code — pick your mode
muscle review --target ./src --mode review        # 📖 Read-only report
muscle review --target ./src --mode auto-fix      # 🔧 Auto-fix safe issues
muscle review --target ./src --mode hybrid        # ⚡ Fix low-risk, plan high-risk
muscle review --target ./src --mode pressure      # 🔥 Adversarial stress-test

# 5. Or run the generation loop
muscle run --task "Build a REST API with auth" --language python --output ./out
```

**That's it.** No cloud account. No server. No ops.

---

## 🚀 Core Features

### Code Review That Learns

```
muscle review --target ./src --mode auto-fix
```

- Runs **Ruff, ESLint, TSC, Clippy** (static) + **M2.7 semantic analysis**
- Classifies issues by **severity**, **category**, and **fixability**
- Auto-fixes what it can, hands off what it can't
- Writes learnings to `.muscle/CLAUDE.md` — so **Claude remembers next time**

### Iterative Code Generation

```
muscle run --task "CLI tool with argparse" --language python --output ./gen
```

- **Generate** → **Evaluate** (compiler, tests, linters) → **Evolve** on failure
- Resumes from saved sessions — stop and pick up where you left off
- Tracks token budgets, enforces cost limits

### Per-Project Memory

MUSCLE builds three memory files as it works:

| File | What it stores |
|---|---|
| `.muscle/CLAUDE.md` | Project conventions, patterns, anti-patterns |
| `.muscle/AGENT.md` | How to work with this specific codebase |
| `.muscle/MEMORY.md` | Learned rules, decisions, recurring issues |

Over time, **Claude Code becomes a domain expert on your repo** — at negligible extra cost.

---

## 🎛️ Review Modes

| Mode | What it does |
|------|---|
| `review` | Scan and report — no changes |
| `auto-fix` | Apply fixes for issues classified as safe |
| `plan` | Generate a markdown handoff plan (no code changes) |
| `hybrid` | Auto-fix low-risk issues, plan high-risk ones |
| `pressure` | Adversarial mode — stress-tests design and hidden failure modes |

---

## 📁 Project Structure

```
.muscle/                          # Created by `muscle init`
├── CLAUDE.md                     # 🧠 Project conventions & patterns
├── AGENT.md                      # 🤖 How Claude should work with this repo
├── MEMORY.md                     # 📝 Learned rules and decisions
├── knowledge/strategies.db       # 🗄️ SQLite: evolved strategies
├── review_kb/review_kb.db       # 🗄️ SQLite: review findings & patterns
├── sessions/<session_id>/        # 💾 Iteration history + artifacts
├── reports/                      # 📊 Nightly + ad-hoc review reports
└── config.yaml                   # ⚙️  Per-project settings
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     muscle CLI                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐      │
│  │  review  │   │   run    │   │     tui      │      │
│  └────┬─────┘   └────┬─────┘   └──────┬───────┘      │
│       │               │                 │               │
│       ▼               ▼                 ▼               │
│  ┌─────────────────────────────────────────────┐       │
│  │            ReviewController                 │       │
│  │  StaticAnalyzer → CodeReviewer → FixGen    │       │
│  └──────────────────────┬──────────────────────┘       │
│                         ▼                               │
│  ┌─────────────────────────────────────────────┐       │
│  │           LearningPipeline                   │       │
│  │  MemoryManager → PatternDetector → Skills   │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │            LoopController                    │       │
│  │  CodeGenerator → EvaluatorRegistry → Evolver│       │
│  └─────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) for the full deep-dive.

---

## 🔌 Claude Code Plugin

Install as a plugin for seamless integration:

```bash
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

Then use slash commands directly in Claude Code:

```
/muscle:review    # Run a review on selected code or files
/muscle:pressure   # Adversarial review mode
/muscle:status     # Show current review/job status
/muscle:history    # List past review sessions
/muscle:probe      # Check background shadow jobs
/muscle:rescue     # Abort a stuck session
```

---

## 📦 Installation

### Option 1: One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
```

### Option 2: Manual

```bash
git clone https://github.com/LivingEthos/muscle.git
cd muscle
uv sync              # Install deps with uv
uv pip install -e .  # Install CLI
```

### Option 3: Claude Code plugin

```bash
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

---

## 🛠️ All Commands

| Command | Description |
|---------|-------------|
| `muscle init` | Initialize `.muscle/` for the current project |
| `muscle review` | Review code (`review`, `auto-fix`, `plan`, `hybrid`, `pressure`) |
| `muscle run` | Start the generate → evaluate → evolve loop |
| `muscle check` | Single-shot validation without the full loop |
| `muscle history` | List persisted sessions |
| `muscle resume` | Resume an incomplete session |
| `muscle abort` | Abort a running session |
| `muscle probe` | Show shadow review job status |
| `muscle diagnosis` | Show completed shadow review results |
| `muscle nightly` | Manage nightly review metadata & reports |
| `muscle kb` | Inspect strategy knowledge base |
| `muscle cost` | Inspect token/cost usage |
| `muscle improve` | Self-improvement log explorer |
| `muscle tui` | Launch the terminal UI |
| `muscle uninstall` | Remove all `.muscle/` data |

Run `muscle --help` for the full command surface.

---

## 🌐 Supported Languages

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![JavaScript](https://img.shields.io/badge/JavaScript-ES2024+-yellow) ![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-blue) ![Go](https://img.shields.io/badge/Go-1.21+-00ADD8) ![Rust](https://img.shields.io/badge/Rust-1.70+-orange) ![Java](https://img.shields.io/badge/Java-17+-red) ![C++](https://img.shields.io/badge/C++-17+-00599C)

---

## 🔒 Security & Privacy

- **Local-first**: All data stays on your machine by default
- **No telemetry**: Zero tracking, zero phone-home
- **Memory is yours**: `.muscle/` data never leaves your environment
- **API key only**: MUSCLE only needs your MiniMax API key — no other credentials

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Built with 💪 by [LivingEthos](https://github.com/LivingEthos)**  
**Powered by [MiniMax M2.7](https://www.minimax.io/)**

*Give your code more muscle.*
</div>
