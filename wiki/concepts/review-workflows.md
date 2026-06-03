# Review Workflows

| Field | Value |
|---|---|
| Audience | Users, maintainers, and agents deciding how to review code |
| Status | Current review behavior |
| Source of truth | [`tools/muscle/cli.py`](../../tools/muscle/cli.py), [`tools/muscle/code_review/review_controller.py`](../../tools/muscle/code_review/review_controller.py), [`tools/muscle/code_review/types.py`](../../tools/muscle/code_review/types.py), [`tools/muscle/workflows/`](../../tools/muscle/workflows/) |
| Primary commands | `muscle review`, `/muscle:review`, `/muscle:pressure`, `/muscle:check` |

`muscle review` combines local static analysis, M2.7 semantic review, optional
fixing, optional handoff generation, and learning.

## Review Modes

| Mode | CLI value | Behavior |
|---|---|---|
| Standard | `review` | Report issues and learn from findings. |
| Auto-fix | `auto-fix` | Apply fix suggestions for fixable issues, subject to caps and verification. |
| Plan | `plan` | Generate a markdown handoff plan without applying fixes. |
| Hybrid | `hybrid` | Fix lower-risk issues and plan higher-risk issues. |
| Pressure | `pressure` | Run adversarial semantic review focused on design and failure modes. |

## Review Inputs

Important `muscle review` options:

```bash
muscle review --target <path> --mode review --severity low
muscle review --target <path> --mode pressure --intensity intensive
muscle review --target <path> --mode hybrid --execution worktree
muscle review --target <path> --format json --output review.json
muscle review --target <path> --no-db
muscle review --target <path> --shadow
```

Pressure focus accepts comma-separated tags such as `design`, `failure`, `race`,
`auth`, `data`, `rollback`, and `reliability`.

## Workflow Engine

Structured workflows live under [`tools/muscle/workflows/`](../../tools/muscle/workflows/).
They are constrained YAML DAGs. Supported node types include:

- `classify`
- `review_agent`
- `synthesize`
- `fix`
- `validate`
- `gate`

Built-in workflow files:

| Workflow | Purpose |
|---|---|
| `review-smart.yaml` | Default scoped review workflow. |
| `review-comprehensive.yaml` | Broader review workflow. |
| `review-fix-verify.yaml` | Fix and verification-oriented workflow. |
| `pressure-review.yaml` | Adversarial review workflow. |

## Static Analysis Layer

`StaticAnalyzer` detects language and runs local tools when available. Examples
include Ruff, Pyright, Bandit, ESLint, TSC, svelte-check, golangci-lint, Clippy,
cppcheck, and Checkstyle. Python targets also run MUSCLE's built-in AST
security analyzer and deterministic rule engine. Static findings are normalized
before semantic review.

## Semantic Review Layer

`CodeReviewer` sends source and normalized findings to M2.7. It asks the model
to confirm findings, classify severity/category, identify fixability, and
produce concrete suggested fixes. If static analysis finds nothing, proactive
semantic review can still run. If structured JSON review fails after retries,
MUSCLE falls back to a plain-chat review parser that still emits complete
`ReviewIssue` objects.

## Committee And Deduplication

`CommitteeReviewer` combines LLM-backed review with deterministic specialists
and fuzzy deduplication. This lets MUSCLE keep high-signal findings while
reducing duplicate report noise.

## JSON Output Contract

`muscle review --format json` keeps stdout machine-parseable by routing progress
text to stderr. Use this for automation or CI-style wrappers. Combining
`--format json --output <file>` writes the same JSON payload to disk even when
the review did not generate a handoff plan.

## No-DB Reviews

`muscle review --no-db` skips project-memory, learning, and optimization writes.
It is intended for one-off checks, CI smoke runs, and situations where the user
explicitly wants no learning side effects. It does not currently expose the
in-memory repository layer as a public storage backend.
