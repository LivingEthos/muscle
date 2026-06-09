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
├── m27_client.py               # MiniMax M3 API client
├── budget_manager.py            # Token budget tracking
├── session_manager.py           # Session persistence to disk
├── strategy_kb.py              # SQLite + VSS knowledge base
├── code_generator.py           # M3 code generation
├── evolver.py                  # M3 strategy evolution
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
│   ├── code_reviewer.py        # M3 semantic review with pressure mode
│   ├── review_controller.py    # Review orchestration
│   ├── review_kb.py           # Review knowledge base
│   ├── fix_generator.py        # M3 fix generation
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
│   ├── long_eval_runner.py    # Manual deep evaluation with reports
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
| `muscle long-eval` | ✅ | Manual deep evaluation (run/reports/cleanup) |

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

<!-- MUSCLE_PUBLISHED_START -->
### Methodology
- Think before coding: state assumptions; if multiple interpretations fit, surface them.
- Simplicity first: ship the minimum code that solves the problem.
- Surgical changes: touch only what the task requires; match existing style.
- Goal-driven execution: define the verification check first, then loop until it passes.

### Delegation Protocol (Plan-Then-Hand-Off)
You (Claude Code / Codex) are the planner and synthesizer. MUSCLE's MiniMax M2.7 agents are the execution muscle — they do bulk, mechanical work at ~5–10× lower token cost per equivalent pass.

Division of labor:
- **You do:** understand intent, form the approach, make architectural and UX calls, write a focused plan, integrate results, present to the user.
- **MUSCLE does:** execute that plan — bulk code reviews across many files, generating fix candidates, running test/type-check sweeps, collecting diagnostics, validating changes, pattern scans.

Once you've decided what needs to happen, write a concise plan and hand execution to MUSCLE:
- Multi-file code review, bug hunting, security audit → `/muscle:review` with a targeted scope and focus.
- Deep investigation of a specific failure → MUSCLE rescue agent (`/muscle:rescue`).
- Validating a fix, running tests / type-checks / linters → MUSCLE verification agent.
- Pressure-testing a design you've proposed → `/muscle:pressure`.

Keep the planning with you. Do not ask MUSCLE to plan the work. Do not do the bulk execution yourself. When MUSCLE reports back, integrate and decide — cite the MUSCLE session id so follow-ups stay linked. If MUSCLE's output is clearly off-target on a novel problem (empty pattern memory, low confidence across findings), fall back to direct reasoning.

_These commands require the MUSCLE plugin bundle to be active in this project (for example, the Claude or Codex plugin bundle under `tools/muscle/plugin`). Without it, reason directly._

### Effort & Tool Guidance
- On Claude Code (Opus 4.8): run MUSCLE fix-application flows at `xhigh` effort; summarization-only at `high`. In auto mode, proceed through delegations without confirmation prompts.
- Opus 4.8 interprets instructions literally. If a MUSCLE finding is ambiguous, ask the user before generalizing.
- Opus 4.8 provides its own progress updates — do not add interim summary instructions.

### Critical Rules
- Silent fallback to 'adaptive' for unknown stages hides typos and masks quality regressions — Either (a) raise KeyError for unknown stages so refactors fail loudly at the first call site, or (b) at minimum emit a warnings.warn(..., RuntimeWarning) or structured log entry each time an unknown stage is resolved. If a default must be kept, it should be the cheapest mode (disabled), not the most expensive, to fail safe toward lower resource consumption. (score: 16.5, validated: 1x)
- Locking is partial: update uses file lock but prune and consolidate do read-then-write — Route ALL file mutations through update_text_file_locked or a sibling helper with the same locking contract. Add an integration test that fires 100 concurrent writers plus 1 pruner plus 1 consolidator and asserts no lost entries. (score: 16.5, validated: 1x)
- consolidate_memories lets an LLM silently delete entries with no audit and no rollback — Write to a temp file, compare counts against the original, abort if the new set is less than 50% the old size or missing timestamp prefixes. Take a backup (filepath.with_suffix(.bak)) before overwrite. Return a structured result (original_count, new_count, removed_ids) so callers can detect anomalies. Fix the always-returns-0 bug. (score: 16.5, validated: 1x)
- Telemetry sink race condition on shared m27_client — Wire a per-scenario sink through constructor injection or a context manager that does not mutate shared client state. Hold a process-wide lock around set/restore or, better, instantiate a dedicated M27Client per scenario so no shared mutable sink exists. (score: 16.5, validated: 1x)
- Unvalidated path traversal via fixture manifest — After every resolve() assert resolved.is_relative_to(self.fixture_root) and reject otherwise. Use shutil.copytree(symlinks=False) plus a pre-walk that rejects any symlink. Treat the manifest as untrusted input and validate it against a JSON schema before use. (score: 16.5, validated: 1x)
- Evidence threshold and DB checks silently bypassed when ProjectMemory unavailable — Fail closed. If ProjectMemory is None, raise RuntimeError or return False with reason 'safety subsystem unavailable'. Never default to permissive behavior on a security boundary. (score: 16.5, validated: 1x)
- Non-atomic write of LLM-generated content overwrites agent file with no rollback — Write to a sibling temp file (agent_path.with_suffix('.md.tmp')), fsync, then os.replace() to atomically swap. On failure, the original is untouched. Verify the temp file contains the expected length before swapping. (score: 16.5, validated: 1x)
- TOCTOU race between agent_path.exists() and write_text() — Use a process-level lock (fcntl.flock on a sentinel file in the agents dir) keyed by agent_name. Or make the existence check + write atomic via temp-file rename with O_EXCL. Or enforce uniqueness at the DB layer with a UNIQUE constraint on (project_path, name) and catch IntegrityError. (score: 16.5, validated: 1x)
- Successful fetch data clobbered when subsequent fetch fails — Per-source state isolation: keep results in local variables per fetch method and accumulate into instance attributes only at the end. On per-source failure, log clearly and use cached data for THAT source only without touching other sources' results. Add a 'stale' flag to results so downstream code knows freshness. (score: 16.5, validated: 1x)
- Untrusted upstream content embedded into templates enables prompt injection — Pin to specific commit SHAs and verify content hashes match expected values. Use a curated allowlist of known-safe patterns. Sanitize and escape descriptions before embedding: strip non-printable chars, escape markdown and HTML, reject any template containing suspicious patterns (shell commands, URLs, instruction-like text). Never use untrusted community content directly as template source. (score: 16.5, validated: 1x)
- Cache file has no integrity verification enabling trivial cache poisoning — Sign the cache file with HMAC using a key derived from a per-project secret, or store SHA256 hashes alongside entries and verify on load. Use atomic writes (write to temp file, fsync, rename) to prevent partial writes. Set restrictive file permissions (0600) on cache files. Validate schema and reject unknown fields on load. Consider keeping a chain of custody signed by the upstream commit hash. (score: 16.5, validated: 1x)
- Eager import of 14 submodules makes the entire facade hostage to a single failure — Either (a) split the facade into a thin re-export layer with try/except around each import, logging failures and substituting a stub that raises a more informative error on use, or (b) move all 14 submodules to lazy `__getattr__` access like the existing `ReviewBenchmarkRunner` pattern, so the package is always importable. Option (b) is more uniform and avoids the asymmetric design that the current code already partially adopts. (score: 16.5, validated: 1x)
- Exclude pattern matching is dangerously broad and ambiguous — Use a single, well-defined matching algorithm. Document the pattern syntax clearly. Consider using gitignore-style patterns for familiarity. (score: 16.5, validated: 1x)
- File names starting with dash interpreted as command-line options — Use a -- separator before positional arguments (cmd.append('--'); cmd.extend(files)), or validate file names to reject those starting with a dash. (score: 16.5, validated: 1x)
- Silent exception swallowing masks agent crashes as clean reviews — Track failed agents in a separate dict mapping agent_name to exception class and message. Log at WARNING with full traceback. Return a typed ReviewResult with findings, failed_agents, and partial flag. Refuse to mark a review complete if any required agent failed. (score: 16.5, validated: 1x)
- Synthesize fuzzy-bucketing silently merges semantically distinct issues — Bucket by (file_path, line_number, category, cwe_id) and only dedupe when all four match. Restrict fuzzy title merging to issues from the same source_agent or with the same cwe_id. Preserve all distinct suggested_fix values as a list. Never merge across different IssueCategory values. (score: 16.5, validated: 1x)
- TOCTOU race in path containment check undermines all downstream file ops — Canonicalize all input paths up front and pass resolved Path objects through the entire pipeline. Use O_NOFOLLOW for sensitive reads, and re-validate at each trust boundary. (score: 16.5, validated: 1x)
- Worktree delta apply is non-atomic; partial corruption of main worktree is unrecoverable — Use a journal/staging pattern: apply delta to a temp directory, fsync, then rename atomically per file. Maintain a reverse-delta for rollback. Verify the resulting tree before committing the apply. (score: 16.5, validated: 1x)
- Global MUSCLE_THINKING_MODE override is a footgun and a privilege-escalation vector — Either (a) restrict the override to a safe subset of stages (e.g., only the 'disabled'-by-default formatting stages) and refuse to override 'adaptive'-by-default stages; (b) require an explicit per-stage override syntax (e.g., MUSCLE_THINKING_MODE_OVERRIDE=fix_generation:disabled,verification:adaptive); or (c) at minimum emit a loud warning at startup if the env var is set, and log every call site that is affected. The override should never be fully silent. (score: 10.899999999999999, validated: 1x)
- THINKING_POLICY is a module-level mutable dict with no immutability guarantee — Use types.MappingProxyType({...}) to make the dict read-only at runtime while preserving dict-lookup syntax. Alternatively, store the policy in a frozen dataclass, a NamedTuple, or just use an if/elif chain with hardcoded values. The current design is mutable for no benefit. (score: 10.899999999999999, validated: 1x)
- No validation that THINKING_POLICY values are in VALID_THINKING_MODES, drift is silent — Add a module-level assertion or post-import sanity check: 'for stage, mode in THINKING_POLICY.items(): assert mode in VALID_THINKING_MODES, f"stage {stage} has invalid mode {mode}"'. This runs once at import time and fails fast. Alternatively, build THINKING_POLICY dynamically from VALID_THINKING_MODES. (score: 10.899999999999999, validated: 1x)
- Architectural schizophrenia: DB-first claim enforced only by comments — Either truly delete the read paths and make this class write-only into a dead-letter audit log, or invert the architecture: the class becomes a thin facade that ONLY reads/writes DB and markdown is generated as a derived artifact. Pick one. (score: 10.899999999999999, validated: 1x)
- Prompt injection from user-controlled entry into LLM calls that produce authoritative output — Strip or escape markdown control characters in entries. Use a strict schema-validated parser (e.g., Pydantic) for LLM JSON responses, not json.loads. For consolidate_memories, never blindly trust the LLM ordering; re-validate each returned entry by checking it parses as a real memory line (timestamp prefix, category, etc.). Cap prompt size with an explicit assertion. Consider running the LLM with a system prompt that explicitly forbids including content from user messages in the output. (score: 10.899999999999999, validated: 1x)
- Silent LLM fallback hides quality degradation; caller cannot distinguish no-LLM from LLM-garbage — Return a structured result that distinguishes LLM-succeeded, LLM-failed-used-fallback, and no-LLM-configured. Emit a counter or metric on fallback. For _m27_summarize_entry, refuse to truncate mid-word or mid-tag; find a clean break point or drop the entry entirely. Add a circuit breaker: after N consecutive fallback events, refuse to write rather than write garbage. (score: 10.899999999999999, validated: 1x)
- Empty or zero-scenario benchmark silently passes every gate — Refuse to run when len(scenarios) == 0 for any suite value, or require a minimum scenario count per suite as a hard precondition. Distinguish 'no scenarios' (hard fail) from 'scenarios present but quiet' (real result). (score: 10.899999999999999, validated: 1x)
- Telemetry recorder closed while results may still be read — Defer recorder.close() until after all summaries are computed, or use a context manager scoped to the data-extraction phase rather than the controller-run phase. Snapshot the events into plain Python objects inside the try block. (score: 10.899999999999999, validated: 1x)
- Reports directory is shared mutable state created in __init__ — Write to a temp file in the same directory, fsync, then os.replace to the final name. Include a timestamped suffix or a per-run subdirectory. Make mkdir lazy and tied to the actual write call rather than to construction. (score: 10.899999999999999, validated: 1x)
- Stable substring matchers weaken the oracle and hide regressions — Combine exact-text anchors for must-contain tokens with severity gates. Use a small DSL (regex with anchored groups) and a per-finding required-and-forbidden token set, plus a property-based fuzzer that flips one word at a time and asserts the matcher still distinguishes pass/fail. (score: 10.899999999999999, validated: 1x)
- Agent name derived from untrusted pattern with no defense-in-depth sanitization — After constructing the candidate path, call Path.resolve() and verify it is still within self.agents_dir.resolve(). Reject any path that escapes. Additionally, apply a strict allowlist regex (e.g., ^[a-z0-9_-]+$) and reject anything else. Never trust the LLM's output as a filename. (score: 10.899999999999999, validated: 1x)
- can_create_agent() and generate_agent() are not atomic — eviction race — Wrap the entire check+evict+create sequence in a single transaction or file lock. Better: have generate_agent() call can_create_agent() as the single source of truth, and treat the capacity check in generate_agent() as redundant (or remove it). The list_agents() call is also potentially racy with DB writes. (score: 10.899999999999999, validated: 1x)
- Backup failures are logged and ignored — proceed with destructive operation — Make backup a precondition. If backup fails, abort the operation and surface a hard error. At minimum, the user should be able to opt into a 'destructive mode' explicitly. Never silently degrade a safety guarantee. (score: 10.899999999999999, validated: 1x)
- DB updates and file writes are not transactional — partial state on failure — Stage the new content as a pending revision in the DB first, then atomically swap the file (via os.replace), then mark the revision as committed in the DB. If the swap fails, the DB knows there is a pending revision and can recover. (score: 10.899999999999999, validated: 1x)
- Race condition in cache writes and reads causes inconsistent state under concurrent use — Use atomic write pattern: write to a temp file in the same directory, fsync, then os.replace() to the final path. Use file locking (fcntl.flock) around the read-modify-write cycle. Add JSON schema validation on load and on save. Consider a version field in the cache to detect concurrent writers. (score: 10.899999999999999, validated: 1x)
- Fragile regex parser breaks silently on upstream README format changes — Use a proper markdown parser (e.g., mistune, markdown-it-py) rather than regex. Validate that the parsed result is structurally reasonable (minimum expected number of agents). Log a warning when parse yield drops below a threshold compared to the cache. Have a canary entry check. Document the expected README format and version-pin to a specific format version. (score: 10.899999999999999, validated: 1x)
- Hardcoded /main branch assumption fails when repos rename or move default branch — Query the GitHub API to discover the default branch (one extra HTTP call, cached). Or attempt both main and master with a fallback strategy. Better: pin to specific commit SHAs and update them via a controlled release process. This is a known-good vendoring pattern that trades freshness for reliability. (score: 10.899999999999999, validated: 1x)
- Asymmetric lazy loading: `ReviewBenchmarkRunner` is special-cased while 13 siblings are eagerly loaded — Standardize on one of two patterns: either move everything to lazy `__getattr__` (and drop the explicit imports + the explicit `__all__` literal of classes), or remove the lazy escape hatch and use explicit deferred loading only in the modules that genuinely need it. Whichever you pick, the rationale should be documented, and the choice should not be ad hoc per class. (score: 10.899999999999999, validated: 1x)
- `__all__` and `__getattr__` are inconsistent, and `__all__` controls wildcard import security in surprising ways — Make the explicit list the single source of truth. Either add `ReviewBenchmarkRunner` to `__all__` (and accept the cost of the explicit import) or remove the lazy special case entirely. The two surfaces (wildcard imports and attribute access) should agree. (score: 10.899999999999999, validated: 1x)
- Bandit command conflicts with explicit file list causing unpredictable scanning — Remove the -r flag when passing explicit files, or use a single directory argument. Better yet, detect the tool's expected invocation pattern and adapt the file-passing logic accordingly. (score: 10.899999999999999, validated: 1x)
- Parallel tool execution can corrupt shared cache files — Run each tool in an isolated temporary directory with copies of the target files, or use per-tool working directories. At minimum, disable caching for tools that support it. (score: 10.899999999999999, validated: 1x)
- Hard 300-second timeout silently drops all findings — Capture partial output from the subprocess before it times out. Store the partial output in the evidence. Distinguish between tool timed out and tool found no issues in the result. (score: 10.899999999999999, validated: 1x)
- Tool output parsing trusts tool exit codes blindly — Validate parsed output against expected schema. Distinguish between tool found issues and tool encountered an error based on the actual output content. (score: 10.899999999999999, validated: 1x)
- No retry or fallback when tools are missing — Log a WARNING (not INFO) when a tool is missing. Consider falling back to an alternative tool if available. For critical security tools, make their absence a hard failure. (score: 10.899999999999999, validated: 1x)
- Tool output is stored in full including potentially sensitive data — Sanitize tool output before storage. Redact patterns that look like secrets. Limit the size of stored output. (score: 10.899999999999999, validated: 1x)
- Token accounting has write/read race and destructive consume pattern — Acquire self._token_lock inside _record_agent_tokens for every write. Replace pop with a non-destructive get that resets the counter, or use a per-agent deque of usage events drained by exactly one consumer under the lock. Document the threading contract explicitly. (score: 10.899999999999999, validated: 1x)
- Deterministic fast-path skips LLM based on regex false-positives — Never skip the LLM based on a positive finding. Use deterministic findings to AUGMENT the LLM review, not replace it. If cost reduction is the goal, run deterministic in parallel and let synthesis merge. Require the file to be in an allow-list of safe patterns before the fast path triggers. (score: 10.899999999999999, validated: 1x)
- Hardcoded secret regex captures the secret value in findings — Redact the matched value in code_snippet (e.g., replace with a length-and-prefix marker). Never include the literal secret in any field that crosses a trust boundary. Add a post-processing step that scrubs known secret patterns from all output fields. Hash the value to a short fingerprint for recurring detection without storage. (score: 10.899999999999999, validated: 1x)
- Prompt injection via attacker-controlled target_path and static_issues — Treat all external strings as untrusted. Sanitize before logging. Never include raw user content in LLM prompts without explicit delimiters and an instruction to ignore instructions within the content. Use structured input schemas with whitelisted fields. Log a hash or length of input rather than content itself. (score: 10.899999999999999, validated: 1x)
- _fix_locks dict leaks unboundedly and is not shared across controller instances — For multi-process safety use OS-level file locks (fcntl.flock, portalocker). For in-process use, register locks in a WeakValueDictionary. Document that the lock is in-process only. (score: 10.899999999999999, validated: 1x)
- Silent fallback to hybrid mode masks invalid configuration — Validate config.mode in __init__ and add an explicit else branch that raises ValueError. Use an exhaustive match-statement that the type checker enforces. (score: 10.899999999999999, validated: 1x)
- event_callback exceptions abort the review silently and leave partial state — Wrap event_callback in a try/except that logs the failure and continues. Treat event emission as fire-and-forget for observability. (score: 10.899999999999999, validated: 1x)
<!-- MUSCLE_PUBLISHED_END -->


MUSCLE has been tested on itself:
- Found **19 real issues** (4 critical, 6 high, 9 medium)
- JSON recovery successfully extracts findings from truncated responses
- Pressure mode identifies design weaknesses
- All 917 tests pass (7 skipped - Jenkins/mock complexity)
- Test coverage: **77%** overall line coverage, **100%** on types.py, pattern_detector.py, code_review/__init__.py, tui/__init__.py

### Notable issues found in self-review

#### Critical
- `check` command silently used DummyEvaluator for `"python"` language (not `".py"`) — added `LANGUAGE_ALIASES` including `"py"`, `"js"`, `"ts"`, `"rs"`, `"cs"`
- Evaluator commands used `output_dir` as both `cwd` and path arg — linters tried to find `tools/muscle/tools/muscle` — fixed all to use `"."` as path when `cwd=output_dir`
- `muscle run` sessions not persisted — LoopController.run() never called SessionManager.create_session() or save_iteration()/save_session_report() — added session_manager param and all save calls
- Session ID collisions in SessionManager — fixed with UUID-based session IDs
- Untracked-file auto-commit misses in GitAdapter — fixed to handle untracked files properly
- Missing persisted commit hashes in LoopController — fixed to capture and persist git commits
- Unstable fake "content hashes" in SessionManager — fixed to use actual content-based hashing

#### High
- `scle/session-` branch naming in LoopController — fixed to `muscle/session-`
- `WorkerManager` singleton bug — class-level `_initialized` caused subsequent instances to skip `__init__` — fixed to `self.__dict__.get("_initialized")`
- `LoopController._should_continue` returned FAILED status even when abort was requested — fixed with proper precedence
- `DummyGenerator` abort race — 100 iterations completed before abort flag checked — fixed with `time.sleep(0.01)`
- `files_generated` always empty in reports — _build_session_report() hard-coded files_generated=[] — now tracks pre/post file sets and computes diff, passes through IterationResult
- Single-file `muscle check` fails with [Errno 20] Not a directory — evaluators used "." as path but cwd was set to file path — fixed eval_target to use parent dir when target is a file
- False TypeScript match on test files in ProjectBuilder — fixed to exclude test files from TypeScript detection
- Ignored project descriptions in ProjectBuilder — fixed to actually use provided descriptions

#### Medium
- `PyCompileError` signature used string instead of `BaseException` — fixed to `py_compile.PyCompileError(msg, exc_value, file)`
- FileNotFoundError return code is `-2`, not `-1` — updated base.py `_run_command`
- `_should_retry` used string equality instead of substring matching
- `get_max_tokens` returned 1024/2048 instead of actual 500/2000 for SIMPLE/MEDIUM
- Webhook async tests used wrong `AsyncMock` stacking for nested `async with` context managers
- Standard review skips LLM when static analyzers find nothing — _run_review_mode() only called code_reviewer.review() when `if all_static_issues:` — removed guard so LLM review always runs
- Iteration off-by-one — ctx.current_iteration += 1 at line 463, then iter_num = ctx.current_iteration + 1 at line 255 — first iteration reported as "Iteration 2" — fixed to use ctx.current_iteration directly

### Known Remaining Risks

| Module | Coverage | Risk |
|--------|----------|------|
| github_integration.py | 41% | Integration-heavy, most likely to break in production |
| jenkins.py | 58% | Network/process integration with broad exception handling |
| github.py | 64% | API integration with retry logic |
| mcp_client.py | 69% | MCP protocol integration |
| cli.py | 61% | Line 503: partially implemented resume command |

*Last updated: 2026-04-01*
