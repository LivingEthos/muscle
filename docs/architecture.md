# MUSCLE Architecture and Runtime Guide

Last updated: 2026-04-02

This document explains how the active MUSCLE application works today based on the
implemented `tools/muscle/` package. It is intended to be the source-of-truth
architecture explainer for contributors and users who want to understand the
runtime flow, storage model, and subsystem boundaries.

## What MUSCLE Is

MUSCLE has two primary runtime loops:

1. A generate -> evaluate -> evolve loop exposed by `muscle run`
2. A review -> fix/plan -> learn loop exposed by `muscle review`

Both loops are powered by the MiniMax M2.7 API through an Anthropic-compatible
client and both persist state so the project can compound over time.

`tools/muscle/` is the active package tree.

`tools/scle/` is a legacy predecessor that still exists in the repo, but it is
not the package installed by `pyproject.toml` and it is excluded from coverage.

## Top-Level Runtime Map

```mermaid
flowchart TD
    User["User or plugin command"]
    CLI["tools/muscle/cli.py"]
    Init["muscle init"]
    Run["muscle run"]
    Review["muscle review"]
    Check["muscle check"]
    TUI["muscle tui"]
    Plugin["tools/muscle/plugin"]

    User --> CLI
    Plugin --> CLI

    CLI --> Init
    CLI --> Run
    CLI --> Review
    CLI --> Check
    CLI --> TUI

    Run --> Loop["LoopController"]
    Loop --> Generator["CodeGenerator"]
    Loop --> Evaluators["EvaluatorRegistry + evaluators/*"]
    Loop --> Evolver["Evolver + StrategyKB"]
    Loop --> Sessions["SessionManager"]
    Loop --> Budget["BudgetManager"]
    Loop --> Git["GitAdapter auto-commit"]
    Loop --> Hooks["WebhookNotifier"]
    Loop --> Improve["SelfImprover"]

    Review --> ReviewController["ReviewController"]
    ReviewController --> Static["StaticAnalyzer"]
    ReviewController --> Semantic["CodeReviewer"]
    ReviewController --> Fixes["FixGenerator"]
    ReviewController --> Handoff["HandoffGenerator"]
    Review --> Learning["LearningPipeline"]
    Learning --> Memory["MemoryManager"]
    Learning --> Patterns["PatternDetector"]
    Learning --> Skills["SkillGenerator"]

    Review --> Shadow["ShadowBroker + ShadowWorker"]
    Review --> LongEval["LongEvalRunner"]
```

## Primary Entry Points

### `muscle init`

`muscle init` uses `tui/project_manager.py` to detect the current project and
create the local `.muscle/` workspace. It writes the initial project config and
creates the memory files that MUSCLE later updates.

What it creates immediately:

- `.muscle/config.yaml`
- `.muscle/strategy_kb.json`
- `.muscle/CLAUDE.md`
- `.muscle/AGENT.md`
- `.muscle/MEMORY.md`
- `.muscle/skills/`
- `.muscle/logs/`

Important implementation detail:

- `config.yaml` is currently written with JSON content even though the filename
  ends in `.yaml`

### `muscle run`

`muscle run` is the autonomous generation loop. It optionally scaffolds a
project, generates code, evaluates the output, and evolves the next strategy
until success, budget exhaustion, timeout, abort, or max iterations.

### `muscle review`

`muscle review` is the code review workflow. It combines local static analysis,
M2.7 semantic review, optional fix application, and post-review learning.

### `muscle tui`

`muscle tui` launches the Rich-based terminal UI scaffold in `tools/muscle/tui/`.
It is a real entry point and navigation shell, but many views still render
placeholder/sample data rather than fully live project state.

## The `muscle run` Flow

### Components Involved

- `cli.py` builds the runtime config and dependencies
- `LoopController` owns iteration state and stop conditions
- `CodeGenerator` calls M2.7 and writes generated files
- `EvaluatorRegistry` selects compiler, test, and lint evaluators by language
- `Evolver` analyzes failures and produces the next strategy
- `SessionManager` persists progress under `.muscle/sessions/`
- `BudgetManager` enforces fixed or auto budgets
- `GitAdapter` optionally creates a branch and commit on success
- `WebhookNotifier` emits lifecycle notifications
- `SelfImprover` logs outcomes for later self-analysis

### Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant C as cli.run
    participant L as LoopController
    participant G as CodeGenerator
    participant E as EvaluatorRegistry
    participant V as Evolver
    participant S as SessionManager
    participant I as SelfImprover

    U->>C: muscle run --task ...
    C->>S: create_session(config)
    C->>L: run()
    loop until success or stop condition
        L->>G: generate(task, evolved_strategy, output_dir)
        G-->>L: code_output + token_usage
        L->>E: evaluate(output_dir, language, eval_mode)
        E-->>L: EvaluationResult
        alt evaluation passes
            L->>S: save_iteration(...)
            L->>S: save_session_report(...)
            L->>I: log_session(...)
            L-->>C: success
        else evaluation fails
            L->>V: evolve(task, errors, previous_strategy)
            V-->>L: evolved_strategy
            L->>S: save_iteration(...)
        end
    end
```

### What Happens In Each Iteration

1. `LoopController` optionally pauses for interactive approval or user hints.
2. `CodeGenerator` sends the task and the latest evolved strategy to M2.7.
3. The generator parses fenced code blocks and writes files into `output_dir`.
4. `EvaluatorRegistry` picks evaluators based on detected or supplied language.
5. Evaluation failures are flattened into error lists.
6. `Evolver` turns those errors into a new strategy prompt, optionally using
   similar prior strategies from `StrategyKB`.
7. The iteration result is written to `.muscle/sessions/<session_id>/`.

### Stop Conditions

The run loop stops when one of these is true:

- evaluation passes
- `max_iterations` is reached
- timeout is reached
- user abort is requested
- budget is exceeded
- early exit condition is met, such as passing tests

### Evaluation Modes

`RunConfig.eval_mode` controls how failures are fed back into the evolver:

- `all`: one combined error set per iteration
- `sequential`: evolve once per error
- `parallel`: evaluate tools in parallel, then evolve on the combined result

### Git Behavior

If git is enabled, a successful run can:

- create branch `muscle/session-<session_id>`
- stage changed files
- commit with a MUSCLE session summary
- optionally push the branch

This is wired through `LoopController._auto_commit()` and `adapters/git_adapter.py`.

## The `muscle review` Flow

### Components Involved

- `ReviewController` orchestrates the review mode
- `StaticAnalyzer` runs local tools such as Ruff, ESLint, TSC, Clippy, and more
- `CodeReviewer` asks M2.7 to validate and classify findings
- `FixGenerator` applies suggested code replacements for fixable issues
- `HandoffGenerator` produces markdown plans for issues not auto-fixed
- `LearningPipeline` updates memory files and attempts recurring-pattern skill generation

### Sequence

```mermaid
flowchart TD
    A["muscle review"] --> B["ReviewController.run()"]
    B --> C["StaticAnalyzer.analyze()"]
    C --> D["Static issues"]
    D --> E["CodeReviewer.review()"]
    E --> F["Structured ReviewIssue list"]

    F --> G{"Mode"}
    G -->|review| H["Report issues"]
    G -->|auto-fix| I["FixGenerator.apply_fix_from_suggestion()"]
    G -->|plan| J["HandoffGenerator.generate_handoffs()"]
    G -->|hybrid| K["Fix low/medium + plan high/critical"]
    G -->|pressure| L["Adversarial semantic review"]

    H --> M["LearningPipeline.learn_from_review()"]
    I --> M
    J --> M
    K --> M
    L --> M

    M --> N["MemoryManager updates .muscle/*.md"]
    M --> O["PatternDetector scans ReviewKB history"]
    O --> P["SkillGenerator writes .muscle/skills/*.md"]
```

### Review Modes

- `review`: report issues
- `auto-fix`: apply fix suggestions for fixable issues
- `plan`: produce a handoff plan without editing files
- `hybrid`: auto-fix lower-risk issues and generate a plan for harder ones
- `pressure`: adversarial review that challenges design choices and failure modes

### Static Analysis Layer

`StaticAnalyzer` chooses tools by detected language and runs them concurrently.

Examples:

- Python: Ruff, Pyright, Bandit
- JavaScript: ESLint
- TypeScript: ESLint, TSC
- Go: golangci-lint
- Rust: Clippy
- C/C++: cppcheck
- Java: Checkstyle

The output is normalized into `StaticIssue` records before the semantic pass.

### Semantic Review Layer

`CodeReviewer` groups issues by file, reads source content, and asks M2.7 to:

- confirm whether the issue is real
- classify severity and category
- decide whether the issue is auto-fixable
- suggest a concrete fix when possible

If there are no static findings, `CodeReviewer` can still do a proactive file review.

### Fix and Handoff Layer

`FixGenerator` currently applies the suggested replacement directly to the file,
with a temporary backup during the write. `HandoffGenerator` is used when the
selected mode needs a markdown plan for human follow-up.

## Learning and Memory Flow

The review command calls `LearningPipeline.learn_from_review()` after a review
completes.

### What The Learning Pipeline Does Today

1. Categorizes findings by severity
2. Writes immediate high/critical rules into `.muscle/CLAUDE.md` and related memory files
3. Writes tracked findings into `.muscle/MEMORY.md`
4. Validates and ages existing rules
5. Attempts recurring-pattern detection and skill generation
6. Logs the review session summary

### Memory File Boundaries

`MemoryManager` performs marker-based edits so MUSCLE only updates bounded
sections of the managed markdown files.

Current markers used by the implementation:

- `<!-- MUSCLE_LEARNED_START -->` / `<!-- MUSCLE_LEARNED_END -->`
- `<!-- MUSCLE_MEMORY_START -->` / `<!-- MUSCLE_MEMORY_END -->`

### Important Accuracy Note

The memory-update path is actively wired into the CLI today.

The broader recurring-pattern subsystem is present, but parts of it are more
foundational than fully saturated:

- `PatternDetector` reads from `ReviewKB`
- `ReviewKB` APIs exist for storing reviewed issues and fix effectiveness
- the review controller currently records fix attempts directly during auto-fix
- deeper issue-history population and long-horizon strategy evolution are present
  as modules, but not every advanced path is exercised equally by the CLI

That means the learning loop is real today, but its strongest compounding effect
comes from memory-file updates and persisted session history, with the deeper
pattern/skill ecosystem still maturing.

## Shadow Reviews and Long Evaluations

### Shadow Mode

`muscle review --shadow` uses:

- `ShadowBroker` for persistent job bookkeeping in `~/.muscle/shadow_jobs.json`
- `ShadowWorker` for background processing

The worker runs review jobs in-process and updates status for `muscle probe` and
`muscle diagnosis`.

### Long Evaluation Mode

Long evaluation is a manual deep-review workflow:

- `LongEvalRunner` runs one or more review scans and writes reports to `.muscle/reports/`
- Triggered manually via `muscle long-eval run`

Important implementation detail:

- there is no scheduling or automatic overnight execution
- the deep evaluation is always user-triggered and runs immediately

## Persistence Model

### Per-Project State

These files and directories live under the target project:

```text
.muscle/
  config.yaml                 # JSON content written by ProjectManager
  strategy_kb.json            # Initial project bootstrap file
  CLAUDE.md
  AGENT.md
  MEMORY.md
  logs/
  skills/
  agents/                     # Created on demand by AgentGenerator
  knowledge/
    strategies.db             # StrategyKB SQLite database
  review_kb/
    review_kb.db             # ReviewKB SQLite database
  sessions/
    <session_id>/
      meta.json
      iterations.jsonl
      report.json
      context.json
      artifacts/
  reports/
    long_eval_YYYY-MM-DD.json
    long_eval_YYYY-MM-DD.md
  budget.json                 # Optional auto-budget state
```

### Global State

These files and directories live under the user home directory:

```text
~/.muscle/
  cache/cache.db
  shadow_jobs.json
  improvement_log.json
  prompts/
  <session_id>.pid
  global/strategies.db
  global_review/review_kb.db
```

## Integrations and Their Maturity

### Fully Wired From The CLI

- MiniMax M2.7 API client
- session persistence and resume
- evaluator selection and execution
- review modes
- shadow job commands
- long evaluation report generation
- git auto-commit for successful run sessions
- webhook notifications for run sessions
- learning pipeline memory updates

### Present As Subsystems Or Partial Surfaces

- TUI is navigable but still uses placeholder/sample view data in several screens
- GitHub, GitLab, Jenkins, and MCP adapters exist as implementation modules
- `adapters/github_integration.py` provides a higher-level GitHub workflow layer,
  but it is not yet a major first-class CLI command family
- review pattern evolution, generated agents, and broader multi-review compounding
  are implemented as modules and storage layers, but not every path is equally
  surfaced or exercised by default commands

## Why The App Is Structured This Way

The architecture deliberately separates:

- orchestration from model calls
- semantic review from static analysis
- generation from evaluation
- review findings from memory persistence
- project-local learning from global caches

That separation keeps the CLI composable, makes subsystems independently testable,
and lets MUSCLE evolve from a simple code-review companion into a broader
self-improving automation loop without collapsing everything into one monolith.
