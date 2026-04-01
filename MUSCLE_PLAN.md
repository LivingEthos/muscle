# MUSCLE - MiniMax Unified Self-Correcting Learning Engine

> "Give your code more muscle"

**Version:** 0.1.12
**Last Updated:** 2026-04-01
**Status:** v0.1.12 — Functional, in active development

---

## Executive Summary

MUSCLE is a self-learning code review companion that:
- Runs post-task verification after Claude Code tasks
- Traces root causes of issues through conversation
- Auto-fixes or proposes fixes based on configurable automation
- Updates memory files so Claude NEVER makes the same mistake twice
- Evolves its strategies over time when validated effective
- Works locally with optional cloud sync in the future

**Core Philosophy:** M2.7 is cheap enough to run constantly. If it learns your project, it approximates Claude Opus quality at a fraction of the cost.

---

## Installation

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/LivingEthos/muscle/main/install.sh | bash
```

### Claude Code Plugin marketplace

```bash
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

### Manual

```bash
git clone https://github.com/LivingEthos/muscle.git
cd muscle
uv sync && uv pip install -e .
```

---

## The Compounding Advantage

```
Review #1 → Review #2 → Review #3 → ... → Review #N
(learns)   (remembers)   (evolves)       (expert)
   ↓          ↓           ↓               ↓
"Auth here"  "Known      "Pressure       "This repo
was missed"   pattern"    works better"   knows no bugs"
```

---

## Feature Set

### Core Features (P0) ✅

| Feature | Status | Notes |
|---------|--------|-------|
| **Post-Task Verification** | ✅ | Review gate runs after every Claude Code task |
| **Root Cause Tracing** | ✅ | M2.7 traces issues to specific decisions |
| **Auto-Fix / Propose** | ✅ | Configurable per severity level |
| **Memory File Updates** | ✅ | CLAUDE.md, AGENT.md, MEMORY.md management |
| **Per-Project KB** | ✅ | SQLite-based pattern and fix storage |

### Important Features (P1) ✅

| Feature | Status | Notes |
|---------|--------|-------|
| **Strategy Evolution** | ✅ | Evolves when validated effective |
| **TUI Interface** | ✅ | Dashboard, reviews, history, settings |
| **Claude Code Plugin** | ✅ | Slash commands, subagents, hooks |
| **Multi-Project Support** | ✅ | Auto-detect + TUI switcher |
| **Dynamic Skill Generation** | ✅ | Creates project-specific skills automatically |
| **Dynamic Agent Generation** | ✅ | Creates specialized sub-agents for complex tasks |

### Adapters & Integrations (P1)

| Feature | Status | Notes |
|---------|--------|-------|
| **GitHub Adapter** | ✅ | PRs, comments, issues, status checks |
| **GitLab Adapter** | ✅ | MRs, pipelines (basic) |
| **Jenkins Adapter** | ✅ | Build triggers, artifact retrieval |
| **Git Adapter** | ✅ | diff, status, branch operations |
| **MCP Client** | ✅ | MCP server integration |
| **Claude Code Plugin** | ✅ | See plugin integration below |

### Future Features (P2-P3)

| Feature | Status | Notes |
|---------|--------|-------|
| **Cloud Sync** | ❌ Future | Optional cross-machine sync |
| **Nightly Cron Reports** | ⚠️ Partial | `nightly_runner.py` exists, cron not wired |
| **Shadow Worker Background Jobs** | ⚠️ Partial | Broker/worker exist, need daemonization |

---

## Architecture

### Directory Structure

```
~/.muscle/
├── global_config.yaml       # Global MUSCLE settings
└── global_kb.db            # Optional: cross-project learnings

/path/to/project/
├── .muscle/                 # MUSCLE project directory
│   ├── project.db           # SQLite: patterns, fixes, history
│   ├── config.yaml          # Project config
│   ├── strategy_kb.json     # Evolved review strategies
│   ├── CLAUDE.md           # Project conventions (MUSCLE-managed)
│   ├── AGENT.md             # Agent-specific memory
│   ├── MEMORY.md            # Miscellaneous learnings
│   ├── skills/              # Dynamically generated project skills
│   │   └── ...
│   ├── agents/              # Dynamically generated sub-agents
│   │   └── ...
│   ├── reports/             # Nightly review reports
│   ├── logs/                # Review logs
│   └── agent_kb/            # Cached agent knowledge base
└── .git/
```

### Key Principles

1. **`.muscle/` by default** - Works even without Claude Code
2. **All local first** - Cloud sync is a future feature
3. **Per-project isolation** - Each project has its own KB
4. **Memory file boundaries** - MUSCLE edits only within markers

---

## Configuration Options

### Automation Levels

| Level | Critical/High | Medium/Low | Description |
|-------|---------------|------------|-------------|
| **1: Auto-fix** | Auto-fix | Auto-fix if confident | Maximum automation |
| **2: Propose** | Propose | Propose | Human in loop |
| **3: Hybrid** | Auto-fix | Propose + accept | Balanced |
| **4: Ask** | Ask | Ask | Full control |

### Review Gate Behaviors

| Mode | Critical/High | Medium/Low | Fluidity | Accuracy |
|------|--------------|-----------|----------|----------|
| **Block+Fix** | Auto-fix, then allow | Warn, then allow | High | High |
| **Block All** | Must address | Must address | Medium | Highest |
| **Warn Only** | Notify | Notify | Highest | Medium |
| **Disabled** | No auto | No auto | Highest | User-defined |

---

## Memory File Management

### Marker System

Each memory file has its own marker pair:

| File | Markers |
|------|---------|
| `CLAUDE.md` | `<!-- MUSCLE_LEARNED_START -->` / `<!-- MUSCLE_LEARNED_END -->` |
| `AGENT.md` | `<!-- MUSCLE_AGENTS_START -->` / `<!-- MUSCLE_AGENTS_END -->` |
| `MEMORY.md` | `<!-- MUSCLE_MEMORY_START -->` / `<!-- MUSCLE_MEMORY_END -->` |

### Update Rules

1. **Bounded sections** - Only edit within markers
2. **No bloat** - Prune old entries when new ones supersede
3. **No duplicates** - Check before adding
4. **User content preserved** - Never modify outside markers

---

## Self-Learning System

### Knowledge Bases

| KB | Storage | Purpose | Evolution |
|----|---------|---------|-----------|
| **Pattern KB** | `project.db` | Learn from mistakes | Compounding |
| **Fix KB** | `project.db` | Track what worked | Validation-based |
| **Strategy KB** | `strategy_kb.json` | Evolve review approach | When validated |
| **Memory Files** | `.muscle/*.md` | Human-readable learnings | Continuous |
| **Generated Skills** | `.muscle/skills/*.md` | Project-specific agent skills | When validated |
| **Agent KB** | `.muscle/agent_kb/` | Community agent patterns | From awesome-claude-* repos |

---

## TUI Design

### Navigation
- **Arrow keys** - Navigate
- **Enter** - Select/Confirm
- **q** - Quit/Back

### Views
1. Dashboard (default)
2. Reviews
3. History
4. Settings
5. Knowledge Base
6. Fixes
7. Project Switcher

---

## Claude Code Plugin

### Slash Commands

| Command | Description |
|---------|-------------|
| `/muscle:review` | Standard review on changes |
| `/muscle:pressure` | Adversarial review |
| `/muscle:rescue` | Delegate deep-dive investigation |
| `/muscle:status` | Check job status |
| `/muscle:result` | Get job results |
| `/muscle:cancel` | Cancel running jobs |
| `/muscle:setup` | Configure review gate |

### Plugin Components
- **Commands**: 7 slash commands (review, pressure, rescue, status, result, cancel, setup)
- **Agents**: rescue_agent.md, verification_agent.md
- **Skills**: code-review/SKILL.md (model-invoked skill)
- **Hooks**: Stop event hook runs `muscle review` after each task completion

### Marketplace Distribution

The plugin is distributed via Claude Code's plugin marketplace:

```bash
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace
```

Uses `git-subdir` source to pull from the main repo's `tools/muscle/plugin/` directory.

---

## CLI Commands

| Command | Status | Description |
|---------|--------|-------------|
| `muscle init` | ✅ | Initialize MUSCLE for the current project |
| `muscle review` | ✅ | Review code for issues (5 modes) |
| `muscle tui` | ✅ | Terminal User Interface |
| `muscle run` | ✅ | Start a new generation session |
| `muscle history` | ✅ | List all sessions |
| `muscle resume` | ⚠️ Partial | Loads session, full resume WIP |
| `muscle abort` | ✅ | Abort running session (SIGTERM + status update) |
| `muscle check` | ✅ | Single-shot validation (compiler/linter/tests) |
| `muscle kb` | ✅ | stats / export / import / clear / knowledge-add |
| `muscle cost` | ✅ | stats / clear |
| `muscle improve` | ✅ | report / export / import / clear / prompt |
| `muscle probe` | ✅ | Shadow job status |
| `muscle diagnosis` | ✅ | Shadow job results |
| `muscle lifeline` | ✅ | Deep-dive investigation |
| `muscle nightly` | ✅ | enable / disable / status / run / reports / cleanup |

### Review Modes

| Mode | Description |
|------|-------------|
| `review` | Standard review, reports issues |
| `auto-fix` | Automatically applies fixes for auto-fixable issues |
| `plan` | Generates handoff plan for manual fixes |
| `hybrid` | Auto-fix safe issues, plan for complex ones |
| `pressure` | Adversarial review that challenges design decisions |

---

## Implementation Phases

### Phase 1: Core Infrastructure ✅ COMPLETE
- [x] Rename SCLE → MUSCLE globally
- [x] Create `.muscle/` directory structure
- [x] Implement SQLite KB schema
- [x] Basic memory file management
- [x] Guided init flow
- [x] JSON recovery for truncated responses

### Phase 2: TUI ✅ COMPLETE
- [x] `muscle init` command with guided setup
- [x] Dashboard view with project health
- [x] Reviews view
- [x] History view
- [x] Settings view
- [x] Knowledge base view
- [x] Fixes view
- [x] Project switcher
- [x] Arrow key navigation
- [x] Project auto-detection

### Phase 3: Claude Code Plugin ✅ COMPLETE
- [x] Plugin manifest (`plugin.json`)
- [x] Slash commands (7 commands)
- [x] Subagents (rescue_agent, verification_agent)
- [x] Stop hook (`hooks/hooks.json` for review gate)
- [x] Agent-invoked skill (code-review/SKILL.md)
- [x] Marketplace distribution (`marketplace.json`)

### Phase 4: Self-Learning Engine ✅ COMPLETE
- [x] **Pattern Detection** - `pattern_detector.py` (3+ occurrence threshold)
- [x] **Dynamic Skill Generation** - `skill_generator.py`
- [x] **Dynamic Agent Generation** - `agent_generator.py`
- [x] **Memory Manager** - `memory_manager.py` (3 marker types)
- [x] **Fix Tracking & Validation** - `fix_tracker.py`
- [x] **Strategy Evolution** - `strategy_evolver.py`
- [x] **Agent Knowledge Base** - `agent_kb_fetcher.py` (VoltAgent/travisvn repos)
- [x] **CLAUDE.md/AGENT.md/MEMORY.md Integration**

### Phase 5: External Integrations ✅ COMPLETE
- [x] GitHub adapter (PRs, issues, comments, checks)
- [x] GitLab adapter (MRs, pipelines)
- [x] Jenkins adapter (build triggers, artifacts)
- [x] Git adapter (diff, status, branch ops)
- [x] MCP client (server integration)
- [x] GitHub integration layer (`github_integration.py`)

### Phase 6: Background & Nightly ✅ COMPLETE
- [x] Shadow mode broker/worker (`shadow_broker.py`, `shadow_worker.py`)
- [x] Nightly runner (`nightly_runner.py`)
- [x] Morning reports (JSON + markdown)
- [x] Nightly CLI (`muscle nightly enable/disable/status/run/reports/cleanup`)

### Phase 7: Polish & Future ❌ INCOMPLETE
- [ ] Cloud sync architecture
- [ ] Comprehensive test coverage (current: 917 unit tests, 77% coverage)

---

## Self-Review Results

MUSCLE has been tested on itself:
- Found **19 real issues** (4 critical, 6 high, 9 medium)
- JSON recovery successfully extracts findings from truncated responses
- Pressure mode identifies design weaknesses
- All **917 tests pass** (77% overall line coverage)

### Notable issues found in self-review

#### Critical (Patched)
- `check` command silently used DummyEvaluator for `"python"` language (not `".py"`) — added `LANGUAGE_ALIASES`
- Evaluator commands used `output_dir` as both `cwd` and path arg — fixed to use `"."` as path when `cwd=output_dir`
- `muscle run` sessions not persisted — LoopController.run() never called SessionManager methods
- Session ID collisions in SessionManager — fixed with UUID-based session IDs
- Untracked-file auto-commit misses in GitAdapter — fixed to handle untracked files properly
- Missing persisted commit hashes in LoopController — fixed to capture and persist git commits
- Unstable fake "content hashes" in SessionManager — fixed to use actual content-based hashing

#### High (Patched)
- `scle/session-` branch naming — fixed to `muscle/session-`
- `DummyGenerator` abort race — 100 iterations completed before abort flag checked
- `files_generated` always empty in reports — _build_session_report() hard-coded empty list
- Iteration off-by-one — first iteration reported as "Iteration 2" — fixed to use ctx.current_iteration directly
- False TypeScript match on test files in ProjectBuilder — fixed to exclude test files
- Ignored project descriptions in ProjectBuilder — fixed to actually use provided descriptions

#### Medium (Patched)
- Standard review skips LLM when static analyzers find nothing — removed guard so LLM review always runs
- `get_max_tokens` returned 1024/2048 instead of actual 500/2000 for SIMPLE/MEDIUM

### Known Remaining Risks

| Module | Coverage | Risk |
|--------|----------|------|
| github_integration.py | 41% | Integration-heavy, most likely to break in production |
| jenkins.py | 58% | Network/process integration with broad exception handling |
| github.py | 64% | API integration with retry logic |
| mcp_client.py | 69% | MCP protocol integration |
| cli.py | 61% | Line 503: partially implemented resume command |

---

## Quality Gates

All code must pass before merging:

| Check | Command | Required |
|-------|---------|----------|
| Types | `uv run mypy tools/muscle/` | Yes |
| Lint | `uv run ruff check tools/muscle/` | Yes |
| Format | `uv run ruff format --check tools/muscle/` | Yes |
| Tests | `uv run pytest tests/` | Yes |

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-31 | 0.1.0 | Initial plan created |
| 2026-03-31 | 0.1.1 | Phase 1 complete: Core infrastructure |
| 2026-03-31 | 0.1.2 | Phase 2 complete: TUI with dashboard, views, navigation |
| 2026-03-31 | 0.1.3 | Phase 3 complete: Claude Code plugin with 7 commands, 2 agents |
| 2026-03-31 | 0.1.4 | Phase 4 complete: Self-learning engine (pattern detection, skill/agent generation, strategy evolution) |
| 2026-03-31 | 0.1.5 | Phase 5 complete: External integrations (GitHub, GitLab, Jenkins, MCP) |
| 2026-03-31 | 0.1.6 | Phase 6 partial: Shadow mode, nightly runner, morning reports |
| 2026-03-31 | 0.1.7 | Add curl installer, Claude Code marketplace, code-review SKILL.md |
| 2026-03-31 | 0.1.8 | Fix hooks.json format, marketplace naming, PATH symlink |
| 2026-03-31 | 0.1.9 | Implement muscle abort (SIGTERM + PID tracking), check (single-shot eval), kb knowledge-add (strategy entry), nightly CLI (enable/disable/status/run/reports/cleanup) |
| 2026-04-01 | 0.1.10 | Fix `muscle check` broken for all languages: added missing short-form language aliases (py, js, ts, rs, cs), fixed evaluator commands using output_dir as both cwd and path arg (doubling the path), fixed TscCompiler redundant --project flag, all 509 tests pass |
| 2026-04-01 | 0.1.11 | Expanded test coverage from 509 to 912 tests (77% coverage). Added comprehensive tests for m27_client.py (58 tests, 88% coverage), code_generator.py (31 tests, 66% coverage), loop_controller.py (12 tests, 69% coverage), cli.py run command (7 new tests), static_analyzer.py (56 tests, 77% coverage). All quality gates passing. |
| 2026-04-01 | 0.1.12 | Patched confirmed bugs: Session ID collisions (UUID-based), untracked-file auto-commit misses, missing persisted commit hashes, unstable content hashes, false TypeScript match on tests, ignored project descriptions. Added regression coverage in test_session_manager.py, test_git_adapter.py, test_loop_controller.py, test_project_builder.py. 917 tests pass, 77% coverage. |

---

*This is a living document. Update as implementation progresses.*
