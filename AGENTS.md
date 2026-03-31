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
├── cli.py                    # CLI entry point
├── types.py                  # Data types
├── m27_client.py             # MiniMax API client
├── budget_manager.py         # Token budget tracking
├── session_manager.py        # Session persistence
├── strategy_kb.py            # SQLite knowledge base
├── code_generator.py         # M2.7 code generation
├── evolver.py                # M2.7 strategy evolution
├── loop_controller.py        # Core loop orchestration
├── self_improver.py          # Self-improvement logic
├── cost_optimizer.py         # Cost optimization
├── interactive.py            # Interactive mode
├── project_builder.py        # Project building
├── webhook_notifier.py       # Webhook notifications
├── evaluator_registry.py      # Evaluator registry
├── code_review/              # Code review subsystem
│   ├── __init__.py
│   ├── types.py              # Review-specific types
│   ├── code_reviewer.py      # M2.7 review with pressure mode
│   ├── review_controller.py  # Orchestrator
│   ├── review_kb.py          # Review knowledge base
│   ├── fix_generator.py      # Fix generation
│   ├── fix_tracker.py        # Fix tracking & validation
│   ├── handoff_generator.py  # Handoff plan generation
│   ├── memory_manager.py     # CLAUDE.md/AGENT.md/MEMORY.md updates
│   ├── pattern_detector.py   # Pattern detection
│   ├── skill_generator.py    # Dynamic skill generation
│   ├── agent_generator.py    # Dynamic agent generation
│   ├── strategy_evolver.py   # Strategy evolution
│   ├── agent_kb_fetcher.py  # Agent KB from awesome-claude-*
│   ├── shadow_broker.py      # Shadow job tracking
│   ├── shadow_worker.py      # Background job processor
│   ├── nightly_runner.py     # Nightly cron & reports
│   └── static_analyzer.py    # Static analysis
├── adapters/                  # External integrations
│   ├── __init__.py
│   ├── github.py             # GitHub adapter
│   ├── github_integration.py # GitHub integration layer
│   ├── git_adapter.py        # Git adapter
│   ├── gitlab.py             # GitLab adapter
│   ├── jenkins.py            # Jenkins adapter
│   └── mcp_client.py         # MCP client
├── evaluators/               # Evaluators
│   ├── __init__.py
│   ├── base.py               # Base evaluator
│   ├── compiler.py           # Compiler evaluator
│   ├── linter.py            # Linter evaluator
│   ├── tester.py             # Test evaluator
│   └── assertions.py         # Assertion evaluator
├── tui/                      # Terminal UI
│   ├── __init__.py
│   ├── views.py              # TUI views
│   └── project_manager.py    # Project management
├── plugin/                   # Claude Code plugin
│   ├── .claude-plugin/
│   │   └── plugin.json       # Plugin manifest
│   ├── commands/             # Slash commands
│   │   ├── review.md
│   │   ├── pressure.md
│   │   ├── rescue.md
│   │   ├── status.md
│   │   ├── result.md
│   │   ├── cancel.md
│   │   └── setup.md
│   ├── agents/               # Subagents
│   │   ├── rescue_agent.md
│   │   └── verification_agent.md
│   └── hooks/
│       └── hooks.json        # Stop hook
└── languages/                # Language support
    └── __init__.py
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

## Development Philosophy

MUSCLE follows the **Generate → Evaluate → Evolve → Repeat** loop:
1. **Generate** code from task + evolved strategies
2. **Evaluate** against compiler, tests, linter
3. **Evolve** strategy based on failures
4. **Repeat** until success or max iterations

### Self-Learning System

MUSCLE learns from every review:
1. **Pattern Detection** - Identifies recurring issues (3+ occurrences)
2. **Skill Generation** - Creates project-specific `.md` skills
3. **Agent Generation** - Creates specialized sub-agents (max 10)
4. **Strategy Evolution** - Evolves when effectiveness ≥ 80%
5. **Memory Updates** - Updates CLAUDE.md/AGENT.md/MEMORY.md

---

## Commit Message Format

```
[type]: [short description]

[what changed]
[why it was changed]

MUSCLE-Iteration: N
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`

---

## Claude Code Plugin Integration

The plugin provides these commands:
- `/muscle:review` - Standard review on changes
- `/muscle:pressure` - Adversarial review
- `/muscle:rescue` - Delegate deep-dive investigation
- `/muscle:status` - Check job status
- `/muscle:result` - Get job results
- `/muscle:cancel` - Cancel running jobs
- `/muscle:setup` - Configure review gate

---

## Memory File Management

MUSCLE uses marker-based editing to update memory files:

```markdown
<!-- MUSCLE_LEARNED_START -->
<!-- Content managed by MUSCLE -->
<!-- MUSCLE_LEARNED_END -->
```

Files managed:
- `CLAUDE.md` - Project conventions, patterns to avoid
- `AGENT.md` - Agent-specific learnings, review strategies
- `MEMORY.md` - Miscellaneous learnings, past issues

---

## Self-Review Results

MUSCLE has been tested on itself:
- Found **12 real issues** (2 critical, 5 high, 5 medium)
- JSON recovery successfully extracts findings from truncated responses
- Pressure mode identifies design weaknesses

---

*Last updated: 2026-03-31*
