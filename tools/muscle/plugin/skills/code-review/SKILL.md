---
name: code-review
description: Run MUSCLE code review on files or directories. Use when reviewing code changes, checking for bugs, validating fixes, auditing code quality. Uses M2.7 semantic analysis plus local static analyzers.
---

# MUSCLE Code Review Skill

You are a code review assistant powered by MUSCLE. MUSCLE maintains per-project memory under `.muscle/` so Claude Code can learn your codebase's patterns over time.

## Plan-Then-Hand-Off (Cost-Saving Delegation)

You (Claude Code on Opus 4.7, or Codex) are the planner and synthesizer. MUSCLE's MiniMax M2.7 agents are the execution muscle at ~5–10× lower token cost. Decide what the review should cover, then hand execution to MUSCLE via the commands below. Do not do the bulk review yourself.

In auto mode, proceed through delegations without confirmation prompts between steps. You still plan; MUSCLE still executes.

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

Execute the appropriate review command based on the user's need. Pass `--focus` and `--target` to scope MUSCLE's work tightly — MUSCLE executes the review you planned, not one it plans itself.

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

Delegate follow-up execution to MUSCLE (do not redo the analysis yourself):
- Run `/muscle:pressure` for adversarial review of critical paths.
- Run `/muscle:rescue` to investigate specific issues deeper.
- Apply suggested fixes via MUSCLE, then invoke the MUSCLE verification agent before committing.
- Update project memory files with new patterns.

## Review Intensity Levels

| Level | When to Use |
|-------|-------------|
| `minimal` | Quick sanity check on small changes |
| `moderate` | Standard review (default) |
| `intensive` | Critical changes, security-sensitive code |
| `exhaustive` | Pre-release audit, compliance review |

## Per-Project Memory

After each review, MUSCLE updates `.muscle/` memory files so Claude Code can learn from past findings:
- Detected patterns are stored in the project knowledge base under `.muscle/`
- Recurring issues may trigger skill and agent generation (still maturing)
- Strategy evolution improves review accuracy when effectiveness is validated (still maturing)
- Memory files (CLAUDE.md, AGENT.md, MEMORY.md) are updated after reviews

## Important Notes

- Ensure `MINIMAX_API_KEY` is set before running reviews
- The `muscle` CLI must be installed (`muscle --version` to verify)
- Run `muscle init` in your project directory before the first review to set up `.muscle/` state
- Shadow mode background reviews are available: `muscle review --target <path> --shadow`

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
