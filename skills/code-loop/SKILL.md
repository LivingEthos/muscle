# SCLE Code Loop Skill

## Description

SCLE (Self-Correcting Loop Engine) is an autonomous code generation and improvement skill that uses MiniMax M2.7's self-improvement capabilities to iteratively generate, evaluate, and refine code until it passes all quality checks.

## Usage

### Interactive Mode

```
/code-loop "Build a REST API with JWT authentication in Python"
```

This starts an interactive session where you see each iteration and can:
- `[E]volve` - Let the system evolve its strategy
- `[S]kip` - Skip to the next step
- `[A]bort` - Stop the session
- `[R]etry` - Retry without evolving

### Silent Mode

```
/code-loop --silent "Build a FastAPI service with PostgreSQL"
```

Runs silently and returns the final result.

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--silent` | Run without interactive output | false |
| `--language` | Specify language (auto-detected if not) | auto |
| `--output` | Output directory | current dir |
| `--max-iterations` | Maximum iterations | 20 |
| `--timeout` | Timeout (30m, 2h, etc.) | 60m |
| `--budget` | Token budget (auto, unlimited, or number) | unlimited |
| `--eval-mode` | Evaluation mode (all, sequential, parallel) | all |
| `--allow-warnings` | Pass even with linter warnings | false |

## Examples

```bash
# Basic usage
/code-loop "Build a Python FastAPI auth service"

/code-loop --language python --output ./my-api "Build a REST API with JWT auth"

# With budget control
/code-loop --budget auto --max-iterations 50 "Complex microservices project"

# Silent mode for automation
/code-loop --silent "Build a CLI tool with argument parsing"
```

## How It Works

1. **Generate**: M2.7 generates code based on the task description
2. **Evaluate**: Code is tested with compiler, linter, and unit tests
3. **Evolve**: If evaluation fails, M2.7 analyzes errors and generates improved strategy
4. **Repeat**: Loop continues until success or max iterations

## Integration

SCLE integrates with:
- **GitHub Actions**: `minimax/scle-action@v1`
- **GitLab CI**: Via `.gitlab-ci.yml` template
- **Jenkins**: Via pipeline step
- **MCP Tools**: MiniMax text-to-speech, image generation for test assets

## Budget Management

SCLE supports Token Plan integration:
- `--budget auto` reads from your Token Plan allowance
- `--budget 100000` sets a fixed token limit
- `--budget unlimited` removes limits

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success - code passed all evaluations |
| 1 | Failed - max iterations reached |
| 2 | Aborted - user cancelled |
| 3 | Budget exceeded |

## Tips

1. **Be specific**: "Build a REST API" vs "Build a FastAPI REST API with JWT, PostgreSQL, and Docker"
2. **Include context**: "Build a web scraper that handles rate limiting and retries"
3. **Set realistic budgets**: Complex tasks may need more iterations
4. **Use `--allow-warnings` for prototypes**: Focus on functionality first
