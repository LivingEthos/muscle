"""
AGENTS.md - MUSCLE Development Guide

Self-learning code review companion built using its own principles:
iterative improvement, multi-agent collaboration, and evaluation-driven development.
"""

# MUSCLE Development Guide

> Self-learning code review companion built using its own principles: iterative improvement, multi-agent collaboration, and evaluation-driven development.

---

## Build / Lint / Test Commands

```bash
# Install dependencies
uv sync

# Run ALL tests
uv run pytest tests/ -v

# Run SINGLE test file
uv run pytest tests/unit/test_loop_controller.py -v

# Run SINGLE test
uv run pytest tests/unit/test_loop_controller.py::test_loop_controller_success_first_iteration -v

# Quality checks (ALL must pass)
uv run mypy tools/muscle/                    # Type checking
uv run ruff check tools/muscle/              # Linting
uv run ruff format --check tools/muscle/     # Formatting

# Auto-fix lint/format issues
uv run ruff check tools/muscle/ --fix
uv run ruff format tools/muscle/

# Verify all checks pass
uv run mypy tools/muscle/ && uv run ruff check tools/muscle/ && uv run ruff format --check tools/muscle/ && uv run pytest tests/ -v
```

---

## Code Style Guidelines

### Imports
- Use `from __future__ import annotations` for forward references and modern syntax
- Group imports: stdlib → third-party → local, with blank lines between
- Use `TYPE_CHECKING` guard for imports only used in type hints
```python
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .loop_controller import LoopContext
```

### Type Annotations
- Use `X | None` NOT `Optional[X]` (modern Python 3.10+)
- Use `dict[str, Any]` NOT `Dict[str, Any]`
- Use `Callable` from `collections.abc` NOT `typing`
- All function parameters and return types MUST be annotated
- Use `# type: ignore[no-any-return]` sparingly for deliberate Any returns

### Naming Conventions
- **Classes**: `PascalCase` (e.g., `LoopController`, `BudgetManager`)
- **Functions/methods**: `snake_case` (e.g., `check_budget`, `evolve_strategy`)
- **Constants**: `SCREAMING_SNAKE_CASE` (e.g., `DEFAULT_TIMEOUT`, `MAX_RETRIES`)
- **Private members**: `_leading_underscore` (e.g., `_session`, `_rate_limiter`)
- **Type variables**: `PascalCase` (e.g., `T`, `ResultT`)

### Formatting
- 4 spaces per indent level (no tabs)
- Max line length: 100 characters (ruff default)
- Use trailing commas in multi-line collections
- One blank line between top-level definitions

### Error Handling
- Never swallow exceptions silently - always log or re-raise with context
- Use descriptive error messages: `"Rate limited (429)"` not `"Error"`
- Return empty/safe values on failure (e.g., `return "", TokenUsage()`)
- Exponential backoff for retryable errors (429, 5xx, timeouts)

### Logging
- Use `logger = logging.getLogger(__name__)` at module level
- Log at INFO level minimum for significant operations
- Include relevant context (session_id, iteration, token usage)
- Never log secrets or API keys

### Docstrings
- Use Google style docstrings
- Every public class/function needs a docstring
```python
def check_budget(self, iteration_cost: int) -> tuple[bool, str]:
    """Check if budget allows proceeding with an iteration.

    Args:
        iteration_cost: Token cost of the next iteration.

    Returns:
        Tuple of (allowed, reason). If not allowed, reason explains why.
    """
```

### File Headers
```python
"""
Module name: brief description

Architecture Decision Record (ADR):
- Why this design choice was made
- Alternatives considered
- Trade-offs made
"""
```

---

## Quality Gates

Each module MUST pass all checks before merging:

| Check | Command | Required |
|-------|---------|----------|
| Types | `uv run mypy tools/muscle/` | Yes |
| Lint | `uv run ruff check tools/muscle/` | Yes |
| Format | `uv run ruff format --check tools/muscle/` | Yes |
| Tests | `uv run pytest tests/` | Yes |

---

## Module Structure

```
tools/muscle/
├── cli.py                      # CLI entry point (click-based)
├── types.py                    # Core data types (RunConfig, SessionReport, etc.)
├── m27_client.py               # MiniMax M2.7 API client
├── budget_manager.py            # Token budget tracking
├── session_manager.py           # Session persistence to disk
├── strategy_kb.py              # SQLite + VSS knowledge base
├── code_generator.py           # M2.7 code generation
├── evolver.py                  # M2.7 strategy evolution
├── loop_controller.py          # Core Generate→Evaluate→Evolve loop
├── self_improver.py            # Self-review and improvement analysis
├── cost_optimizer.py           # Cost estimation and cache
├── interactive.py              # Interactive mode handler
├── project_builder.py           # Project scaffolding generator
├── webhook_notifier.py         # Webhook notifications
├── evaluator_registry.py        # Dynamic evaluator loader (compiler/linter/tester)
├── code_review/                # Code review subsystem
│   ├── __init__.py
│   ├── types.py                # Review-specific types (ReviewConfig, Severity, etc.)
│   ├── code_reviewer.py        # M2.7 semantic review with pressure mode
│   ├── review_controller.py    # Review orchestration
│   ├── review_kb.py           # Review knowledge base
│   ├── fix_generator.py        # M2.7 fix generation
│   ├── fix_tracker.py         # Fix attempt tracking & validation
│   ├── handoff_generator.py   # Markdown handoff plan generation
│   ├── memory_manager.py      # CLAUDE.md/AGENT.md/MEMORY.md updates
│   ├── pattern_detector.py    # Recurring pattern detection (3+ occurrences)
│   ├── skill_generator.py     # Dynamic .muscle/skills/ generation
│   ├── agent_generator.py     # Dynamic .muscle/agents/ generation
│   ├── strategy_evolver.py   # Strategy evolution (when effectiveness ≥ 80%)
│   ├── agent_kb_fetcher.py   # Fetches from VoltAgent/awesome-claude-* repos
│   ├── shadow_broker.py      # Shadow job queue (pending/running/completed)
│   ├── shadow_worker.py       # Background job processor
│   ├── nightly_runner.py      # Nightly cron with morning reports
│   └── static_analyzer.py    # Static analysis via language tools (ruff, eslint, etc.)
├── adapters/                   # External integrations
│   ├── __init__.py
│   ├── github.py              # GitHub REST API (PRs, issues, checks)
│   ├── github_integration.py  # GitHub → review workflow binding
│   ├── git_adapter.py         # Git operations (diff, status, etc.)
│   ├── gitlab.py              # GitLab REST API (MRs, pipelines)
│   ├── jenkins.py             # Jenkins API (build triggers, artifacts)
│   └── mcp_client.py          # MCP server client
├── evaluators/                # Language-specific evaluators
│   ├── __init__.py
│   ├── base.py               # BaseEvaluator abstract class
│   ├── compiler.py            # Python, Node, TypeScript, Go compilers
│   ├── linter.py             # Ruff, Black, ESLint, golangci-lint
│   ├── tester.py             # pytest, Jest, go test
│   └── assertions.py         # Benchmark and output format assertions
├── tui/                       # Terminal UI
│   ├── __init__.py
│   ├── views.py              # Dashboard, Reviews, History, Settings, KB, Fixes views
│   └── project_manager.py    # Project detection, init, config management
└── plugin/                    # Claude Code plugin
    ├── .claude-plugin/
    │   ├── plugin.json       # Plugin manifest
    │   └── marketplace.json   # Plugin marketplace catalog
    ├── commands/              # Slash commands (Markdown)
    │   ├── review.md
    │   ├── pressure.md
    │   ├── rescue.md
    │   ├── status.md
    │   ├── result.md
    │   ├── cancel.md
    │   └── setup.md
    ├── agents/               # Subagents (Markdown)
    │   ├── rescue_agent.md
    │   └── verification_agent.md
    ├── skills/               # Agent skills
    │   └── code-review/
    │       └── SKILL.md      # Model-invoked code review skill
    └── hooks/
        └── hooks.json        # Stop event hook for review gate
```

---

## API Configuration

```bash
# Global endpoint (most users)
export MINIMAX_API_KEY="your-token-plan-api-key"
export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"

# China endpoint
export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
```

---

## CLI Commands

| Command | Status | Description |
|---------|--------|-------------|
| `muscle init` | ✅ | Initialize MUSCLE for a project |
| `muscle review` | ✅ | Code review (review/auto-fix/plan/hybrid/pressure modes) |
| `muscle tui` | ✅ | Terminal UI dashboard |
| `muscle run` | ✅ | Start a new generation session |
| `muscle history` | ✅ | List all sessions |
| `muscle resume` | ⚠️ Partial | Loads session but full resume not yet implemented |
| `muscle abort` | ✅ | Abort a running session (SIGTERM + PID file) |
| `muscle check` | ✅ | Single-shot validation (compiler/linter/tester) |
| `muscle kb` | ✅ | Knowledge base management (stats/export/import/clear) |
| `muscle cost` | ✅ | Cost optimizer (stats/clear) |
| `muscle improve` | ✅ | Self-improvement (report/export/import/clear/prompt) |
| `muscle probe` | ✅ | Shadow job status |
| `muscle diagnosis` | ✅ | Shadow job results |
| `muscle lifeline` | ✅ | Deep-dive investigation |
| `muscle kb knowledge-add` | ✅ | Add strategy to global knowledge base |
| `muscle nightly` | ✅ | Nightly cron management (enable/disable/run/reports/cleanup) |

---

## Development Philosophy

MUSCLE follows the **Generate → Evaluate → Evolve → Repeat** loop:
1. **Generate** code from task + evolved strategies
2. **Evaluate** against compiler, tests, linter
3. **Evolve** strategy based on failures
4. **Repeat** until success or max iterations

### Self-Learning System

MUSCLE learns from every review:
1. **Pattern Detection** - Identifies recurring issues (3+ occurrences)
2. **Skill Generation** - Creates project-specific `.md` skills in `.muscle/skills/`
3. **Agent Generation** - Creates specialized sub-agents in `.muscle/agents/` (max 10)
4. **Strategy Evolution** - Evolves when validated effective (≥ 80% success)
5. **Memory Updates** - Updates CLAUDE.md, AGENT.md, MEMORY.md with project learnings

---

## Commit Message Format

```
[type]: [short description]

[what changed]
[why it was changed]
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`

---

## Claude Code Plugin Integration

The plugin provides these slash commands (installed via `/plugin install muscle@muscle-marketplace`):

| Command | Description |
|---------|-------------|
| `/muscle:review` | Standard review on changes |
| `/muscle:pressure` | Adversarial review (challenges design decisions) |
| `/muscle:rescue` | Deep-dive investigation and bug hunting |
| `/muscle:status` | Check shadow job status |
| `/muscle:result` | Get shadow job results |
| `/muscle:cancel` | Cancel a running shadow job |
| `/muscle:setup` | Configure review gate settings |

### Installing the Plugin

```bash
# Add marketplace and install
/plugin marketplace add LivingEthos/muscle
/plugin install muscle@muscle-marketplace

# Or load locally for development
claude --plugin-dir ./tools/muscle/plugin
```

---

## Memory File Management

MUSCLE uses marker-based editing to update memory files. Each file has its own markers:

```markdown
<!-- MUSCLE_LEARNED_START -->  (CLAUDE.md only)
<!-- MUSCLE_LEARNED_END -->

<!-- MUSCLE_AGENTS_START -->    (AGENT.md only)
<!-- MUSCLE_AGENTS_END -->

<!-- MUSCLE_MEMORY_START -->    (MEMORY.md only)
<!-- MUSCLE_MEMORY_END -->
```

Files managed:
- `CLAUDE.md` - Project conventions, patterns to avoid, coding standards
- `AGENT.md` - Agent-specific learnings, review strategies, tool preferences
- `MEMORY.md` - Miscellaneous learnings, past issues, verification results

### Update Rules
1. **Bounded sections** - Only edit within markers
2. **No bloat** - Prune old entries when new ones supersede
3. **No duplicates** - Check before adding
4. **User content preserved** - Never modify outside markers

---

## Self-Review Results

MUSCLE has been tested on itself:
- Found **19 real issues** (4 critical, 6 high, 9 medium)
- JSON recovery successfully extracts findings from truncated responses
- Pressure mode identifies design weaknesses
- All 509 tests pass (7 skipped - Jenkins/mock complexity)

### Notable issues found in self-review

#### Critical
- `check` command silently used DummyEvaluator for `"python"` language (not `".py"`) — added `LANGUAGE_ALIASES` including `"py"`, `"js"`, `"ts"`, `"rs"`, `"cs"`
- Evaluator commands used `output_dir` as both `cwd` and path arg — linters tried to find `tools/muscle/tools/muscle` — fixed all to use `"."` as path when `cwd=output_dir`
- `muscle run` sessions not persisted — LoopController.run() never called SessionManager.create_session() or save_iteration()/save_session_report() — added session_manager param and all save calls
- Iteration off-by-one — ctx.current_iteration += 1 at line 463, then iter_num = ctx.current_iteration + 1 at line 255 — first iteration reported as "Iteration 2" — fixed to use ctx.current_iteration directly

#### High
- `scle/session-` branch naming in LoopController — fixed to `muscle/session-`
- `WorkerManager` singleton bug — class-level `_initialized` caused subsequent instances to skip `__init__` — fixed to `self.__dict__.get("_initialized")`
- `LoopController._should_continue` returned FAILED status even when abort was requested — fixed with proper precedence
- `DummyGenerator` abort race — 100 iterations completed before abort flag checked — fixed with `time.sleep(0.01)`
- `files_generated` always empty in reports — _build_session_report() hard-coded files_generated=[] — now tracks pre/post file sets and computes diff, passes through IterationResult
- Single-file `muscle check` fails with [Errno 20] Not a directory — evaluators used "." as path but cwd was set to file path — fixed eval_target to use parent dir when target is a file

#### Medium
- `PyCompileError` signature used string instead of `BaseException` — fixed to `py_compile.PyCompileError(msg, exc_value, file)`
- FileNotFoundError return code is `-2`, not `-1` — updated base.py `_run_command`
- `_should_retry` used string equality instead of substring matching
- `get_max_tokens` returned 1024/2048 instead of actual 500/2000 for SIMPLE/MEDIUM
- Webhook async tests used wrong `AsyncMock` stacking for nested `async with` context managers
- Standard review skips LLM when static analyzers find nothing — _run_review_mode() only called code_reviewer.review() when `if all_static_issues:` — removed guard so LLM review always runs

*Last updated: 2026-04-01*

---

*Last updated: 2026-03-31*
