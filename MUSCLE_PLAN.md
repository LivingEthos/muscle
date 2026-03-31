# MUSCLE - MiniMax Unified Self-Correcting Learning Engine

> "Give your code more muscle"

**Version:** 0.1.0
**Last Updated:** 2026-03-31
**Status:** Phase 7 - Polish & Cloud Sync (Ready for use)

---

## Implementation Progress

### Phase 1: Core Infrastructure ✅ COMPLETE
- [x] Rename SCLE → MUSCLE globally
- [x] Create `.muscle/` directory structure
- [x] Implement SQLite KB schema
- [x] Basic memory file management
- [x] Guided init flow
- [x] JSON recovery improved for truncated responses
- [x] Self-review tested and working

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
- [x] `.muscle/` directory creation with all necessary files

### Self-Review Results

MUSCLE successfully ran self-review on `code_reviewer.py`:
- Found **12 issues** (2 critical, 5 high, 5 medium)
- JSON recovery successfully extracts findings from truncated responses
- Issues identified include:
  - SYSTEM_PROMPT not protected against prompt injection
  - Shared M27Client across threads without synchronization
  - No timeout on M27Client.chat() calls
  - JSON recovery heuristics could discard valid findings

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

## The Compounding Advantage

```
Review #1 → Review #2 → Review #3 → ... → Review #N
(learns)   (remembers)   (evolves)       (expert)
   ↓          ↓           ↓               ↓
"Auth here"  "Known      "Pressure       "This repo
was missed"  pattern"    works better"   knows no bugs"
```

---

## Feature Set

### Core Features (P0)

| Feature | Description |
|---------|-------------|
| **Post-Task Verification** | Review gate runs after every Claude Code task |
| **Root Cause Tracing** | M2.7 traces issues to specific decisions |
| **Auto-Fix / Propose** | Configurable per severity level |
| **Memory File Updates** | CLAUDE.md, AGENT.md, MEMORY.md management |
| **Per-Project KB** | SQLite-based pattern and fix storage |

### Important Features (P1)

| Feature | Description |
|---------|-------------|
| **Strategy Evolution** | Evolves when validated effective |
| **TUI Interface** | Dashboard, reviews, history, settings |
| **Claude Code Plugin** | Slash commands, subagents, hooks |
| **Multi-Project Support** | Auto-detect + TUI switcher |
| **Dynamic Skill Generation** | Creates project-specific skills automatically |
| **Dynamic Agent Generation** | Creates specialized sub-agents for complex tasks |

### Future Features (P2-P3)

| Feature | Description |
|---------|-------------|
| **GitHub Integration** | PRs, comments, issues |
| **Nightly Cron** | Background analysis with morning reports |
| **Cloud Sync** | Optional cross-machine sync |
| **Agent Knowledge Base** | Knowledge base of well-designed agents/skills to reference |

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
│   │   ├── auth-review.md  # Project-specific auth patterns
│   │   ├── api-standards.md # API design patterns
│   │   └── ...
│   └── logs/                # Review logs
│
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

```markdown
<!-- MUSCLE_LEARNED_START -->
<!-- Content managed by MUSCLE -->
<!-- MUSCLE_LEARNED_END -->
```

### What Gets Updated

| File | Contents | Format |
|------|----------|--------|
| `CLAUDE.md` | Project conventions, patterns to avoid, coding standards | Human-readable |
| `AGENT.md` | Agent-specific learnings, review strategies, tool preferences | Structured for agents |
| `MEMORY.md` | Miscellaneous learnings, past issues, verification results | Chronological |

### Update Rules

1. **Bounded sections** - Only edit within markers
2. **No bloat** - Prune old entries when new ones supersede
3. **No duplicates** - Check before adding
4. **Structured format** - Easy to parse and search
5. **User content preserved** - Never modify outside markers

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

---

## Dynamic Skill Generation

MUSCLE can automatically create and maintain specialized skills for the project that the main coding agent can use.

### What It Does

1. **Detects patterns** - Learns recurring issues or conventions in the project
2. **Creates skills** - Generates `.md` skill files tailored to project needs
3. **Updates CLAUDE.md/AGENT.md** - References skills so coding agent uses them automatically
4. **Validates effectiveness** - Tracks if skill usage improves outcomes

### Example Generated Skills

```
.muscle/skills/
├── auth-patterns.md      # "When working with auth, check X, Y, Z"
├── api-conventions.md     # "Our API always uses pagination with cursor"
├── db-migrations.md      # "Always use transactions for multi-table updates"
├── error-handling.md      # "Our error response format is {code, message, data}"
└── testing-standards.md  # "Unit tests must mock external APIs"
```

### Skill Format

```markdown
---
name: auth-patterns
description: Project-specific authentication patterns and pitfalls
triggers:
  - "auth"
  - "login"
  - "token"
  - "jwt"
  - "session"
---

# Auth Patterns for This Project

## Token Validation
When validating auth tokens, always:
1. Check expiration first
2. Verify issuer matches `AUTH_ISSUER`
3. Validate signature using `AUTH_SECRET`

## Common Mistakes to Avoid
- Don't cache token validation results
- Don't log tokens (even partially)
- Don't skip CSRF validation on state-changing endpoints

## Related Files
- `src/auth/tokens.py` - Token utilities
- `src/middleware/auth.py` - Auth middleware
```

### Skill Generation Trigger

Skills are generated when:
- MUSCLE detects a pattern 3+ times
- Pattern has been verified by successful fixes
- Skill would improve future code quality

### Integration with Coding Agent

```markdown
<!-- MUSCLE_SKILLS_START -->
<!-- Use skills from .muscle/skills/ directory when working with auth, APIs, etc -->
<!-- MUSCLE_SKILLS_END -->
```

### Configuration

```yaml
skill_generation:
  enabled: true           # Toggle skill generation
  min_pattern_count: 3    # Patterns seen N times before skill created
  auto_reference: true    # Auto-add to CLAUDE.md/AGENT.md
  validation_required: true # Only create skill after successful fix
```

### Phase Integration

Skill generation is part of Phase 4 (Self-Learning Engine):
- [ ] Skill detector (pattern → skill trigger)
- [ ] Skill generator (M2.7 generates skill content)
- [ ] Skill validator (track usage, validate effectiveness)
- [ ] CLAUDE.md/AGENT.md integration

---

## Dynamic Agent Generation (Future Feature)

MUSCLE can dynamically create specialized sub-agents that the main coding model can invoke for better performance on complex tasks.

### What It Does

1. **Detects complex patterns** - Identifies tasks requiring specialized handling
2. **Creates agents** - Generates Claude Code sub-agent definitions tailored to project needs
3. **Improves over time** - Tracks agent effectiveness and refines them
4. **Learns from best practices** - References knowledge base of well-designed agents

### Example Generated Agents

```
.muscle/agents/
├── auth-specialist.md      # "Expert at auth implementation, follows our patterns"
├── api-designer.md        # "Designs APIs matching our conventions"
├── db-migration-expert.md  # "Safe database migrations with rollback"
├── security-auditor.md    # "Deep security review specialist"
└── test-architect.md      # "Designs comprehensive test suites"
```

### Agent Format

```markdown
---
name: auth-specialist
description: Authentication expert for this project
triggers:
  - "auth"
  - "login"
  - "jwt"
  - "oauth"
  - "session"
capabilities:
  - Implement auth endpoints
  - Review auth code for vulnerabilities
  - Design token refresh flows
system_prompt: |
  You are an authentication specialist for this project.
  Always follow our auth patterns defined in .muscle/skills/auth-patterns.md
  Common mistakes to avoid: ...
---

# Auth Specialist Agent

## This Project's Auth Patterns
[References .muscle/skills/auth-patterns.md]

## Capabilities
- Implement JWT-based auth with refresh tokens
- Add OAuth2 support for Google/GitHub
- Audit existing auth code for vulnerabilities
```

### Agent Knowledge Base

Reference repos for well-designed agents:
- https://github.com/VoltAgent/awesome-claude-code-subagents
- https://github.com/travisvn/awesome-claude-skills

Research needed to:
1. Catalog common agent patterns
2. Identify best practices for agent design
3. Determine which agents are most useful for code review
4. Build templates MUSCLE can refine for project needs

### Agent Generation Trigger

Agents are generated when:
- Complex pattern detected in 3+ reviews
- Task would benefit from specialized handling
- No existing agent handles this domain
- Generated agent validated by successful task completion

### Integration with Main Model

```markdown
<!-- MUSCLE_AGENTS_START -->
<!-- Available agents: auth-specialist, api-designer, security-auditor -->
<!-- Invoke with: /agent auth-specialist -->
<!-- MUSCLE_AGENTS_END -->
```

### Configuration

```yaml
agent_generation:
  enabled: true              # Toggle agent generation
  min_complexity: 3          # Complexity score before creating agent
  max_agents: 10            # Limit agents per project
  auto_reference: true      # Auto-add to CLAUDE.md/AGENT.md
  use_knowledge_base: true   # Reference agent KB for best practices
```

### Phase Integration

Agent generation is part of Phase 4 (Self-Learning Engine):
- [ ] Agent detector (complex pattern → agent trigger)
- [ ] Agent generator (M2.7 generates agent definition)
- [ ] Agent validator (track usage, validate effectiveness)
- [ ] Agent knowledge base integration (future research)
- [ ] CLAUDE.md/AGENT.md integration

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
| `/muscle:rescue` | Delegate investigation |
| `/muscle:status` | Check job status |
| `/muscle:result` | Get results |
| `/muscle:cancel` | Cancel job |
| `/muscle:setup` | Configure |
| `/muscle:help` | Help |

---

## Implementation Phases

### Phase 1: Core Infrastructure ✅ COMPLETE
- [x] Rename SCLE → MUSCLE globally
- [x] Create `.muscle/` directory structure
- [x] Implement SQLite KB schema
- [x] Basic memory file management
- [x] Guided init flow

### Phase 2: TUI ✅ COMPLETE
- [x] Dashboard view
- [x] Review history view
- [x] Settings view
- [x] Knowledge base view
- [x] Project switcher
- [x] Arrow + Enter navigation

### Phase 3: Claude Code Plugin ✅ COMPLETE
- [x] Plugin manifest (`plugin.json`)
- [x] Slash commands (`review`, `pressure`, `rescue`, `status`, `result`, `cancel`, `setup`)
- [x] Subagents (`rescue_agent.md`, `verification_agent.md`)
- [x] Stop hook (`hooks/hooks.json` for review gate)

### Phase 4: Self-Learning Engine ✅ COMPLETE
- [x] **Pattern Detection** - `pattern_detector.py` identifies recurring issues (3+ occurrences)
- [x] **Dynamic Skill Generation** - `skill_generator.py` creates `.md` skills in `.muscle/skills/`
- [x] **Dynamic Agent Generation** - `agent_generator.py` creates sub-agents in `.muscle/agents/`
- [x] **Memory Manager** - `memory_manager.py` handles CLAUDE.md/AGENT.md/MEMORY.md updates
- [x] **Fix Tracking & Validation** - `fix_tracker.py` tracks fix attempts and outcomes
- [x] **Strategy Evolution** - `strategy_evolver.py` evolves strategies based on effectiveness
- [x] **Agent Knowledge Base** - `agent_kb_fetcher.py` fetches from awesome-claude-* repos
- [x] **Memory File Pruning/Dedup** - Built into `memory_manager.py`
- [x] **Skill/Agent Validator** - Built into generators with validation methods
- [x] **CLAUDE.md/AGENT.md Integration** - Memory manager handles updates

### Phase 5: GitHub Integration ✅ COMPLETE
- [x] PR creation with fixes - `github.create_pull_request()`
- [x] PR commenting - `github.create_review()`
- [x] Issue creation - `github.create_issue()`, `github.create_issue_comment()`
- [x] Review status checks - `github.create_check_run()`, `github.update_check_run()`
- [x] GitHub integration layer - `github_integration.py` ties adapter to review workflow

### Phase 6: Background Jobs ✅ COMPLETE
- [x] Nightly cron - `nightly_runner.py` with configurable schedule
- [x] Morning reports - JSON and markdown reports in `.muscle/reports/`
- [x] Shadow mode - ShadowBroker/ShadowWorker already implemented

### Phase 7: Polish & Cloud Sync
- [ ] Cloud sync architecture (future)
- [ ] Performance optimization
- [ ] Comprehensive testing
- [ ] Documentation

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-31 | 0.1.0 | Initial plan created |
| 2026-03-31 | 0.1.1 | Phase 1 complete: SCLE renamed to MUSCLE, self-review working |
| 2026-03-31 | 0.1.2 | Dynamic Skill Generation feature added to Phase 4 |
| 2026-03-31 | 0.1.3 | Phase 2 complete: TUI with dashboard, views, navigation |
| 2026-03-31 | 0.1.4 | Dynamic Agent Generation and Agent Knowledge Base features added |
| 2026-03-31 | 0.1.5 | Phase 3 complete: Claude Code plugin with 7 commands, 2 agents, hooks |
| 2026-03-31 | 0.1.6 | Phase 4 complete: Self-learning engine with pattern detection, skill/agent generation, strategy evolution, agent KB |
| 2026-03-31 | 0.1.7 | Phase 5 complete: GitHub integration with PRs, issues, comments, status checks |
| 2026-03-31 | 0.1.8 | Phase 6 complete: Nightly runner, morning reports, shadow mode |

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
| 2026-03-31 | 0.1.1 | Phase 1 complete: SCLE renamed to MUSCLE, self-review working |
| 2026-03-31 | 0.1.2 | Dynamic Skill Generation feature added to Phase 4 |
| 2026-03-31 | 0.1.3 | Phase 2 complete: TUI with dashboard, views, navigation |
| 2026-03-31 | 0.1.4 | Dynamic Agent Generation and Agent Knowledge Base features added |
| 2026-03-31 | 0.1.5 | Phase 3 complete: Claude Code plugin with 7 commands, 2 agents, hooks |
| 2026-03-31 | 0.1.6 | Phase 4 complete: Self-learning engine with pattern detection, skill/agent generation, strategy evolution, agent KB |

---

*This is a living document. Update as implementation progresses.*
