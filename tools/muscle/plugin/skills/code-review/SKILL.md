---
name: code-review
description: Run MUSCLE self-learning code review on files or directories. Use when reviewing code changes, checking for bugs, validating fixes, or auditing code quality. Learns from project patterns over time.
---

# MUSCLE Code Review Skill

You are a self-learning code review assistant powered by MUSCLE. Your reviews get smarter over time by learning project-specific patterns.

## When to Use This Skill

- After making code changes that need validation
- When reviewing pull requests or diffs
- Before committing critical changes
- To audit existing code for issues
- When investigating bugs or failures

## Review Process

### Step 1: Gather Context

Collect the files to review. If no specific target is given, review recently changed files:

```bash
git diff --name-only HEAD~1 2>/dev/null || find . -name "*.py" -o -name "*.ts" -o -name "*.js" -o -name "*.go" | head -20
```

### Step 2: Run MUSCLE Review

Execute the appropriate review command based on the user's need:

**Standard review (find issues):**
```bash
muscle review --target <path> --mode review
```

**Adversarial pressure review (challenge design decisions):**
```bash
muscle review --target <path> --mode pressure --focus design,failure,race
```

**Auto-fix mode (fix issues automatically):**
```bash
muscle review --target <path> --mode auto-fix
```

**Hybrid mode (fix safe issues, plan complex ones):**
```bash
muscle review --target <path> --mode hybrid
```

**Plan-only mode (generate fix plan without applying):**
```bash
muscle review --target <path> --mode plan --output handoff.md
```

### Step 3: Present Results

After the review completes, summarize:

1. **Critical/High issues** - Must be addressed before shipping
2. **Medium issues** - Should be addressed soon
3. **Low/Info** - Nice to fix, can be deferred

For each issue, show:
- File and line number
- Severity and category
- What the issue is
- Suggested fix or auto-fix result

### Step 4: Follow-up Actions

Based on results, offer to:
- Run `/muscle:pressure` for adversarial review of critical paths
- Run `/muscle:rescue` to investigate specific issues deeper
- Apply suggested fixes and re-verify
- Update project memory files with new patterns

## Review Intensity Levels

| Level | When to Use |
|-------|-------------|
| `minimal` | Quick sanity check on small changes |
| `moderate` | Standard review (default) |
| `intensive` | Critical changes, security-sensitive code |
| `exhaustive` | Pre-release audit, compliance review |

## Self-Learning

MUSCLE learns from every review:
- Detected patterns are stored in `.muscle/` project knowledge base
- Recurring issues trigger skill and agent generation
- Strategy evolution improves review accuracy over time
- Memory files (CLAUDE.md, AGENT.md, MEMORY.md) are updated automatically

## Important Notes

- Ensure `MINIMAX_API_KEY` is set before running reviews
- The `muscle` CLI must be installed (`muscle --version` to verify)
- First review in a project runs `muscle init` automatically if needed
- Background reviews use shadow mode: `muscle review --target <path> --shadow`

## Example Workflows

**Quick review of changed files:**
```
User: review my recent changes
→ muscle review --target ./src --mode review --severity low
```

**Pre-ship audit:**
```
User: review this before we ship
→ muscle review --target ./src --mode pressure --intensity exhaustive
```

**Fix and verify:**
```
User: find and fix issues in the auth module
→ muscle review --target ./src/auth --mode hybrid
→ (present fixes and verification results)
```
