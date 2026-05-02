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
SECTION_DELEGATION = "### Delegation Protocol (Plan-Then-Hand-Off)"
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

_These commands require the MUSCLE plugin bundle to be active in this project (for example, the Claude or Codex plugin bundle under `tools/muscle/plugin`). Without it, reason directly._

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
