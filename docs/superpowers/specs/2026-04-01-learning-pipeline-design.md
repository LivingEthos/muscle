# MUSCLE Learning Pipeline Design

## Summary

Wire MUSCLE's existing but disconnected components (MemoryManager, SkillGenerator, PatternDetector) into a self-learning pipeline that dynamically updates CLAUDE.md, MEMORY.md, and project-specific skills after every review. The system validates its own rules, strengthens effective ones, rewrites failing ones, and archives stale ones — all scoped per-project.

## Goals

1. Reduce the main coding agent's mistakes by injecting proven, project-specific rules into CLAUDE.md
2. Reduce token usage by keeping CLAUDE.md lean (only validated rules) and archiving stale ones
3. Generate project-specific skills from recurring patterns
4. Close the feedback loop: rules that work get reinforced, rules that don't get rewritten

## Non-Goals

- Global (cross-project) learning — all state lives in `.muscle/` per project
- AGENT.md updates for the main coding agent — only used for M2.7/project agents
- Changing how ReviewController works — it stays a pure reviewer

## Architecture

### New File: `tools/muscle/code_review/learning_pipeline.py`

The central orchestrator. Single class, called from CLI layer after reviews complete.

```python
class LearningPipeline:
    def __init__(self, project_path, m27_client=None):
        self.project_path = Path(project_path)
        self.memory_manager = MemoryManager(project_path, m27_client)
        self.pattern_detector = PatternDetector()
        self.skill_generator = SkillGenerator(project_path, m27_client)
        self.review_db_path = project_path / ".muscle" / "project.db"

    def learn_from_review(self, review_result):
        """Main entry point — called after every review."""
        findings = self._categorize_findings(review_result)
        self._update_claude_md(findings)
        self._update_memory_md(findings)
        self._detect_and_generate_skills()
        self._validate_existing_rules(findings)

    def _categorize_findings(self, review_result):
        """Split findings into high/critical (immediate) and medium/low (tracked)."""

    def _update_claude_md(self, findings):
        """Write rules + anti-patterns for high/critical findings."""

    def _update_memory_md(self, findings):
        """Track all findings with occurrence counts, update pattern history."""

    def _detect_and_generate_skills(self):
        """Run PatternDetector, generate skills at 3+ threshold, register in CLAUDE.md."""

    def _validate_existing_rules(self, findings):
        """Check if existing rules prevented issues. Strengthen, rewrite, or archive."""
```

### CLAUDE.md Managed Section

MUSCLE manages a bounded section using markers. Content outside markers is never touched.

```markdown
## MUSCLE Learned Rules
<!-- MUSCLE_RULES_START -->

### Do
- Use `logger.getLogger(__name__)` for all logging (confidence: high, validated: 5x)
- Always parameterize SQL queries in `src/db/` (confidence: high, validated: 3x)

### Don't
- Never catch bare `except:` without specifying exception type (confidence: high, validated: 4x)
- Do not use mutable default arguments in function signatures (confidence: medium, validated: 1x)

### Project Skills
- `.muscle/skills/auth-validation.md` — Authentication pattern checks
- `.muscle/skills/db-query-safety.md` — Database query safety rules

<!-- MUSCLE_RULES_END -->
```

**Properties:**
- Rules include confidence level (low/medium/high) and validation count
- Deduplicated by semantic similarity via M2.7
- Compact by design — stale rules archived to MEMORY.md

### MEMORY.md Managed Section

Full history and tracking. Lower priority for token budget since it's not auto-loaded.

```markdown
# MUSCLE Memory
<!-- MUSCLE_MEMORY_START -->

## Pattern History
| Pattern | Severity | Occurrences | First Seen | Last Seen | Status |
|---------|----------|-------------|------------|-----------|--------|
| Bare except clauses | high | 7 | 2026-03-15 | 2026-04-01 | promoted |
| Missing type hints in API | medium | 2 | 2026-03-28 | 2026-03-30 | tracking |

## Archived Rules
- [2026-04-01] "Check for Python 3.9 compat" — not seen in 12 reviews, moved from CLAUDE.md

## Fix History
| Fix | Applied To | Validated | Result |
|-----|-----------|-----------|--------|
| Replace print() with logger | src/api/*.py | yes | pattern stopped recurring |

## Review Sessions
- 2026-04-01: 3 critical, 5 medium — promoted 1 rule to CLAUDE.md
- 2026-03-30: 0 critical, 2 medium — validated 3 existing rules

<!-- MUSCLE_MEMORY_END -->
```

### Validation & Self-Modification Loop

After each review, the pipeline validates every existing rule in CLAUDE.md:

```
For each rule:
  Pattern found in current review?
    YES → Rule not working. Increment failure_count.
      failure_count >= 3: M2.7 rewrites rule with stronger, more specific wording
      failure_count >= 6: Escalate severity + log in MEMORY.md as persistent problem
    NO → Rule is working. Increment validated_count.
      Upgrade confidence: low(0) → low(1) → medium(2-3) → high(4+)
      validated_count >= 10 AND not seen in 10+ reviews: Archive to MEMORY.md
```

**Rule rewriting example:**
- Original: "Use logger instead of print()"
- After 3 failures: "In `src/api/` and `src/workers/`, NEVER use `print()` — use `logging.getLogger(__name__).info()`. The print statements are being added in error handlers and debug blocks."

### Skill Generation Pipeline

```
PatternDetector.detect_patterns(review_db)
  → filter by threshold (3+ occurrences, medium+ confidence)
  → SkillGenerator.generate_skill(pattern_info, reviewed_issues)
    → M2.7 generates skill content with project-specific examples
    → writes to .muscle/skills/{pattern-slug}.md
    → MemoryManager.add_skill_reference() registers in CLAUDE.md
```

**Skill lifecycle:**
- Created at 3+ occurrences
- Validated when pattern stops appearing
- Updated when new context discovered
- Archived to MEMORY.md only when completely stale

### Confidence Progression

```
new (0 validations) → low (1) → medium (2-3) → high (4+)
```

### Promotion Rules (MEMORY.md → CLAUDE.md)

- High/Critical severity findings: promoted immediately on first occurrence
- Medium severity: promoted at 3+ occurrences
- Low severity: promoted at 3+ occurrences only if pattern is across multiple files

## Integration Points

### 1. CLI `review` command (primary)

After `controller.run()` returns in `cli.py`:
```python
pipeline = LearningPipeline(project_path, m27_client)
pipeline.learn_from_review(review_result)
```

### 2. Nightly runner

After `run_nightly()` completes:
```python
pipeline = LearningPipeline(project_path)
pipeline.learn_from_review(nightly_result)
```

### 3. Stop hook (automatic)

The hook runs `muscle review`, which now includes learning. No hook changes needed.

## Files to Modify

| File | Change |
|------|--------|
| `code_review/learning_pipeline.py` | **NEW** — full learning cycle orchestrator |
| `code_review/memory_manager.py` | Fix marker bug, add rule validation/archival/rewriting methods |
| `code_review/review_controller.py` | Add `export_findings()` method for structured pipeline input |
| `cli.py` | Call `learning_pipeline.learn_from_review()` after review |
| `code_review/nightly_runner.py` | Call pipeline after nightly review |
| `tui/project_manager.py` | Fix AGENT.md marker → use `MUSCLE_LEARNED_START` or remove AGENT.md markers |
| `code_review/skill_generator.py` | Add skill update/archive lifecycle methods |

## Bug Fixes Required

1. **Marker mismatch**: `project_manager.py` creates AGENT.md with `<!-- MUSCLE_AGENTS_START -->` but MemoryManager uses `<!-- MUSCLE_LEARNED_START -->`. Fix: use consistent markers or skip AGENT.md for non-M2.7 use.

## Dependencies

None new. Uses existing:
- M2.7 client (for rule rewriting and skill generation)
- MemoryManager (file writes with markers)
- PatternDetector (3+ threshold detection)
- SkillGenerator (skill .md creation)
- ReviewController (review findings)

## Testing Strategy

- Unit tests for LearningPipeline with mocked MemoryManager/PatternDetector
- Integration test: review → learn → verify CLAUDE.md updated
- Regression test: verify rules outside markers are never touched
- Validation loop test: simulate 3+ failures → verify rule rewrite triggered
- Archival test: simulate 10+ clean reviews → verify stale rule moved to MEMORY.md
