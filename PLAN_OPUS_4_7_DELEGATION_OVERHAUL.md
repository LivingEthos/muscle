# MUSCLE Delegation-First Plugin: Token-Saving CLAUDE.md + AGENTS.md Overhaul

## Context

MUSCLE's plugin is consumed by two host CLIs:
- **Claude Code** (Claude Opus 4.7, ~$5 / $25 per MTok) — ships with **auto mode**, new effort levels (`max`/`xhigh`/`high`/`medium`/`low`), adaptive thinking, task budgets (beta), more literal instruction following, fewer subagents and tool calls by default.
- **Codex** (OpenAI, expensive hosts with similar agentic behavior) — MUSCLE already imports Codex session data in `tools/muscle/optimization/importers.py:39-147` and uses a "Codex-style verify-before-learn pattern" in `tools/muscle/code_review/verification_loop.py:4`.

Both hosts are expensive. MUSCLE's internal workhorse **MiniMax M2.7** does equivalent review-scoped reasoning at **~5–10× lower cost**. The plugin itself **never needs an Anthropic API key** — MUSCLE authenticates to MiniMax via `MINIMAX_API_KEY` (or `ANTHROPIC_API_KEY` as a legacy alias, since MiniMax exposes an Anthropic-compatible API at `api.minimax.io/anthropic`; it is *not* a real Anthropic key).

Today the plugin leaves the delegation economics on the table:
- The skill at `tools/muscle/plugin/skills/code-review/SKILL.md` treats MUSCLE as "one option among many" — the opposite of delegation-first.
- The published MUSCLE section in a project's root `CLAUDE.md` (`tools/muscle/claude_publisher.py`, markers `MUSCLE_PUBLISHED_START/END`, size-capped at 50 lines per section, M2.7-consolidated) holds dynamic rules but **no Methodology** and **no Delegation Protocol**.
- **Nothing publishes to `AGENTS.md`** — Codex users get no MUSCLE-owned context at their host's standard memory file. Grep confirms: no `AGENTS.md` references anywhere in `tools/muscle/`.
- `memory_manager.py:145-151` seeds `.muscle/CLAUDE.md` (and sibling `.muscle/AGENT.md`) as empty marker blocks — no behavioral defaults.
- When a user already maintains a `CLAUDE.md` or `AGENTS.md`, MUSCLE has no flow that **optimizes it non-destructively** into the ideal format.
- Repo-level docs (`CLAUDE.md`, `MUSCLE_PLAN.md`, `docs/architecture.md`) predate this delegation-first / Opus-4.7 / dual-host story.

**Simplifying assumption (per user):** assume the Claude Code host is **Opus 4.7 on auto mode at any effort level**. No host-model detection is built — Claude Code / Codex expose no reliable runtime signal, and we don't need one for the delegation framing to work. MUSCLE already detects Codex **presence** (via `~/.codex/sessions` in `importers.py:57`), which is all we need to know whether to publish `AGENTS.md`.

**The four-principle design guide** (Think Before Coding · Simplicity First · Surgical Changes · Goal-Driven Execution) is embedded into the Methodology section MUSCLE writes, and is also how every change in this plan is designed — minimum code, non-destructive, verifiable.

**Opus 4.7 behaviors that shape the templates:**
- **Literal instruction following** → positive, directive phrasing; name tools and commands explicitly.
- **Fewer subagents / tool calls by default** → spell out exactly when rescue/verification agents are invoked.
- **Built-in progress updates** → no "summarize every N tool calls" scaffolding.
- **Auto mode** → the Delegation Protocol must work hands-off; never require a user confirmation between delegations.
- **Effort levels** → mention `xhigh` for coding once, plainly.
- **New tokenizer** → does not affect MUSCLE directly (plugin calls MiniMax, not Anthropic).

**Intended outcome:** The MUSCLE plugin transparently saves a significant share of host tokens per project by (a) writing a pinned **Methodology + Delegation Protocol** (plan-then-hand-off) into both `CLAUDE.md` and `AGENTS.md`, so Opus 4.7 / Codex keep the planning role and hand mechanical bulk execution to MUSCLE's M2.7 agents, (b) refreshing the plugin skill with a plan-then-delegate preamble while preserving its existing flexibility, (c) safely optimizing any pre-existing `CLAUDE.md`/`AGENTS.md` without data loss, (d) keeping dynamic rule learning intact, and (e) the repo's own docs accurately describe the new posture.

---

## Phase 0 — Repo docs refresh (do first)

Before touching plugin code, make the repo self-description accurate.

### 0.1 Root `CLAUDE.md`
- Under **Environment Variables**: clarify that `MINIMAX_API_KEY` and `ANTHROPIC_API_KEY` are interchangeable names for the **MiniMax** credential (MiniMax's Anthropic-compatible endpoint). The plugin does **not** use a real Anthropic key.
- Under **Key Patterns**: add *"MUSCLE's plugin output is consumed by Claude Code (Opus 4.7) and Codex. Keep prompt templates literal, positive, and surgical — Opus 4.7 interprets prompts literally and spawns fewer subagents/tools by default."*
- Add a **Tooling Notes** subsection: *"`m27_client.py` passes `temperature` and other sampling params. Those are **400 errors on Anthropic Opus 4.7**. Do not add an Anthropic fallback without stripping those params first."*
- Add a **Delegation Economics** bullet: *"Opus 4.7 / Codex hosts are ~5–10× more expensive per token than MiniMax M2.7. MUSCLE's plugin writes a plan-then-hand-off Delegation Protocol into every project's CLAUDE.md and AGENTS.md: the host model (Opus 4.7 / Codex) keeps the planning role and hands mechanical bulk execution (multi-file reviews, test sweeps, fix-candidate generation, pattern scans) to MUSCLE's M2.7 agents (`/muscle:review`, rescue agent, verification agent, `/muscle:pressure`)."*
- Under **Current Maturity Notes**: *"The plugin now writes a pinned Methodology + Delegation Protocol section into project CLAUDE.md and AGENTS.md via `claude_publisher.py`; `muscle optimize-host-docs` can reorganize a pre-existing CLAUDE.md/AGENTS.md non-destructively."*

### 0.2 `MUSCLE_PLAN.md`

Three edits:

1. Find the `Last updated:` line at the top of the file and replace the date with `2026-04-17`.

2. Immediately after the `## Product Goal` section's closing paragraph, insert this new section verbatim:

```markdown
## Dual-Host Delegation Posture

MUSCLE's plugin is consumed by two expensive host CLIs — Claude Code (Opus 4.7, ~$5/$25 per MTok) and Codex. MUSCLE's internal workhorse, MiniMax M2.7, does equivalent review-scoped reasoning at ~5–10× lower token cost.

The plugin now writes a pinned **Methodology + Delegation Protocol + Effort & Tool Guidance** block into every reviewed project's root `CLAUDE.md` and `AGENTS.md`, via `claude_publisher.py`. The host model keeps planning, synthesis, and user interaction; MUSCLE's M2.7 agents handle bulk mechanical execution (multi-file review, test/lint sweeps, fix-candidate generation, pattern scans).

This posture complements — does not replace — the dynamic rule-learning pipeline. `LearningPipeline` continues to promote rules from `project_memory.db` into the dynamic sections alongside the pinned block. Pinned sections are exempt from M2.7 consolidation and from the 50-line section cap.

See `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md` for the implementation plan.
```

3. In the `## Active Plan Files` list, add this line alongside the existing entries: `- PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`.

### 0.3 `docs/architecture.md`

Append this new section at the end of the file, after the last existing section:

```markdown
## Host Memory Contract (Plugin → Host CLI)

MUSCLE's plugin publishes structured content to the **host CLI**'s memory files (Claude Code → `CLAUDE.md`, Codex/cross-tool → `AGENTS.md`) at the root of every reviewed project. The publisher (`tools/muscle/claude_publisher.py`) writes identical content to both files inside the `MUSCLE_PUBLISHED_START` / `MUSCLE_PUBLISHED_END` marker region.

### Section types

**Pinned** — always present, byte-identical across consolidation cycles, exempt from the 50-line section cap:
- `### Methodology` — four-principle design guide (think / simplicity / surgical / goal-driven).
- `### Delegation Protocol` — plan-then-hand-off posture directing the host model to delegate bulk execution to MUSCLE's M2.7 agents.
- `### Effort & Tool Guidance` — Opus 4.7 effort hints (`xhigh` for coding) and auto-mode guidance.

All pinned content is sourced from `tools/muscle/code_review/host_memory_templates.py` (constant strings; no dynamic rendering).

**Dynamic** — populated from `project_memory.db` via `LearningPipeline` → `MemoryDecisionEngine` → `ClaudePublisher.publish()`. Subject to the 50-line section cap and M2.7 consolidation when caps are exceeded:
- `### Critical Rules`, `### Frequent Mistakes`, `### Active Agent Calls`, `### Active Skill Calls`, `### Tooling Notes`.

### Optimizer flow

`tools/muscle/code_review/host_memory_optimizer.py` provides a non-destructive rewriter for pre-existing `CLAUDE.md` / `AGENTS.md` files that predate the MUSCLE plugin. Exposed as `muscle optimize-host-docs`. It wraps user content in `MUSCLE_PUBLISHED` markers (if absent) and injects the pinned block. Content outside the markers is never reordered, rewritten, or deleted. Pure and deterministic — no M2.7 calls.

### File map

- `tools/muscle/code_review/host_memory_templates.py` — pinned content constants.
- `tools/muscle/code_review/host_memory_optimizer.py` — non-destructive optimizer.
- `tools/muscle/claude_publisher.py` — marker-bounded dynamic publisher (now multi-target).
```

### 0.4 New `PROJECT_INDEX.md` at repo root
Single file, ≤80 lines. Two-column table mapping feature → critical files:
- CLI entry (`tools/muscle/cli.py`)
- Review flow (`review_controller.py`, `code_reviewer.py`, `fix_generator.py`, `handoff_generator.py`, `committee_reviewer.py`)
- Code-gen loop (`loop_controller.py`, `code_generator.py`, `evaluator_registry.py`, `evolver.py`)
- Memory + publishing (`memory_manager.py`, `claude_publisher.py`, `learning_pipeline.py`, new `host_memory_templates.py`, new `host_memory_optimizer.py`)
- Codex integration (`optimization/importers.py`, `code_review/verification_loop.py`)
- Plugin (skill, commands, agents)
- Data stores (pointer to the list in CLAUDE.md — don't re-list)

---

## Phase 1 — Plugin & template changes

**Implementation order (do not reorder — later changes import from earlier ones):**

1. **Change 1** — create `host_memory_templates.py` first. Nothing imports from it yet, so it lands standalone.
2. **Change 3** — `memory_manager.py` edit, which imports `INTERNAL_SEED` from Change 1.
3. **Change 2** — `claude_publisher.py` refactor, which imports `PINNED_TEMPLATE`, section constants, and `render_pinned_block` from Change 1. Run `uv run pytest tests/unit/test_claude_publisher.py -v` after this step; most existing tests should still pass (single-target path still works because `target_files[0]` defaults to `CLAUDE.md`).
4. **Change 4** — create `host_memory_optimizer.py` + add the CLI subcommand + add the plugin command file. Run `muscle optimize-host-docs --dry-run` against the repo root to smoke-test.
5. **Change 6b** — register `/muscle:optimize-host-docs` in `plugin.json`.
6. **Change 5, 6** — plugin skill + command/agent header edits (pure markdown; no import graph).
7. **Change 7** — extract `get_codex_home()` helper.
8. **Phase 0.2, 0.3** — finalize `MUSCLE_PLAN.md` and `docs/architecture.md` text.
9. **Run full quality gates** (see Verification section).

Do not commit piecemeal — land the whole sequence as one reviewable change so the import graph stays consistent.


### Change 1 — `host_memory_templates.py` (single template, both hosts) [HIGH]

**New file:** `tools/muscle/code_review/host_memory_templates.py`.

**Exact module skeleton (write this verbatim):**

```python
"""Canonical host-memory templates.

Used by ClaudePublisher (for root CLAUDE.md and AGENTS.md) and by
MemoryManager (for .muscle/CLAUDE.md and .muscle/AGENT.md internal seeds).

These strings are pinned — they must survive M2.7 consolidation cycles
unmodified (see claude_publisher._m27_summarize_entries).
"""

from __future__ import annotations

# Section headings that count as "pinned" inside MUSCLE_PUBLISHED markers.
# Kept in sync with the headings below and with PINNED_SECTIONS in
# claude_publisher.py.
SECTION_METHODOLOGY = "### Methodology"
SECTION_DELEGATION = "### Delegation Protocol"
SECTION_EFFORT = "### Effort & Tool Guidance"

PINNED_SECTION_ORDER: tuple[str, ...] = (
    SECTION_METHODOLOGY,
    SECTION_DELEGATION,
    SECTION_EFFORT,
)

PINNED_TEMPLATE: str = """### Methodology
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

_These commands require the MUSCLE plugin to be active in this project (install via `muscle install`). Without it, reason directly._

### Effort & Tool Guidance
- On Claude Code (Opus 4.7): run MUSCLE fix-application flows at `xhigh` effort; summarization-only at `high`. In auto mode, proceed through delegations without confirmation prompts.
- Opus 4.7 interprets instructions literally. If a MUSCLE finding is ambiguous, ask the user before generalizing.
- Opus 4.7 provides its own progress updates — do not add interim summary instructions.
"""

INTERNAL_SEED: str = """### Methodology
- Think before coding: state assumptions; if multiple interpretations fit, surface them.
- Simplicity first: ship the minimum code that solves the problem.
- Surgical changes: touch only what the task requires; match existing style.
- Goal-driven execution: define the verification check first, then loop until it passes.
"""


def render_pinned_block() -> str:
    """Return the pinned block exactly as it should appear inside markers.

    Deterministic: always returns the same bytes. Callers concatenate this
    with dynamic sections to build the full MUSCLE_PUBLISHED region.
    """
    return PINNED_TEMPLATE
```

**Reference template body (for convenience, also embedded in PINNED_TEMPLATE above):**

```markdown
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

_These commands require the MUSCLE plugin to be active in this project (install via `muscle install`). Without it, reason directly._

### Effort & Tool Guidance
- On Claude Code (Opus 4.7): run MUSCLE fix-application flows at `xhigh` effort; summarization-only at `high`. In auto mode, proceed through delegations without confirmation prompts.
- Opus 4.7 interprets instructions literally. If a MUSCLE finding is ambiguous, ask the user before generalizing.
- Opus 4.7 provides its own progress updates — do not add interim summary instructions.
```

### Change 2 — Publisher writes pinned sections to CLAUDE.md **and** AGENTS.md [HIGH]

**File:** `tools/muscle/claude_publisher.py`.

**Audit finding (2026-04-17):** `publish()` is hardcoded to a single output via `self.claude_md_path = self.project_path / "CLAUDE.md"` (line 75). The existing section constants at lines 46-50 are: `SECTION_CRITICAL_RULES`, `SECTION_MISTAKE_CORRECTIONS`, `SECTION_AGENT_CALLS`, `SECTION_SKILL_CALLS`, `SECTION_TOOLING_NOTES`. `MAX_SECTION_LINES = 50` is at line 53. The M2.7 consolidation prompt is an f-string at lines 167-179 inside `_m27_summarize_entries()`. Size-cap enforcement lives in `_check_and_consolidate()` at lines 238-328 via five identical `if total_X > MAX_SECTION_LINES:` blocks (one per dynamic section). Only caller of `publish()` is `LearningPipeline._publish_active_specializations` at `learning_pipeline.py:542`.

#### Change 2.1 — Import pinned constants + add `PINNED_SECTIONS` frozenset

Add **after** line 50 (the existing `SECTION_TOOLING_NOTES` line):

```python
# Pinned section headers + template body (imported from host_memory_templates
# for single source of truth). Pinned sections are exempt from MAX_SECTION_LINES
# and from M2.7 consolidation.
from .code_review.host_memory_templates import (
    PINNED_TEMPLATE,
    SECTION_DELEGATION,
    SECTION_EFFORT,
    SECTION_METHODOLOGY,
    render_pinned_block,
)

PINNED_SECTIONS: frozenset[str] = frozenset(
    {SECTION_METHODOLOGY, SECTION_DELEGATION, SECTION_EFFORT}
)
```

Note: `claude_publisher.py` sits at `tools/muscle/claude_publisher.py`; the new module is at `tools/muscle/code_review/host_memory_templates.py`. The correct relative import is `from .code_review.host_memory_templates import ...` (single leading dot, since both are children of `tools.muscle`).

#### Change 2.2 — Constructor gains `target_files` parameter

Replace the existing `__init__` method (lines 59-86). **Before:**

```python
    def __init__(
        self,
        project_path: str,
        backup_manager: BackupManager | None = None,
        m27_client: Any | None = None,
    ):
        """
        Initialize ClaudePublisher.

        Args:
            project_path: Path to the project root.
            backup_manager: Optional shared BackupManager instance. If not provided,
                           one will be created using ProjectMemory.
            m27_client: Optional M2.7 client for consolidation.
        """
        self.project_path = Path(project_path)
        self.claude_md_path = self.project_path / "CLAUDE.md"
        self.m27 = m27_client

        if backup_manager is not None:
            # Use the provided shared BackupManager
            self._backup_manager = backup_manager
        else:
            # Create a shared BackupManager using ProjectMemory
            from .project_memory import ProjectMemory

            pm = ProjectMemory(str(self.project_path))
            self._backup_manager = BackupManager(pm, str(self.project_path))
```

**After:**

```python
    def __init__(
        self,
        project_path: str,
        backup_manager: BackupManager | None = None,
        m27_client: Any | None = None,
        target_files: list[str] | None = None,
    ):
        """
        Initialize ClaudePublisher.

        Args:
            project_path: Path to the project root.
            backup_manager: Optional shared BackupManager instance. If not provided,
                           one will be created using ProjectMemory.
            m27_client: Optional M2.7 client for consolidation.
            target_files: Filenames (relative to project_path) to publish to.
                          Defaults to ["CLAUDE.md", "AGENTS.md"]. Identical content
                          is written to every target, with a per-file backup before
                          each write.
        """
        self.project_path = Path(project_path)
        self.target_files: list[str] = list(target_files) if target_files else ["CLAUDE.md", "AGENTS.md"]
        # Retained for backwards compatibility with code that reads claude_md_path directly.
        self.claude_md_path = self.project_path / self.target_files[0]
        self.m27 = m27_client

        if backup_manager is not None:
            self._backup_manager = backup_manager
        else:
            from .project_memory import ProjectMemory

            pm = ProjectMemory(str(self.project_path))
            self._backup_manager = BackupManager(pm, str(self.project_path))
```

#### Change 2.3 — `publish()` iterates over targets

Replace the write section of `publish()` (lines 350-404). **Before:**

```python
        if not self.claude_md_path.exists():
            logger.warning(f"CLAUDE.md not found at {self.claude_md_path}")
            return False

        # Always create backup before writing (using shared BackupManager)
        try:
            self._backup_manager.create_backup("claude_md")
        except FileNotFoundError:
            # Root CLAUDE.md doesn't exist yet - cannot back up
            logger.warning(f"CLAUDE.md not found at {self.claude_md_path}, cannot backup")
            return False
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return False

        # Check sizes and consolidate if needed (M2.7 summarization for over-cap sections)
        (
            critical_rules,
            mistake_corrections,
            agent_calls,
            skill_calls,
            tooling_notes,
        ) = self._check_and_consolidate(
            critical_rules=critical_rules or [],
            mistake_corrections=mistake_corrections or [],
            agent_calls=agent_calls or [],
            skill_calls=skill_calls or [],
            tooling_notes=tooling_notes or [],
        )

        try:
            content = self.claude_md_path.read_text()
            updated_content = self._update_published_section(
                content,
                critical_rules=critical_rules or [],
                mistake_corrections=mistake_corrections or [],
                agent_calls=agent_calls or [],
                skill_calls=skill_calls or [],
                tooling_notes=tooling_notes or [],
            )
            self.claude_md_path.write_text(updated_content)
            logger.info("Successfully published to CLAUDE.md")

            self._backup_manager._pm.insert_action_log(
                project_path=str(self.project_path),
                action_type="publish",
                entity_type="claude_md",
                entity_id=None,
                details_json='{"sections": ["critical_rules", "mistake_corrections", "agent_calls", "skill_calls", "tooling_notes"]}',
            )

            return True
        except Exception as e:
            logger.error(f"Failed to publish to CLAUDE.md: {e}")
            return False
```

**After:**

```python
        # Check sizes and consolidate once (results reused for every target).
        (
            critical_rules,
            mistake_corrections,
            agent_calls,
            skill_calls,
            tooling_notes,
        ) = self._check_and_consolidate(
            critical_rules=critical_rules or [],
            mistake_corrections=mistake_corrections or [],
            agent_calls=agent_calls or [],
            skill_calls=skill_calls or [],
            tooling_notes=tooling_notes or [],
        )

        any_written = False
        for filename in self.target_files:
            target_path = self.project_path / filename
            if not target_path.exists():
                # Skip targets that the user has not created. Do NOT auto-create
                # here — auto-creation is the optimizer's job (Change 4).
                logger.info(f"{filename} not found at {target_path}; skipping publish to this target")
                continue

            # Per-file backup before write.
            try:
                self._backup_manager.create_backup(f"publish:{filename}")
            except FileNotFoundError:
                logger.warning(f"{filename} not found at {target_path}, cannot backup")
                continue
            except Exception as e:
                logger.error(f"Failed to create backup for {filename}: {e}")
                continue

            try:
                content = target_path.read_text()
                updated_content = self._update_published_section(
                    content,
                    critical_rules=critical_rules or [],
                    mistake_corrections=mistake_corrections or [],
                    agent_calls=agent_calls or [],
                    skill_calls=skill_calls or [],
                    tooling_notes=tooling_notes or [],
                )
                target_path.write_text(updated_content)
                logger.info(f"Successfully published to {filename}")
                any_written = True

                self._backup_manager._pm.insert_action_log(
                    project_path=str(self.project_path),
                    action_type="publish",
                    entity_type=filename,
                    entity_id=None,
                    details_json='{"sections": ["critical_rules", "mistake_corrections", "agent_calls", "skill_calls", "tooling_notes"]}',
                )
            except Exception as e:
                logger.error(f"Failed to publish to {filename}: {e}")
                continue

        return any_written
```

#### Change 2.3b — Prepend pinned block in `_build_published_content`

Both `_insert_markers` and `_replace_published_section` delegate to `_build_published_content` (lines 437-513) to construct the body between markers. That's the single place to inject the pinned block. No change to the dispatcher or either of the marker methods.

**Find exactly (lines 445-447):**

```python
    def _build_published_content(
        self,
        critical_rules: list[dict],
        mistake_corrections: list[dict],
        agent_calls: list[dict],
        skill_calls: list[dict],
        tooling_notes: list[str],
    ) -> str:
        """Build the compact published content section."""
        lines: list[str] = []

        # Critical Rules (high score rules first)
```

**Replace with:**

```python
    def _build_published_content(
        self,
        critical_rules: list[dict],
        mistake_corrections: list[dict],
        agent_calls: list[dict],
        skill_calls: list[dict],
        tooling_notes: list[str],
    ) -> str:
        """Build the compact published content section.

        Pinned sections (Methodology, Delegation Protocol, Effort & Tool
        Guidance) are always rendered first, byte-identical across runs,
        regardless of dynamic-section content. Dynamic sections follow.
        """
        lines: list[str] = []

        # Pinned block — always first, always verbatim. Sourced from
        # host_memory_templates.PINNED_TEMPLATE. Do not edit here.
        lines.append(PINNED_TEMPLATE.rstrip())
        lines.append("")

        # Critical Rules (high score rules first)
```

**Why `.rstrip()` + empty line:** `PINNED_TEMPLATE` ends with `\n`, and `lines` is joined with `"\n"` at line 513. Stripping the trailing newline prevents a double-newline artifact. The empty-string append produces one blank line separating the pinned block from the first dynamic section, matching the visual rhythm of the existing per-section `lines.append("")` calls (e.g., line 461).

**Idempotency note:** `_replace_published_section` (line 532) blows away the entire managed region and rebuilds it every call via `_build_published_content`. Because the pinned block is unconditionally prepended on every rebuild, re-running `publish()` produces byte-identical pinned output. No dedup pass is required here.

**Test impact:** In the new `test_pinned_sections_never_consolidated` test, also assert that calling `publish()` twice with the same inputs produces a file where the pinned section appears exactly once (not duplicated). Minimal additional assertion, covers the idempotency invariant.

#### Change 2.4 — Gate consolidation on pinned section names

In `_check_and_consolidate()` (lines 238-328), **each of the 5 `if total_X > MAX_SECTION_LINES:` blocks is for a dynamic section** — none of them touch pinned sections today. **No change required here** beyond a defensive comment. Add at the top of `_check_and_consolidate()`, immediately after the docstring (around line 250):

```python
        # Pinned sections (Methodology, Delegation Protocol, Effort & Tool Guidance)
        # are never consolidated or size-capped. They are written verbatim from
        # host_memory_templates.PINNED_TEMPLATE and must survive unchanged.
```

#### Change 2.5 — M2.7 consolidation prompt guards against pinned names

In `_m27_summarize_entries()` (lines 155-207), **before** the existing `prompt = f"""..."""` assignment at line 167, add a short-circuit:

```python
        # Defensive: pinned sections should never reach this method, but if they
        # do (e.g., a future regression), return entries unchanged rather than
        # paraphrasing the delegation template.
        if section_name in PINNED_SECTIONS:
            logger.warning(
                f"_m27_summarize_entries called for pinned section {section_name!r}; "
                "returning entries unchanged."
            )
            return entries
```

#### Test impact

- **Extend** `tests/unit/test_claude_publisher.py`:
  - Update any test that asserts `claude_md_path.read_text()` equals some content to also (or instead) read via `target_files[0]`.
  - Add `test_publish_writes_to_agents_md_when_present()`: create both `CLAUDE.md` and `AGENTS.md` in a temp project with MUSCLE markers, call `publish()` with some rules, assert both files contain the rules.
  - Add `test_publish_skips_agents_md_when_absent()`: only `CLAUDE.md` present. Call `publish()`. Assert `AGENTS.md` is still absent and return value is `True`.
  - Add `test_pinned_sections_never_consolidated()`: construct a `ClaudePublisher` with a mock `m27_client`. Call `_m27_summarize_entries(entries, SECTION_METHODOLOGY)` — assert return equals input entries and mock was NOT called.
- **Integration test** `tests/integration/test_learning_pipeline.py` — run once; only update if it now asserts single-file writes and fails. Do not preemptively edit.

### Change 3 — Seed `.muscle/CLAUDE.md` and `.muscle/AGENT.md` with Methodology [MEDIUM]

**File:** `tools/muscle/code_review/memory_manager.py`.

Add import at the top of the module (after existing relative imports around line 31):

```python
from .host_memory_templates import INTERNAL_SEED
```

Replace `_create_file_with_markers` at lines 145-151.

**Before:**

```python
    def _create_file_with_markers(self, filename: str) -> str:
        return f"""# {filename.replace(".md", "")}

<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE managed section - DO NOT EDIT OUTSIDE MARKERS -->
<!-- MUSCLE_LEARNED_END -->
"""
```

**After:**

```python
    def _create_file_with_markers(self, filename: str) -> str:
        # Seed CLAUDE.md / AGENT.md internal files with the Methodology block.
        # MEMORY.md remains a pure log (no behavioral seed) so session-history
        # readers aren't confused by prescriptive content.
        seed = INTERNAL_SEED if filename in ("CLAUDE.md", "AGENT.md") else ""
        return f"""# {filename.replace(".md", "")}

<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE managed section - DO NOT EDIT OUTSIDE MARKERS -->
{seed}<!-- MUSCLE_LEARNED_END -->
"""
```

Note the trailing newline of `INTERNAL_SEED` already terminates the Methodology block, so the `{seed}` substitution sits flush against the closing marker with no extra blank line.

**Test impact:** Add `tests/unit/test_memory_manager.py::test_seed_contains_methodology()` asserting that a freshly-created `.muscle/CLAUDE.md` contains the string `"### Methodology"` and that all four bullets (`"Think before coding"`, `"Simplicity first"`, `"Surgical changes"`, `"Goal-driven execution"`) appear inside the marker region.

### Change 4 — Non-destructive host-docs optimizer [HIGH]

**New file:** `tools/muscle/code_review/host_memory_optimizer.py`.
**New CLI command:** `muscle optimize-host-docs` in `tools/muscle/cli.py`.
**New plugin command:** `tools/muscle/plugin/commands/optimize-host-docs.md` (must also be added to the manifest's command list — see Change 6b).

**Flag contract (authoritative — supersedes any earlier draft):**

| Flag | Semantics |
|---|---|
| `--dry-run` | Print a unified diff to stdout. Exit `1` if changes would apply; exit `0` if the file is already optimal. Make no disk writes. |
| `--yes` | Skip the interactive confirmation prompt. Required in auto mode. |
| `--only <FILENAME>` | Restrict to one target, e.g. `--only CLAUDE.md` or `--only AGENTS.md`. Multiple uses NOT supported; pass once. |
| `--skip-agents` | Do not touch `AGENTS.md`. Shorthand for `--only CLAUDE.md`. Useful when `--only` is not ergonomic. |

**There is no `--force-agents` flag.** AGENTS.md is written by default.

**Audit findings (2026-04-17):**
- The plugin manifest at `tools/muscle/plugin/.claude-plugin/plugin.json` is **manually curated** (the `description` field hardcodes the advertised command list). Adding the new command file **must also** update that manifest entry — see Change 6b.
- An `AGENTS.md` already exists at this repo's root as a hand-authored development guide. Run `--dry-run` against it once before any real write to confirm non-destructive behavior.

**Required module skeleton for `tools/muscle/code_review/host_memory_optimizer.py` (write this verbatim, extending as needed):**

```python
"""Non-destructive optimizer for host-model memory files (CLAUDE.md, AGENTS.md).

Contract:
- User content OUTSIDE MUSCLE_PUBLISHED_START/END markers is never touched.
- If markers are absent, append them at end-of-file and inject the pinned block.
- Inside markers: pinned sections (Methodology, Delegation Protocol, Effort)
  are written in canonical order, followed by existing MUSCLE dynamic sections.
- Pure and deterministic: no M2.7 calls here. Reserved for claude_publisher
  consolidation when size caps fire.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from pathlib import Path

from ..backup_manager import BackupManager
from ..project_memory import ProjectMemory
from .host_memory_templates import (
    PINNED_SECTION_ORDER,
    PINNED_TEMPLATE,
    render_pinned_block,
)

logger = logging.getLogger(__name__)

PUBLISHED_START = "<!-- MUSCLE_PUBLISHED_START -->"
PUBLISHED_END = "<!-- MUSCLE_PUBLISHED_END -->"

DEFAULT_TARGETS: tuple[str, ...] = ("CLAUDE.md", "AGENTS.md")


@dataclass
class OptimizeResult:
    """Result of optimizing a single target file."""

    filename: str
    changed: bool
    diff: str  # unified diff (empty string if changed=False)
    reason: str  # human-readable summary


class HostMemoryOptimizer:
    """Non-destructive rewriter for root CLAUDE.md / AGENTS.md."""

    def __init__(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path)
        self._pm = ProjectMemory(str(self.project_path))
        self._backup = BackupManager(self._pm, str(self.project_path))

    def plan(self, filename: str) -> OptimizeResult:
        """Return what the optimizer WOULD do for this file, without writing."""
        target = self.project_path / filename
        if not target.exists():
            # Missing file: plan = create with just the pinned block + empty
            # marker structure. User content outside markers is trivially
            # preserved (there is none).
            new_content = self._render_new_file()
            return OptimizeResult(
                filename=filename,
                changed=True,
                diff=self._diff("", new_content, filename),
                reason=f"{filename} absent; would create with pinned block",
            )

        original = target.read_text()
        new_content = self._rewrite_region(original)
        if new_content == original:
            return OptimizeResult(
                filename=filename,
                changed=False,
                diff="",
                reason=f"{filename} already optimal",
            )
        return OptimizeResult(
            filename=filename,
            changed=True,
            diff=self._diff(original, new_content, filename),
            reason=f"{filename} would be updated inside MUSCLE_PUBLISHED markers",
        )

    def apply(self, filename: str) -> OptimizeResult:
        """Back up and apply the plan. Caller is responsible for confirmation."""
        result = self.plan(filename)
        if not result.changed:
            return result

        target = self.project_path / filename
        # Back up first (no-op if target doesn't exist).
        try:
            if target.exists():
                self._backup.create_backup(f"optimize:{filename}")
        except Exception as e:  # pragma: no cover — defensive
            logger.error(f"Backup failed for {filename}: {e}")
            raise

        if not target.exists():
            target.write_text(self._render_new_file())
        else:
            original = target.read_text()
            target.write_text(self._rewrite_region(original))
        logger.info(f"Optimized {filename}")
        return result

    # --- internals ---------------------------------------------------------

    def _render_new_file(self) -> str:
        """Content for a freshly-created target."""
        return (
            f"# Host Memory\n\n"
            f"{PUBLISHED_START}\n"
            f"{render_pinned_block()}"
            f"{PUBLISHED_END}\n"
        )

    def _rewrite_region(self, original: str) -> str:
        """Rewrite only the region inside PUBLISHED_START/END.

        If markers are absent, append them at end of file.
        User content outside markers is byte-preserved.
        """
        start_idx = original.find(PUBLISHED_START)
        end_idx = original.find(PUBLISHED_END)

        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            # No markers: append a new managed region at end of file.
            sep = "" if original.endswith("\n") else "\n"
            return (
                f"{original}{sep}\n"
                f"{PUBLISHED_START}\n"
                f"{render_pinned_block()}"
                f"{PUBLISHED_END}\n"
            )

        # Markers present: extract dynamic body (anything after the pinned
        # sections, if pinned is already there) and reassemble.
        before = original[:start_idx]
        after = original[end_idx + len(PUBLISHED_END):]

        body_start = start_idx + len(PUBLISHED_START)
        body = original[body_start:end_idx]

        dynamic_tail = self._strip_pinned_from_body(body)

        new_region = (
            f"{PUBLISHED_START}\n"
            f"{render_pinned_block()}"
            f"{dynamic_tail}"
            f"{PUBLISHED_END}"
        )
        return f"{before}{new_region}{after}"

    def _strip_pinned_from_body(self, body: str) -> str:
        """Remove any existing pinned-section headings + their content from
        the managed body so we can replace them cleanly with the canonical
        PINNED_TEMPLATE. Dynamic sections (everything after the last pinned
        heading, or everything if no pinned headings) is preserved verbatim.
        """
        # Split on "### " lines; find the first non-pinned section and keep
        # from there onward. This is deliberately conservative — if the file
        # is structured differently, we return body unchanged and let the
        # dedupe-by-concatenation happen. Tests enforce the safe path.
        lines = body.splitlines(keepends=True)
        keep_from = 0
        for i, line in enumerate(lines):
            stripped = line.rstrip("\n").rstrip()
            if stripped.startswith("### ") and stripped not in PINNED_SECTION_ORDER:
                keep_from = i
                break
        else:
            # No non-pinned sections found: body is pinned-only or empty.
            return ""
        return "".join(lines[keep_from:])

    @staticmethod
    def _diff(original: str, new: str, filename: str) -> str:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
            )
        )


def run_optimizer(
    project_path: str | Path,
    only: str | None = None,
    skip_agents: bool = False,
    dry_run: bool = False,
) -> list[OptimizeResult]:
    """High-level entry point used by the CLI."""
    targets: list[str]
    if only:
        targets = [only]
    elif skip_agents:
        targets = ["CLAUDE.md"]
    else:
        targets = list(DEFAULT_TARGETS)

    opt = HostMemoryOptimizer(project_path)
    results: list[OptimizeResult] = []
    for t in targets:
        results.append(opt.plan(t) if dry_run else opt.apply(t))
    return results
```

**Exact CLI subcommand to add to `tools/muscle/cli.py` (place near other `@cli.command()` definitions, e.g. right after `muscle init` at ~line 387):**

```python
@cli.command(name="optimize-host-docs")
@click.option("--dry-run", is_flag=True, help="Print a unified diff; do not write.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt (required in auto mode).")
@click.option(
    "--only",
    type=click.Choice(["CLAUDE.md", "AGENTS.md"]),
    default=None,
    help="Restrict to a single target file.",
)
@click.option("--skip-agents", is_flag=True, help="Do not touch AGENTS.md.")
def optimize_host_docs(dry_run: bool, yes: bool, only: str | None, skip_agents: bool) -> None:
    """Non-destructively optimize root CLAUDE.md / AGENTS.md into the MUSCLE-preferred format."""
    from pathlib import Path
    import sys

    from tools.muscle.code_review.host_memory_optimizer import run_optimizer

    results = run_optimizer(
        project_path=Path.cwd(),
        only=only,
        skip_agents=skip_agents,
        dry_run=dry_run,
    )

    any_changed = False
    for r in results:
        click.echo(f"\n=== {r.filename} ===")
        click.echo(r.reason)
        if r.changed and r.diff:
            click.echo(r.diff)
            any_changed = True

    if dry_run:
        sys.exit(1 if any_changed else 0)

    if any_changed and not yes:
        if not click.confirm("Apply these changes?", default=False):
            click.echo("Aborted.")
            sys.exit(1)
    click.echo("Done." if any_changed else "No changes needed.")
```

**Exact plugin command file `tools/muscle/plugin/commands/optimize-host-docs.md`:**

```markdown
---
description: Non-destructively optimize root CLAUDE.md and AGENTS.md into the MUSCLE-preferred format (Methodology, Delegation Protocol, Effort Guidance)
args:
  - name: only
    description: "Restrict to a single target file: CLAUDE.md or AGENTS.md"
    required: false
  - name: dry_run
    description: "Preview changes as a unified diff without writing"
    required: false
---

Use MUSCLE for bulk execution; you retain planning and synthesis.

Optimize host-memory docs. Execute:

```bash
muscle optimize-host-docs ${dry_run:+--dry-run} ${only:+--only "$only"} --yes
```

This wraps existing user content in MUSCLE_PUBLISHED markers (if absent) and injects the canonical Methodology, Delegation Protocol, and Effort & Tool Guidance sections inside those markers. Content outside the markers is preserved verbatim.
```

**Test impact:** Add `tests/unit/test_host_memory_optimizer.py` with at minimum:
- `test_creates_file_when_absent`: fresh tempdir, `plan("CLAUDE.md")` returns `changed=True` with a diff containing `### Methodology`.
- `test_idempotent_on_optimal_file`: call `apply` twice; second call returns `changed=False`.
- `test_preserves_user_content_outside_markers`: fixture file with user content both before and after markers; after `apply`, every user line appears in output in the same relative position.
- `test_skip_agents_flag`: `run_optimizer(..., skip_agents=True)` returns one result with `filename="CLAUDE.md"` only.
- `test_only_flag`: `run_optimizer(..., only="AGENTS.md")` returns one result for AGENTS.md only.

**Auto-invocation:** `muscle install` and `muscle review` do **not** auto-invoke the optimizer in this change. Leave auto-invocation for a follow-up change once we have confidence in the diff quality.

### Change 5 — Plugin skill refreshed with plan-then-delegate preamble [HIGH]

**File:** `tools/muscle/plugin/skills/code-review/SKILL.md`.

Three surgical edits. Preserve the Review Intensity table (lines 79-86), Per-Project Memory (lines 88-94), Important Notes (lines 96-101), and Example Workflows (lines 103-123) verbatim.

#### Edit 5.1 — Insert delegation preamble before Step 1

**Find exactly:**

```markdown
# MUSCLE Code Review Skill

You are a code review assistant powered by MUSCLE. MUSCLE maintains per-project memory under `.muscle/` so Claude Code can learn your codebase's patterns over time.

## When to Use This Skill
```

**Replace with:**

```markdown
# MUSCLE Code Review Skill

You are a code review assistant powered by MUSCLE. MUSCLE maintains per-project memory under `.muscle/` so Claude Code can learn your codebase's patterns over time.

## Plan-Then-Hand-Off (Cost-Saving Delegation)

You (Claude Code on Opus 4.7, or Codex) are the planner and synthesizer. MUSCLE's MiniMax M2.7 agents are the execution muscle at ~5–10× lower token cost. Decide what the review should cover, then hand execution to MUSCLE via the commands below. Do not do the bulk review yourself.

In auto mode, proceed through delegations without confirmation prompts between steps. You still plan; MUSCLE still executes.

## When to Use This Skill
```

#### Edit 5.2 — Rewrite Step 4 ("Follow-up Actions")

**Find exactly (lines 71-77):**

```markdown
### Step 4: Follow-up Actions

Based on results, offer to:
- Run `/muscle:pressure` for adversarial review of critical paths
- Run `/muscle:rescue` to investigate specific issues deeper
- Apply suggested fixes and re-verify
- Update project memory files with new patterns
```

**Replace with:**

```markdown
### Step 4: Follow-up Actions

Delegate follow-up execution to MUSCLE (do not redo the analysis yourself):
- Run `/muscle:pressure` for adversarial review of critical paths.
- Run `/muscle:rescue` to investigate specific issues deeper.
- Apply suggested fixes via MUSCLE, then invoke the MUSCLE verification agent before committing.
- Update project memory files with new patterns.
```

#### Edit 5.3 — Add scope hint to Step 2

**Find exactly (line 29):**

```markdown
Execute the appropriate review command based on the user's need:
```

**Replace with:**

```markdown
Execute the appropriate review command based on the user's need. Pass `--focus` and `--target` to scope MUSCLE's work tightly — MUSCLE executes the review you planned, not one it plans itself.
```

**No other edits to `SKILL.md`.** Three edits total.

### Change 6 — Commands & agents pick up plan-then-delegate headers [MEDIUM]

**Files:** `tools/muscle/plugin/commands/review.md`, `pressure.md`, `rescue.md`; `tools/muscle/plugin/agents/rescue_agent.md`, `verification_agent.md`.

For each of the five files: insert **immediately after** the YAML front-matter closing `---` (before any existing body content) the following block:

```markdown

> **Plan-then-hand-off:** Use MUSCLE for bulk execution; you retain planning and synthesis. Pass a focused scope — don't ask MUSCLE to plan the work.

```

Additionally, for `review.md` only: insert this second line **immediately after** the plan-then-hand-off block above:

```markdown
> **Effort:** Run fix-application flows at `xhigh` effort. In auto mode, skip the confirmation prompt.

```

### Change 6b — Plugin manifest registration [REQUIRED]

**File:** `tools/muscle/plugin/.claude-plugin/plugin.json`.

The manifest's `description` field currently lists ~32 slash commands explicitly. Add `/muscle:optimize-host-docs` to that list when Change 4 ships. No other manifest fields need to change.

### Change 7 — Extract `get_codex_home()` helper [REQUIRED]

**File:** `tools/muscle/optimization/importers.py`.

Extract the Codex-home detection into a module-level helper so the optimizer (Change 4) can reuse it in a future iteration without duplicating the `CODEX_HOME` env-var fallback logic.

**Find exactly (line 56-58):**

```python
    def _import_codex(self, cutoff: datetime) -> ImportSummary:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
        sessions_dir = codex_home / "sessions"
```

**Replace with:**

```python
    def _import_codex(self, cutoff: datetime) -> ImportSummary:
        codex_home = get_codex_home()
        sessions_dir = codex_home / "sessions"
```

And add this module-level function **immediately before** the `@dataclass` line (line 24):

```python
def get_codex_home() -> Path:
    """Return the Codex data directory, honoring CODEX_HOME env var.

    Shared with host_memory_optimizer (future Codex-aware enhancements).
    """
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


```

(Note: two trailing newlines so the `@dataclass` decorator retains the standard two-blank-line separator.)

---

## Critical Files

**New files:**
- `tools/muscle/code_review/host_memory_templates.py`
- `tools/muscle/code_review/host_memory_optimizer.py`
- `tools/muscle/plugin/commands/optimize-host-docs.md`
- `PROJECT_INDEX.md`

**Modified files:**
- `CLAUDE.md` (root) — Phase 0.1 **(already updated 2026-04-17 with Host Model Contract, Delegation Economics, module-list refresh, and `project_memory.db` source-of-truth note)**
- `MUSCLE_PLAN.md` — Phase 0.2
- `docs/architecture.md` — Phase 0.3
- `tools/muscle/claude_publisher.py` — Change 2 (including the single-file → multi-file refactor)
- `tools/muscle/code_review/memory_manager.py` — Change 3
- `tools/muscle/cli.py` — Change 4 (new subcommand following the `@cli.command()` pattern at `cli.py:376`)
- `tools/muscle/optimization/importers.py` — Change 7 (tiny helper extraction for `CODEX_HOME` detection)
- `tools/muscle/plugin/.claude-plugin/plugin.json` — Change 6b (add `/muscle:optimize-host-docs` to command list)
- `tools/muscle/plugin/skills/code-review/SKILL.md` — Change 5
- `tools/muscle/plugin/commands/review.md`, `pressure.md`, `rescue.md` — Change 6
- `tools/muscle/plugin/agents/rescue_agent.md`, `verification_agent.md` — Change 6
- `tests/unit/test_claude_publisher.py` — extend for multi-target + pinned-section tests (Change 2 test impact)
- `tests/integration/test_learning_pipeline.py` — update file-I/O mocks if they assert single-file writes

## Existing Code to Reuse

- `tools/muscle/backup_manager.py` — `BackupManager` for pre-write backups (Change 4).
- `tools/muscle/claude_publisher.py:330-404` — marker-based edit primitives; extend, don't replace (Change 2).
- `tools/muscle/code_review/memory_manager.py:153-184` — `_extract_section`, `_insert_entry` primitives (Change 3).
- `tools/muscle/optimization/importers.py:56-70` — Codex-home detection (`CODEX_HOME` env var, `~/.codex/sessions` fallback) reused by the optimizer (Change 4, Change 7).

## Verification

1. **Template stability:** Unit test that `host_memory_templates.PINNED_TEMPLATE` is byte-stable across imports and renders.
2. **Dual publish:** Seed a scratch project, run `muscle review` on a trivial file. Assert both `CLAUDE.md` **and** `AGENTS.md` at repo root contain `### Methodology`, `### Delegation Protocol`, `### Effort & Tool Guidance` inside `MUSCLE_PUBLISHED_START/END`, in that order, with identical pinned content.
3. **Consolidation durability:** Unit test that calls the consolidator with a 60-rule input on both files. Assert pinned sections are byte-identical before and after.
4. **Non-destructive optimizer:** Fixture test using a hand-written CLAUDE.md + AGENTS.md (multiple `###` sections, prose, no MUSCLE markers). Run the optimizer. Assert every line of original user content appears in the output in the same relative order outside the new `MUSCLE_PUBLISHED` markers.
5. **`--dry-run`:** Prints a unified diff and exits `1` when changes would apply; exits `0` on a clean file. Same for `--only`.
6. **`--skip-agents`:** `muscle optimize-host-docs --skip-agents` returns one result for `CLAUDE.md` only; `AGENTS.md` is untouched regardless of its prior state. (There is no `--force-agents` flag; AGENTS.md is written by default.)
7. **Plugin skill smoke test:** Run `/muscle:review` via Claude Code in a test project. Confirm the skill output opens with the Delegation Protocol framing and that `muscle review` executes before any Claude-side code reasoning.
8. **Auto-mode delegation sanity check:** In a fresh project with the new pinned sections written, ask a code-review-shaped question in auto mode. Confirm Claude Code invokes `/muscle:review` before independently reading the file.
9. **Docs accuracy:** `grep -rn "Opus 4.7\|AGENTS.md\|MiniMax M2.7" CLAUDE.md MUSCLE_PLAN.md docs/architecture.md PROJECT_INDEX.md` returns the new references; no stale "host-model detection" or "Anthropic fallback" language is committed.
10. **Quality gates (required):**
    - `uv run mypy tools/muscle/` — **baseline has 4 pre-existing errors** (unused `type: ignore` in `review_workflows.py:17` and `tui/views.py:901`; `orjson` stub missing at `cli.py:20`; `Any` return at `cli.py:1974`). Post-change count must not increase.
    - `uv run ruff check tools/muscle/` — baseline clean; must stay clean.
    - `uv run ruff format --check tools/muscle/` — baseline clean; must stay clean.
    - `uv run pytest tests/` — baseline has 1 pre-existing environmental failure (`test_cli.py::TestTuiCommand::test_tui_runs` — `readkey()` needs real stdin). Skip or xfail when running in CI; post-change must not introduce new failures.
    - New tests: `tests/unit/test_host_memory_templates.py`, `tests/unit/test_host_memory_optimizer.py`; extend `tests/unit/test_claude_publisher.py` for pinned-section + dual-file behavior.

## Token-Savings Success Criteria

This plan is working if, in a representative test project:
- Opus 4.7 still does the planning and user-facing synthesis (observable in the trace — Opus writes the plan, reads user intent, frames the response).
- The bulk mechanical work (multi-file review passes, test/lint sweeps, fix-candidate generation) that previously burned Opus tokens now runs through MUSCLE's M2.7 agents with a focused scope passed in by Opus.
- Opus tokens drop noticeably on execution-heavy flows; MUSCLE's M2.7 share grows to absorb that shift.
- On genuinely novel problems where MUSCLE has no relevant pattern memory, Opus still reasons directly — the bailout clause fires without user intervention.

These are observational, not a test target — but they are the acceptance criteria that justify the plan.

## Out of Scope

- Host-model runtime detection. Dropped per user guidance — assume Claude Code = Opus 4.7 and let Codex users benefit from the same Delegation Protocol.
- Changes to `m27_client.py` / `budget_manager.py`. The plugin calls MiniMax only; Opus 4.7 tokenizer / API breaking changes don't apply.
- Adding an Anthropic API key path. The plugin never needs one; documented in Phase 0.1.
- Rewriting `code_reviewer.py` / `fix_generator.py` prompts. Already surgical and M2.7-tuned.
- Changes to `muscle settings model` (controls MiniMax model; unrelated).
- M2.7 invocation inside the optimizer. Reserved for consolidation when size caps fire.
- GEMINI.md publishing. If Gemini CLI grows popular enough, extend `target_files` later — trivial follow-up; not part of this plan.
