# MUSCLE Production Roadmap (Living Plan)

**Status:** Active (single source of truth as of 2026-04-17)
**Replaces the planning role of:** `MUSCLE_PLAN.md` (phase plan), `MUSCLE_HANDOFF_DELEGATION_AND_COST_SAVINGS.md` (Ryan's handoff, absorbed), `Forsight-plan.md` (deferred — tracked here as Phase D), `GroupTink-collab.md` (deferred — tracked here as Phase D), `docs/REMAINING_TODOS.md` (pre-release audit items, integrated as hardening track).
**Still referenced verbatim:** `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md` (the Sonnet-ready implementation plan for Phase A — 1119 lines of exact code diffs, do not duplicate here), `docs/architecture.md` (authoritative design), `CLAUDE.md` (maintainer guide), `PROJECT_INDEX.md` (navigational map).

This document is the **singular living plan** for taking MUSCLE from its current working-but-incomplete state to a production-quality release. It orders every open workstream, gives each one implementation-level detail a smaller model (Sonnet 4.6 / GPT-5) can execute, and defines the gates for shipping.

---

## 1. How to read this plan

1. **Start at §3 Execution Timeline.** It is the authoritative sequence. Do not reorder.
2. **For Phase A (delegation overhaul), open `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md`.** That file contains exact before/after code snippets, Python skeletons, test scaffolds, and a strict import-graph-preserving order. This roadmap points at it; it does not duplicate.
3. **For Phase B (cost-savings features), read §6 here.** Each sub-phase has a module skeleton, file list, test names, and verification thresholds sized for Sonnet-grade execution.
4. **For Phase C (pre-release hardening), read §7 here.** Integrates the open audit findings from `docs/REMAINING_TODOS.md` with priorities that match the production release gate.
5. **For Phase D (deferred), read §8 here.** Foresight and consensus review are deliberately deferred until cost-savings observability (B.6) gives us the data to justify them.

**Invariants — do not violate under any circumstance:**

- The plugin **never** needs an Anthropic API key. `MINIMAX_API_KEY` and `ANTHROPIC_API_KEY` are interchangeable names for the MiniMax credential against MiniMax's Anthropic-compatible endpoint.
- The plugin **never** calls real Anthropic. Do not add a fallback without stripping `temperature` / `top_p` / `top_k` (400 errors on Opus 4.7).
- **No host-model runtime detection.** Assume Claude Code = Opus 4.7. Let Codex users benefit from the same protocol via `AGENTS.md`.
- **Do not reorder Phase A's change sequence.** Later changes import from earlier ones. Phase A lands as one atomic commit; piecemeal is forbidden.
- **Do not publish `GEMINI.md`.** Trivial `target_files` extension later if needed; out of scope.
- **Foresight (Phase D) must never promote rules into long-term memory.** Hard invariant enforced by test.
- **Quality gate baseline as of 2026-04-17:** ruff + format clean; mypy has 4 pre-existing errors; pytest has 1 pre-existing environmental failure (`test_cli.py::TestTuiCommand::test_tui_runs` — needs real stdin). Post-change counts must not increase. Exact error citations at `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md:1094-1098`.

---

## 2. Current state (verified 2026-04-17, commit `2423101`)

**Shipped:**
- DB-first architecture: `project_memory.db` is the authoritative per-project store. Migrations `_0001` through `_0012` landed (`_0012_shadow_job_liveness` being the latest).
- `LearningPipeline` wired after review completion. `MemoryDecisionEngine` scores rules for promotion.
- `ClaudePublisher` publishes to root `CLAUDE.md` inside `MUSCLE_PUBLISHED_START/END` markers with 50-line section caps and M2.7 consolidation on overflow.
- Review modes: `review`, `auto-fix`, `plan`, `hybrid`, `pressure` all dispatched via `ReviewController`.
- Code-gen loop: `LoopController` + `CodeGenerator` + `EvaluatorRegistry` + `Evolver`.
- Plugin bundle at `tools/muscle/plugin/` with skill, 30+ commands, rescue + verification agents. Manifest at `.claude-plugin/plugin.json` is manually curated.
- Optimization subsystem (`tools/muscle/optimization/`): context budgeter, prompt optimizer, session recorder, external-session importers (Claude Code + Codex), workflow optimizer.
- Model-identity + model-pack overlay: `model_identity.py`, `model_packs.py`, `model_pack_standard.py`, `model_pack_validation.py`. Pack overlay policy is overlay-never-override.
- Codex session import via `optimization/importers.py:_import_codex` reading `$CODEX_HOME/sessions`.
- `docs/project-first-growth-model-pack-roadmap.md` workstreams W1 (Foundation Hardening), W3 (Model Identity), W4 (Model-Pack Distribution) mostly complete; see that doc for granular status.

**Not shipped (this plan's scope):**
- No `AGENTS.md` publishing anywhere.
- No pinned Methodology / Delegation Protocol / Effort block in published memory files.
- No `host_memory_templates.py`, `host_memory_optimizer.py`, `muscle optimize-host-docs`.
- No task-level routing (`muscle route`).
- No harness-wide structured I/O contracts.
- No M2.7 response cache (only cost-estimate cache exists today).
- No escalation policy module.
- No reusable context packs (`muscle pack`).
- No delegation observability (`muscle cost --delegation-report`).
- ~20 pre-release audit items open in `docs/REMAINING_TODOS.md` including 6 🔴 High findings.

---

## 3. Execution Timeline (authoritative sequence)

```
Week 1   Phase A — Delegation Overhaul (atomic; one commit)
Week 2   Phase B.6 — Observability (measurement must exist before the rest)
Week 3   Phase B.1 + B.2 — Task routing + structured I/O contracts
Week 4   Phase B.3 + B.4 — Response cache + escalation policy
Week 5   Phase B.5 — Context packs
Week 6   Phase C — Pre-release hardening burndown
Week 7   Phase D (optional) — Foresight (A.2). Coordinate with pinned region.
Later    Phase D (gated on B.6 data) — GroupTink / consensus review (A.3)
Later    Phase D (gated on B.5 library) — Cross-project pack library (B.7)
```

**Why this order:**
- A is P0 because it's the single change that structurally redirects host-model tokens to M2.7. Everything else amplifies it.
- B.6 before B.1-B.5 because you cannot tune features whose impact you cannot measure.
- B.1 (routing) before B.3 (caching) because the cache key space is cleaner with task-tier classification.
- B.2 (structured I/O) parallel to B.1 because they share the M2.7 retry surface.
- C (hardening) can overlap with B but must be complete before tagging a release.
- D (Foresight, GroupTink) is deliberately last. Foresight's temporary root-CLAUDE.md injection must not race the pinned region introduced in A. GroupTink is a net cost increase per invocation; we need B.6 data to justify it.

---

## 4. Phase 0 — Pre-flight (do this before any phase)

**Purpose:** Establish baseline and confirm nothing regresses silently.

1. Verify clean working tree: `git status` prints "nothing to commit, working tree clean".
2. Run baseline gates and record the output:
   ```bash
   uv sync --extra dev
   uv run ruff check tools/muscle/
   uv run ruff format --check tools/muscle/
   uv run mypy tools/muscle/ 2>&1 | tee /tmp/muscle-mypy-baseline.txt
   uv run pytest tests/ -v 2>&1 | tee /tmp/muscle-pytest-baseline.txt
   ```
3. Confirm the 4 pre-existing mypy errors (`review_workflows.py:17`, `tui/views.py:901`, `cli.py:20` orjson, `cli.py:1974` Any-return) and the 1 pre-existing pytest failure (`TestTuiCommand::test_tui_runs`). Anything else is a new regression caused by uncommitted work — stop and investigate.
4. For every phase below: run the same gates after completion and diff against baseline.

---

## 5. Phase A — Delegation Overhaul (P0, Week 1, atomic)

**Reference:** `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md` in full. That file is Sonnet-ready — do not deviate from its 9-step implementation order at `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md:112-126`.

**What this phase ships:**
- `tools/muscle/code_review/host_memory_templates.py` (new) — `PINNED_TEMPLATE`, `INTERNAL_SEED`, `render_pinned_block()`, section constants.
- `tools/muscle/code_review/host_memory_optimizer.py` (new) — non-destructive rewriter.
- `tools/muscle/plugin/commands/optimize-host-docs.md` (new) — plugin command + manifest registration.
- `muscle optimize-host-docs` CLI subcommand in `tools/muscle/cli.py`.
- Multi-target publisher: `claude_publisher.py` now writes `CLAUDE.md` **and** `AGENTS.md`, injects pinned block unconditionally, exempts pinned from M2.7 consolidation.
- `memory_manager.py` seeds `.muscle/CLAUDE.md` and `.muscle/AGENT.md` with `INTERNAL_SEED`.
- `get_codex_home()` helper extracted in `optimization/importers.py`.
- Plugin skill + commands + agents carry plan-then-hand-off preambles.
- `MUSCLE_PLAN.md` / `docs/architecture.md` / root `CLAUDE.md` updated (CLAUDE.md already landed 2026-04-17 in commit `2423101`).

**New tests required (per PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md §Test Impact callouts):**
- `tests/unit/test_host_memory_templates.py` — byte-stability.
- `tests/unit/test_host_memory_optimizer.py` — create/idempotent/preserve/skip-agents/only-flag.
- Extend `tests/unit/test_claude_publisher.py` with: `test_publish_writes_to_agents_md_when_present`, `test_publish_skips_agents_md_when_absent`, `test_pinned_sections_never_consolidated`, twice-publish idempotency assertion.

**Verification gate (§Verification in plan, 10 items):** all must pass before Phase B starts. Key thresholds:
- 10/10 verification items green.
- Quality gates match baseline (no new mypy or pytest regressions).
- Running `muscle optimize-host-docs --dry-run` on this repo's hand-authored `AGENTS.md` emits a sensible diff and **does not** corrupt existing user content.

**Delegation hint for this phase:**
- Delegatable to M2.7: Changes 1, 3, 5, 6, 6b, 7, and all test skeletons — spec is verbatim.
- Keep on planner: Changes 2, 4 — non-trivial refactor + new module design. Use the planner for the code, then hand the test-writing to M2.7.

**Commit strategy:** Land Phase A as **one atomic commit**. The import graph in `claude_publisher.py` depends on `host_memory_templates.py` existing; the optimizer depends on the publisher's multi-target support; the plugin skill edits assume the new command file is registered. Piecemeal commits break intermediate states.

---

## 6. Phase B — Cost-Savings Features (P0–P1, Weeks 2–5)

Everything below builds on Phase A. Each sub-phase has an implementation skeleton, file list, test plan, and acceptance metric.

### 6.1 Phase B.6 — Observability: `muscle cost --delegation-report` [P0, Week 2]

**Why first in B:** you cannot optimize what you cannot measure. B.1–B.5 all need this surface to prove their ROI.

**Gap it closes:** `budget_manager.py` tracks MUSCLE's own M2.7 spend but nothing tracks *host-model tokens avoided*. Every feature in B needs a success metric.

**Files to create/modify:**

| Path | Action |
|---|---|
| `tools/muscle/migrations/_0013_delegation_events.py` | **new** — schema for `delegation_events` table |
| `tools/muscle/delegation_metrics.py` | **new** — recorder + report formatter |
| `tools/muscle/cli.py` | add `muscle cost --delegation-report [--since 7d] [--format text|json]` flag to existing `cost` command |
| `tools/muscle/code_review/review_controller.py` | add `DelegationMetrics.record(...)` calls at entry/exit |
| `tools/muscle/loop_controller.py` | same instrumentation |
| `tools/muscle/m27_client.py` | emit token counts per call into metrics |
| `tests/unit/test_delegation_metrics.py` | **new** — report formatter + reconcile vs budget_manager |

**Migration `_0013_delegation_events.py` exact schema:**

```sql
CREATE TABLE IF NOT EXISTS delegation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,                   -- ISO-8601 UTC
    task_tier TEXT,                              -- from B.1 router; NULL if pre-B.1
    entry_point TEXT NOT NULL,                   -- 'review', 'run', 'fix', etc.
    m27_tokens_in INTEGER DEFAULT 0,
    m27_tokens_out INTEGER DEFAULT 0,
    m27_usd_cents INTEGER DEFAULT 0,             -- integer cents; no float rounding
    verifications_run INTEGER DEFAULT 0,
    verifications_failed INTEGER DEFAULT 0,
    escalations_emitted INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    cache_tokens_saved INTEGER DEFAULT 0,
    pack_id TEXT,                                -- B.5 pack id; NULL if no pack
    pack_reused INTEGER DEFAULT 0                -- 0 or 1
);
CREATE INDEX IF NOT EXISTS idx_delegation_events_session ON delegation_events(session_id);
CREATE INDEX IF NOT EXISTS idx_delegation_events_created ON delegation_events(created_at);
```

Follow the existing migration pattern in `migrations/_0012_shadow_job_liveness.py` (version-check → DDL → version-insert → COMMIT; idempotent).

**`ProjectMemory.connection()` prerequisite:** the skeleton below uses `with self._pm.connection() as conn:` but the context-manager helper `_conn()` is pending per `[PM-01]` in `REMAINING_TODOS.md`. **Ship `[PM-01]` as the first task of Week 2** — it's a small refactor (~15 call sites, already documented). If blocked, use this bridge pattern instead:

```python
# BRIDGE (temporary, replace after [PM-01] lands):
import sqlite3
db_path = self._pm._db_path if hasattr(self._pm, "_db_path") else (
    Path(self._pm.project_path) / ".muscle" / "project_memory.db"
)
with sqlite3.connect(db_path) as conn:
    ...
```

The bridge is identical in behavior but bypasses the context-manager helper. Track the migration as a follow-up task after `[PM-01]` lands so all new B.6/B.4/B.5 code flows through `_pm.connection()` uniformly.

**`delegation_metrics.py` module skeleton:**

```python
"""Records and reports cost-delegation events for muscle cost --delegation-report."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)

# Configured per-host estimate (tokens per equivalent delegated task).
# Used for "estimated host tokens avoided" — clearly labeled as estimated.
HOST_TOKEN_ESTIMATES: dict[str, int] = {
    "claude-opus-4-7": 8000,   # average task; refine from B.1 tier data
    "claude-sonnet-4-6": 5000,
    "codex-default": 8000,
}


@dataclass
class DelegationEvent:
    session_id: str
    entry_point: str
    task_tier: str | None = None
    m27_tokens_in: int = 0
    m27_tokens_out: int = 0
    m27_usd_cents: int = 0
    verifications_run: int = 0
    verifications_failed: int = 0
    escalations_emitted: int = 0
    cache_hits: int = 0
    cache_tokens_saved: int = 0
    pack_id: str | None = None
    pack_reused: bool = False


@dataclass
class DelegationReport:
    since: datetime
    total_events: int
    m27_tokens_by_tier: dict[str, int] = field(default_factory=dict)
    cache_hit_rate: float = 0.0
    cache_tokens_saved: int = 0
    escalation_rate: float = 0.0
    estimated_host_tokens_avoided: int = 0
    m27_usd_cents: int = 0


class DelegationMetrics:
    """Thin recorder around project_memory.db delegation_events table."""

    def __init__(self, project_path: str | Path) -> None:
        self._pm = ProjectMemory(str(project_path))

    def record(self, event: DelegationEvent) -> None:
        """Insert one event. Idempotency not enforced — callers own session dedup."""
        with self._pm.connection() as conn:
            conn.execute(
                """INSERT INTO delegation_events
                   (session_id, created_at, task_tier, entry_point,
                    m27_tokens_in, m27_tokens_out, m27_usd_cents,
                    verifications_run, verifications_failed,
                    escalations_emitted, cache_hits, cache_tokens_saved,
                    pack_id, pack_reused)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.session_id,
                    datetime.now(timezone.utc).isoformat(),
                    event.task_tier,
                    event.entry_point,
                    event.m27_tokens_in,
                    event.m27_tokens_out,
                    event.m27_usd_cents,
                    event.verifications_run,
                    event.verifications_failed,
                    event.escalations_emitted,
                    event.cache_hits,
                    event.cache_tokens_saved,
                    event.pack_id,
                    1 if event.pack_reused else 0,
                ),
            )

    def report(
        self,
        since: timedelta = timedelta(days=7),
        host_model: str = "claude-opus-4-7",
    ) -> DelegationReport:
        """Build a DelegationReport covering the trailing `since` window."""
        cutoff = datetime.now(timezone.utc) - since
        with self._pm.connection() as conn:
            rows = conn.execute(
                """SELECT task_tier, m27_tokens_in, m27_tokens_out, m27_usd_cents,
                          cache_hits, cache_tokens_saved, escalations_emitted
                   FROM delegation_events
                   WHERE created_at >= ?""",
                (cutoff.isoformat(),),
            ).fetchall()

        report = DelegationReport(since=cutoff, total_events=len(rows))
        if not rows:
            return report

        for r in rows:
            tier = r[0] or "unknown"
            report.m27_tokens_by_tier[tier] = (
                report.m27_tokens_by_tier.get(tier, 0) + r[1] + r[2]
            )
            report.m27_usd_cents += r[3]
            report.cache_hits += r[4]
            report.cache_tokens_saved += r[5]
            if r[6]:
                # Any escalation counts the event as escalated.
                pass  # tracked below via sum

        total_calls = report.total_events
        report.cache_hit_rate = (
            sum(r[4] for r in rows) / total_calls if total_calls else 0.0
        )
        total_escalations = sum(1 for r in rows if r[6] > 0)
        report.escalation_rate = total_escalations / total_calls if total_calls else 0.0

        # Estimated host tokens avoided = completed delegations × per-host average.
        avg = HOST_TOKEN_ESTIMATES.get(host_model, 8000)
        report.estimated_host_tokens_avoided = total_calls * avg
        return report

    def format_text(self, report: DelegationReport) -> str:
        """Human-readable report for `muscle cost --delegation-report`."""
        lines = [
            f"=== MUSCLE Delegation Report (since {report.since.date()}) ===",
            f"Total delegated tasks: {report.total_events}",
            "",
            "M2.7 tokens by tier:",
        ]
        for tier, tokens in sorted(report.m27_tokens_by_tier.items()):
            lines.append(f"  {tier:20s} {tokens:>10,} tokens")
        lines.extend([
            "",
            f"M2.7 spend:                  ${report.m27_usd_cents / 100:.2f}",
            f"Cache hit rate:              {report.cache_hit_rate:.1%}",
            f"Cache tokens saved:          {report.cache_tokens_saved:,}",
            f"Escalation rate:             {report.escalation_rate:.1%}",
            f"Estimated host tokens        {report.estimated_host_tokens_avoided:,}",
            f"  avoided (NOT measured):",
        ])
        return "\n".join(lines)

    def format_json(self, report: DelegationReport) -> str:
        return json.dumps({
            "since": report.since.isoformat(),
            "total_events": report.total_events,
            "m27_tokens_by_tier": report.m27_tokens_by_tier,
            "m27_usd_cents": report.m27_usd_cents,
            "cache_hit_rate": report.cache_hit_rate,
            "cache_tokens_saved": report.cache_tokens_saved,
            "escalation_rate": report.escalation_rate,
            "estimated_host_tokens_avoided": report.estimated_host_tokens_avoided,
        }, indent=2)
```

**Required tests (`tests/unit/test_delegation_metrics.py`):**
- `test_record_and_retrieve_single_event`: insert one event, assert `report.total_events == 1`.
- `test_report_aggregates_by_tier`: insert 3 events with different tiers, assert aggregation correct.
- `test_report_since_window_excludes_old_events`: insert event with past timestamp, assert not in 1-day window.
- `test_text_format_contains_required_fields`: assert the 6 report fields appear in the text output.
- `test_reconcile_with_budget_manager`: insert events; assert `report.m27_usd_cents` matches `budget_manager`'s raw counter within 1 cent.

**Acceptance metric:** `muscle cost --delegation-report` runs cleanly on any project with `project_memory.db`. Output shows labeled "estimated" for host tokens (clearly not measured). Numbers reconcile with `budget_manager.py` raw counters (no double-counting).

**Delegation hint:** Full delegation to M2.7 — schema, recorder, formatter, tests are all spec-driven.

---

### 6.2 Phase B.1 — Task-level routing: `muscle route` [P0, Week 3]

**Gap it closes:** MUSCLE routes *within* review modes today but has no "classify-this-task-before-acting" step. The planner model decides whether to delegate per call; there's no lightweight classifier.

**Files to create/modify:**

| Path | Action |
|---|---|
| `tools/muscle/routing.py` | **new** — `RouteDecision` dataclass, `TaskRouter` class, classifier prompt, cache wrapper |
| `tools/muscle/cli.py` | add `muscle route --task "..." [--scope <path>] [--json]` |
| `tools/muscle/plugin/commands/route.md` | **new** — `/muscle:route` slash command |
| `tools/muscle/plugin/.claude-plugin/plugin.json` | register `/muscle:route` in `description` |
| `tools/muscle/code_review/review_controller.py` | call router before first bulk pass; emit escalation marker if `escalate_to_host` |
| `tools/muscle/loop_controller.py` | same |
| `tests/unit/test_routing.py` | **new** |

**`routing.py` module skeleton:**

```python
"""Classifier that decides where a task should run (M2.7 vs host model)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .m27_client import M27Client

logger = logging.getLogger(__name__)


class TaskTier(str, Enum):
    MECHANICAL = "mechanical"     # pattern-match / boilerplate / test
    REASONING = "reasoning"       # trace / debug / refactor
    ARCHITECTURAL = "architectural"  # design / decision / multi-module


class Recommendation(str, Enum):
    M27 = "m27"                              # run on M2.7 directly
    M27_WITH_VERIFY = "m27_with_verify"      # M2.7 with verification loop
    ESCALATE_TO_HOST = "escalate_to_host"    # emit escalation marker


@dataclass
class RouteDecision:
    tier: TaskTier
    recommended: Recommendation
    confidence: float       # 0.0–1.0
    rationale: str
    from_cache: bool = False


ROUTE_SYSTEM_PROMPT = """You are a task-complexity classifier. Given a task description, decide:
1. tier: 'mechanical' (pattern/boilerplate/test), 'reasoning' (debug/trace/refactor), or 'architectural' (design/decision/multi-module).
2. recommended: 'm27' for direct M2.7 execution, 'm27_with_verify' for M2.7 with verification loop, 'escalate_to_host' for the host model to plan directly.
3. confidence: 0.0–1.0.
4. rationale: one short sentence.

Rules:
- 'architectural' tasks ALWAYS get 'escalate_to_host'.
- 'mechanical' tasks with obvious test targets get 'm27_with_verify'.
- Otherwise 'm27'.
- If confidence < 0.5, default to 'escalate_to_host'.

Return ONLY valid JSON matching the schema: {"tier": ..., "recommended": ..., "confidence": ..., "rationale": ...}.
"""


class TaskRouter:
    def __init__(self, m27_client: M27Client, cache_db_path: Path | None = None) -> None:
        self._m27 = m27_client
        self._cache_db = cache_db_path or Path.home() / ".muscle" / "cache" / "cache.db"

    def route(self, task_description: str, scope: Path | None = None) -> RouteDecision:
        cache_key = self._cache_key(task_description, scope)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return RouteDecision(**cached, from_cache=True)

        decision = self._classify_via_m27(task_description, scope)
        self._cache_put(cache_key, decision)
        return decision

    def _classify_via_m27(self, task: str, scope: Path | None) -> RouteDecision:
        user_prompt = f"Task: {task}"
        if scope:
            user_prompt += f"\nScope hint: {scope}"
        response, _ = self._m27.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=ROUTE_SYSTEM_PROMPT,
            max_tokens=256,
            temperature=0.1,
        )
        data = self._parse_json_response(response)
        return RouteDecision(
            tier=TaskTier(data["tier"]),
            recommended=Recommendation(data["recommended"]),
            confidence=float(data["confidence"]),
            rationale=data["rationale"],
        )

    def _cache_key(self, task: str, scope: Path | None) -> str:
        scope_fp = self._scope_fingerprint(scope) if scope else ""
        h = hashlib.sha256(f"{task}||{scope_fp}".encode()).hexdigest()
        return f"route:{h}"

    def _scope_fingerprint(self, scope: Path) -> str:
        """Hash of sorted (path, sha256) tuples for files under scope."""
        if not scope.exists():
            return ""
        pairs = []
        if scope.is_file():
            pairs.append((str(scope), hashlib.sha256(scope.read_bytes()).hexdigest()))
        else:
            for p in sorted(scope.rglob("*")):
                if p.is_file():
                    try:
                        pairs.append((str(p), hashlib.sha256(p.read_bytes()).hexdigest()))
                    except OSError:
                        continue
        return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        """Return cached RouteDecision dict if fresh, else None.

        Uses ResponseCache from Phase B.3. If B.3 has not shipped yet, this
        method should short-circuit to None (no caching) — see B.1→B.3
        dependency note below.
        """
        from .response_cache import ResponseCache  # local import avoids cycles

        cache = ResponseCache(self._cache_db)
        cached = cache.get(key)
        if cached is None:
            return None
        # Reconstruct dict in the format RouteDecision(**...) expects.
        return {
            "tier": TaskTier(cached["tier"]),
            "recommended": Recommendation(cached["recommended"]),
            "confidence": float(cached["confidence"]),
            "rationale": cached["rationale"],
        }

    def _cache_put(self, key: str, decision: RouteDecision) -> None:
        from .response_cache import ResponseCache

        cache = ResponseCache(self._cache_db)
        cache.put(
            key,
            model_id="classifier",  # classifier is host-invariant
            response={
                "tier": decision.tier.value,
                "recommended": decision.recommended.value,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
            },
            ttl_seconds=24 * 60 * 60,  # 24h per B.3 default for route_decision
            tokens_saved=0,  # router calls are tiny; don't credit cache savings
        )

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any]:
        """Strip fences if present; parse JSON; raise on malformed."""
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0]
        return json.loads(text.strip())
```

**CLI skeleton:**

```python
@cli.command(name="route")
@click.option("--task", required=True, help="Task description to classify.")
@click.option("--scope", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def route_cmd(task: str, scope: Path | None, as_json: bool) -> None:
    """Classify a task and decide where it should run (M2.7 vs host)."""
    from tools.muscle.m27_client import M27Client
    from tools.muscle.routing import TaskRouter

    router = TaskRouter(M27Client(api_key=os.environ.get("MINIMAX_API_KEY", "")))
    decision = router.route(task, scope=scope)
    if as_json:
        click.echo(json.dumps({
            "tier": decision.tier.value,
            "recommended": decision.recommended.value,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "from_cache": decision.from_cache,
        }))
    else:
        click.echo(f"Tier:        {decision.tier.value}")
        click.echo(f"Recommended: {decision.recommended.value}")
        click.echo(f"Confidence:  {decision.confidence:.2f}")
        click.echo(f"Rationale:   {decision.rationale}")
```

**Wire into review controller:** at the start of `ReviewController.run()`, call `TaskRouter.route()` with the user's prompt + target path. If `recommended == ESCALATE_TO_HOST`, emit an escalation marker (see Phase B.4 for the marker format) and return early. Record the decision via `DelegationMetrics.record()` (B.6).

**Required tests:**
- `test_classifier_returns_valid_schema`: mock M2.7 returning valid JSON; assert `RouteDecision` fields populated.
- `test_cache_hit_skips_m27_call`: call twice with same input; assert second call returns `from_cache=True` and M2.7 was called exactly once.
- `test_scope_fingerprint_changes_invalidate_cache`: call, modify a scope file, call again; assert M2.7 called twice.
- `test_low_confidence_defaults_to_escalate`: mock M2.7 returning `confidence: 0.3`; assert recommendation overridden to `ESCALATE_TO_HOST`.
- `test_architectural_always_escalates`: mock M2.7 returning `tier: architectural`; assert `ESCALATE_TO_HOST` regardless of confidence.

**Acceptance metric:** on a 50-task fixture set with human labels (create at `tests/fixtures/routing_tasks.jsonl` — one line per task: `{"task": "...", "expected_tier": "..."}`), classifier agreement ≥80% on `mechanical` vs `reasoning` buckets. Cache hit rate >60% on second pass over the same set. End-to-end: architectural task correctly surfaces escalation marker, not an M2.7 run.

**Fixture seed:** 50 tasks split 20 mechanical / 20 reasoning / 10 architectural, drawn from this repo's commit history (`git log --oneline -n 100` for candidate labels). Commit the fixture alongside the code.

**B.1 → B.3 dependency:** Routing cache integration imports `ResponseCache` from B.3. **Ship B.3 before B.1**, OR ship B.1 with cache disabled (`_cache_get` returns `None` unconditionally, `_cache_put` is a no-op). The updated timeline: Week 3 = B.2 + B.3 (both cache infrastructure); Week 4 = B.1 (uses the cache) + B.4. This is a reordering from the original Week 3/4 split — update §3 when you start.

**Delegation hint:** GLM 5.1 for the classifier prompt design + escalation-handoff contract (judgment); M2.7 for module scaffold, CLI, tests (mechanical).

---

### 6.2.bis Dependency pin — Pydantic v2

Before starting B.2: add `pydantic>=2.6,<3` to `[project.dependencies]` in `pyproject.toml`. **Pydantic v1 and v2 have incompatible APIs** — the skeletons in B.2 assume v2 (`Field`, `Literal`, no `Config` classes). Run `uv sync` after the edit; verify `uv run python -c "import pydantic; print(pydantic.VERSION)"` prints `2.x`.

### 6.3 Phase B.2 — Structured I/O contracts [P1, Week 3, parallel to B.1]

**Gap it closes:** M2.7 parse failures are scattered across `code_reviewer.py`, `fix_generator.py`, `pattern_detector.py`, `verification_loop.py`. Each failure is a silent wasted call. A harness-wide schema-validated call path makes parse failures cheap retries.

**Files:**

| Path | Action |
|---|---|
| `tools/muscle/structured_io.py` | **new** — Pydantic schemas for every M2.7 response shape |
| `tools/muscle/m27_client.py` | add `chat_structured(schema, prompt, retries=2)` method |
| `tools/muscle/code_review/code_reviewer.py` | migrate findings parser to `chat_structured` |
| `tools/muscle/code_review/fix_generator.py` | migrate fix-candidate parser |
| `tools/muscle/code_review/pattern_detector.py` | migrate pattern-scan parser |
| `tools/muscle/code_review/verification_loop.py` | migrate verification parser |
| `tests/unit/test_structured_io.py` | **new** |

**`structured_io.py` skeleton:**

```python
"""Pydantic schemas for M2.7 response shapes — harness-wide I/O contract."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class ReviewFinding(BaseModel):
    file_path: str
    line_number: int = Field(ge=1)
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: Literal["security", "correctness", "performance", "style", "docs", "best_practice"]
    title: str
    description: str
    code_snippet: str = ""
    auto_fixable: bool = False
    suggested_fix: str | None = None
    reasoning: str


class ReviewFindings(BaseModel):
    reviews: list[ReviewFinding]


class FixCandidate(BaseModel):
    file_path: str
    original_snippet: str
    fixed_snippet: str
    rationale: str


class PatternScanResult(BaseModel):
    patterns_found: list[str]
    occurrences_by_pattern: dict[str, int]


class VerificationReport(BaseModel):
    passed: bool
    tests_run: int = 0
    tests_failed: int = 0
    lint_passed: bool | None = None
    type_check_passed: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class RouteDecisionSchema(BaseModel):  # mirrors routing.RouteDecision for M2.7 I/O
    tier: Literal["mechanical", "reasoning", "architectural"]
    recommended: Literal["m27", "m27_with_verify", "escalate_to_host"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
```

**`m27_client.chat_structured` — full implementation skeleton (add as a method on existing `M27Client`):**

```python
def chat_structured(
    self,
    schema: type[BaseModel],
    messages: list[dict[str, str]],
    system: str = "",
    max_tokens: int = 4096,
    retries: int = 2,
) -> BaseModel:
    """Call M2.7, parse response as JSON, validate against schema.

    Retries on ValidationError with a schema-corrective follow-up.
    Raises M27StructuredError after retries + 1 total attempts so callers
    can escalate via B.4.
    """
    from pydantic import ValidationError

    schema_hint = (
        f"Reply ONLY with valid JSON matching this schema:\n"
        f"{schema.model_json_schema()}"
    )
    system_with_schema = f"{system}\n\n{schema_hint}" if system else schema_hint

    last_error: Exception | None = None
    working_messages = list(messages)

    for attempt in range(retries + 1):
        response_text, _ = self.chat(
            messages=working_messages,
            system=system_with_schema,
            max_tokens=max_tokens,
            temperature=0.1,  # deterministic for schema adherence
        )
        parsed_text = _strip_json_fences(response_text)
        try:
            import json
            data = json.loads(parsed_text)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            if attempt < retries:
                working_messages.append({"role": "assistant", "content": response_text})
                working_messages.append({
                    "role": "user",
                    "content": (
                        f"Your last response did not match the schema: {e}. "
                        "Reply ONLY with valid JSON matching the schema."
                    ),
                })
            else:
                raise M27StructuredError(
                    f"Failed to produce schema-valid response after {retries + 1} "
                    f"attempts. Last error: {e}"
                ) from e
    # Unreachable, but satisfies mypy.
    raise M27StructuredError(f"Unreachable: {last_error}")


def _strip_json_fences(text: str) -> str:
    """Extract JSON body if wrapped in ```json or ``` fences."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[len("```json"):].lstrip("\n")
    elif text.startswith("```"):
        text = text[len("```"):].lstrip("\n")
    if text.endswith("```"):
        text = text[:-len("```")].rstrip("\n")
    return text.strip()


class M27StructuredError(Exception):
    """Raised when chat_structured fails to produce valid JSON after retries."""
    pass
```

Add `_strip_json_fences` and `M27StructuredError` as module-level in `m27_client.py` (sibling to the existing class).

**Parser migration — exact before/after for `code_reviewer.py`** (apply the same pattern to `fix_generator.py`, `pattern_detector.py`, `verification_loop.py` once this works):

Locate the M2.7 parsing block in `code_reviewer.py` — typically looks like:

```python
# BEFORE (representative; exact form may differ by file):
response_text, _ = self.m27.chat(
    messages=[{"role": "user", "content": prompt}],
    system=SYSTEM_PROMPT,
    max_tokens=4096,
    temperature=0.3,
)
# Manual JSON extraction with fence-stripping + json.loads + dict access.
findings_raw = _extract_json_from_response(response_text)
if "reviews" not in findings_raw:
    logger.warning("M2.7 returned no 'reviews' field")
    return []
findings = [self._parse_finding(r) for r in findings_raw["reviews"]]
```

```python
# AFTER:
from ..structured_io import ReviewFindings

result: ReviewFindings = self.m27.chat_structured(
    schema=ReviewFindings,
    messages=[{"role": "user", "content": prompt}],
    system=SYSTEM_PROMPT,
    max_tokens=4096,
)
findings = [self._from_schema(f) for f in result.reviews]
```

Where `_from_schema` maps the Pydantic `ReviewFinding` to the existing internal dataclass `Finding` (keep the internal dataclass — only the parsing boundary changes). Delete `_extract_json_from_response` and `_parse_finding` once all call sites migrate.

**Required tests:**
- `test_valid_json_parses`: mock M2.7 returning valid JSON; assert schema instance returned.
- `test_malformed_json_retries_then_succeeds`: mock returns garbage, then valid; assert success on retry 1.
- `test_exhausted_retries_raises`: mock always returns garbage; assert `RuntimeError` after `retries + 1` total calls.
- `test_schema_validation_failure_retries`: mock returns syntactically-valid JSON with wrong types; assert retry fires.

**Acceptance metric:** on a replay of the 2026-04-17 test fixture corpus, the count of silent parse failures in `LearningPipeline` drops to 0 over a 1-week baseline. Existing tests continue to pass after parser migration.

**Delegation hint:** Full M2.7 delegation. Schema definitions + mechanical parser migrations are the archetypal spec-driven task.

**Coupling with B.1:** If a `chat_structured` call exhausts retries, the router (B.1) is invoked to decide whether to escalate to host or give up. Wire the retry-counter into the same `DelegationMetrics.record()` call that B.1 uses.

---

### 6.4 Phase B.3 — Response cache for idempotent subtasks [P1, Week 4]

**Gap it closes:** `cost_optimizer.py` caches cost estimates, not responses. Two reviews asking M2.7 the same question about the same unchanged code pay twice.

**Files:**

| Path | Action |
|---|---|
| `tools/muscle/response_cache.py` | **new** — SQLite-backed response cache |
| `tools/muscle/migrations/_0014_response_cache.py` | **new** if we extend `cache.db`, OR add to `response_cache.py` as inline init |
| `tools/muscle/m27_client.py` | wire cache-check before `chat_structured` call; cache-write on successful validation |
| `tools/muscle/cli.py` | add `muscle cache clear [--older-than 7d]` |
| `tests/unit/test_response_cache.py` | **new** |

**Cache table schema (add to `~/.muscle/cache/cache.db`):**

```sql
CREATE TABLE IF NOT EXISTS response_cache (
    key TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    response_json BLOB NOT NULL,       -- JSON body
    tokens_saved INTEGER DEFAULT 0,     -- counted on hit
    created_at TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_response_cache_created ON response_cache(created_at);
```

**Cache key contract:**

```
key = sha256(
  model_id || "||" ||
  system_prompt || "||" ||
  user_prompt || "||" ||
  scope_fingerprint  # sorted (path, sha256) tuples for any file referenced
)
```

**TTL defaults (configurable per call site):**
- `review_findings`: 14 days
- `pattern_scan`: 30 days
- `fix_candidate`: 7 days (surrounding code shifts faster)
- `route_decision`: 24 hours

**`response_cache.py` skeleton:**

```python
"""Content-addressed response cache for M2.7 structured calls."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_DB = Path.home() / ".muscle" / "cache" / "cache.db"


class ResponseCache:
    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self._db = db_path
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.executescript(RESPONSE_CACHE_SCHEMA_SQL)

    @staticmethod
    def build_key(
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        scope_files: list[tuple[str, str]] | None = None,
        pack_id: str | None = None,
    ) -> str:
        """Deterministic cache key.

        scope_files: list of (path, sha256) tuples. Any change invalidates.
        pack_id: B.5 pack content-hash if this call consumes a pack. When
        set, scope_files is typically None (pack already encodes scope).
        """
        scope = json.dumps(sorted(scope_files or []))
        pack = pack_id or ""
        payload = f"{model_id}||{system_prompt}||{user_prompt}||{scope}||{pack}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT response_json, created_at, ttl_seconds FROM response_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        created = datetime.fromisoformat(row[1])
        if datetime.now(timezone.utc) - created > timedelta(seconds=row[2]):
            return None  # expired
        # Update hit counter (separate connection to keep read simple).
        with sqlite3.connect(self._db) as conn:
            conn.execute("UPDATE response_cache SET hit_count = hit_count + 1 WHERE key = ?", (key,))
        return json.loads(row[0])

    def put(self, key: str, model_id: str, response: dict, ttl_seconds: int, tokens_saved: int = 0) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO response_cache
                   (key, model_id, response_json, tokens_saved, created_at, ttl_seconds, hit_count)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    key,
                    model_id,
                    json.dumps(response),
                    tokens_saved,
                    datetime.now(timezone.utc).isoformat(),
                    ttl_seconds,
                ),
            )

    def clear(self, older_than: timedelta | None = None) -> int:
        """Delete entries older than `older_than`. Return count removed."""
        with sqlite3.connect(self._db) as conn:
            if older_than:
                cutoff = (datetime.now(timezone.utc) - older_than).isoformat()
                cur = conn.execute("DELETE FROM response_cache WHERE created_at < ?", (cutoff,))
            else:
                cur = conn.execute("DELETE FROM response_cache")
            return cur.rowcount


RESPONSE_CACHE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS response_cache (
    key TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    response_json BLOB NOT NULL,
    tokens_saved INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_response_cache_created ON response_cache(created_at);
"""
```

**Wire into `m27_client.chat_structured`:** before making the HTTP call, compute the cache key and look up. On hit: return the cached parsed schema instance, increment `DelegationMetrics.cache_hits`. On miss: make the call, validate, and on success `cache.put(...)` with the per-call-site TTL.

**Required tests:**
- `test_put_then_get_roundtrip`.
- `test_expired_entry_returns_none`: put with `ttl=1s`, sleep 2s, assert `get()` returns None.
- `test_cache_key_deterministic`: call `build_key` twice with same args; assert same hash.
- `test_scope_change_invalidates`: put with one scope, get with modified scope hash, assert miss.
- `test_clear_older_than`: insert 3 entries across 10d; `clear(older_than=7d)` removes 2.
- `test_hit_count_increments`.

**Acceptance metric:** cache hit rate >40% on second-run benchmark over `tools/muscle/code_review/benchmark_fixtures/`. Token savings surfaced in `muscle cost --delegation-report` under `cache_tokens_saved`.

**Delegation hint:** Full M2.7 delegation. Schema + query + wiring are mechanical.

---

### 6.5 Phase B.4 — Escalation policy module [P1, Week 4, parallel to B.3]

**Gap it closes:** `verification_loop.py` reverts failed fixes but doesn't escalate. After 2 failures on the same issue, M2.7 is likely going to fail a third time — we should escalate before paying.

**Files:**

| Path | Action |
|---|---|
| `tools/muscle/escalation.py` | **new** — `EscalationPolicy`, record format |
| `tools/muscle/migrations/_0015_escalations.py` | **new** — `escalations` table |
| `tools/muscle/code_review/verification_loop.py` | emit escalation on failure threshold |
| `tools/muscle/code_review/code_reviewer.py` | emit on schema-retry exhaustion |
| `tools/muscle/code_review/fix_generator.py` | emit on verification-failure threshold |
| `tests/unit/test_escalation.py` | **new** |

**`_0015_escalations.py` schema:**

```sql
CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reason TEXT NOT NULL,         -- 'schema_failure' | 'verification_failure' | 'low_confidence_route'
    source_module TEXT NOT NULL,  -- e.g. 'verification_loop'
    issue_summary TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    artifact_path TEXT,           -- .muscle/reports/escalations/<session>.md
    resolved INTEGER DEFAULT 0,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_escalations_session ON escalations(session_id);
CREATE INDEX IF NOT EXISTS idx_escalations_unresolved ON escalations(resolved, created_at);
```

**`escalation.py` skeleton:**

```python
"""Escalation policy — when to kick a problem to the host planner model."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)


@dataclass
class EscalationPolicy:
    max_m27_retries_per_issue: int = 2
    escalate_on_schema_failure_count: int = 3      # from B.2 retry counter
    escalate_on_verification_failure_count: int = 2
    escalate_on_route_confidence_below: float = 0.5


@dataclass
class EscalationRecord:
    session_id: str
    reason: str
    source_module: str
    issue_summary: str
    attempt_count: int
    artifact_path: Path | None = None


class EscalationRecorder:
    def __init__(self, project_path: str | Path, policy: EscalationPolicy | None = None) -> None:
        self._pm = ProjectMemory(str(project_path))
        self._project_path = Path(project_path)
        self.policy = policy or EscalationPolicy()

    def should_escalate(
        self,
        reason: str,
        attempt_count: int,
        route_confidence: float | None = None,
    ) -> bool:
        if reason == "schema_failure":
            return attempt_count >= self.policy.escalate_on_schema_failure_count
        if reason == "verification_failure":
            return attempt_count >= self.policy.escalate_on_verification_failure_count
        if reason == "low_confidence_route" and route_confidence is not None:
            return route_confidence < self.policy.escalate_on_route_confidence_below
        return False

    def emit(self, record: EscalationRecord) -> Path:
        """Persist to DB + write markdown artifact. Return artifact path."""
        artifact_dir = self._project_path / ".muscle" / "reports" / "escalations"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifact_dir / f"{record.session_id}.md"
        content = self._format_artifact(record)
        artifact.write_text(content)
        record.artifact_path = artifact

        with self._pm.connection() as conn:
            conn.execute(
                """INSERT INTO escalations
                   (session_id, created_at, reason, source_module,
                    issue_summary, attempt_count, artifact_path)
                   VALUES (?, datetime('now'), ?, ?, ?, ?, ?)""",
                (
                    record.session_id,
                    record.reason,
                    record.source_module,
                    record.issue_summary,
                    record.attempt_count,
                    str(artifact),
                ),
            )
        logger.info(f"Escalated: {record.reason} in {record.source_module}; artifact at {artifact}")
        return artifact

    def _format_artifact(self, record: EscalationRecord) -> str:
        return f"""# MUSCLE Escalation — {record.reason}

**Session:** {record.session_id}
**Source:** {record.source_module}
**Attempts:** {record.attempt_count}

## Issue
{record.issue_summary}

## Next step
The host model (Claude Code / Codex) should review this issue directly; MUSCLE's
M2.7 agents exhausted their retry budget. See `.muscle/reports/escalations/`
for related attempts.
"""
```

**Host-side surface — three concrete touchpoints (no "or" — ship all three):**

1. **Artifacts:** `.muscle/reports/escalations/<session_id>.md`, one file per escalation. Already implemented by `EscalationRecorder.emit()` above.
2. **CLI surface:** extend `muscle status` to list unresolved escalations: count + paths + age. Add a new column/section to the existing `muscle status` output in `cli.py`. Query: `SELECT * FROM escalations WHERE resolved = 0 ORDER BY created_at DESC`.
3. **Host-memory dynamic section:** append a one-line entry to the `### Frequent Mistakes` dynamic section in root `CLAUDE.md` when an escalation fires. Format: `- Unresolved escalation ({session_id}): {issue_summary} — see .muscle/reports/escalations/{session_id}.md`. Use the existing `claude_publisher.publish(mistake_corrections=...)` surface. Escalations auto-clear from this section when marked resolved (either by a follow-up review succeeding OR by `muscle escalation resolve <id>` — add this small CLI).

This makes escalations visible regardless of how the host model checks in: next-turn prompt, interactive `muscle status`, or reviewing the root memory file.

**Required tests:**
- `test_policy_threshold_schema_failure`: attempt 2 → no escalate; attempt 3 → escalate.
- `test_policy_threshold_verification_failure`.
- `test_policy_low_confidence`.
- `test_emit_creates_artifact_and_db_row`.
- `test_emit_idempotent_on_same_session_reason`: two emits with same keys produce one row or logged warning (pick one and test it).

**Acceptance metric:** synthetic test with deliberately hard issue fires exactly one escalation record (not three), and the markdown artifact contains the issue summary + the 2 failed M2.7 attempts + verification output.

**Delegation hint:** planner for policy defaults + prefix format; M2.7 for threshold-check code, DB plumbing, markdown formatter.

---

### 6.6 Phase B.5 — Distilled context packets: `muscle pack` [P1, Week 5]

**Gap it closes:** `optimization/context_budgeter.py` picks issue-centered code windows per subtask. Reuse across subtasks is nonexistent. A persisted, content-addressed "pack" built once per delegation is the single biggest per-session token save.

**Files:**

| Path | Action |
|---|---|
| `tools/muscle/packs.py` | **new** — `Pack`, `PackBuilder`, `PackStore` |
| `tools/muscle/cli.py` | add `muscle pack --task "..." --scope <path> --out <path>`; accept `--pack <id>` on existing commands |
| `tools/muscle/code_review/review_controller.py` | accept `--pack` and skip context budgeting if packet provided |
| `tools/muscle/migrations/_0016_packs.py` | **new** — `packs` table (metadata only; pack bodies live on disk) |
| `tools/muscle/plugin/commands/pack.md` | **new** — `/muscle:pack` |
| `tests/unit/test_packs.py` | **new** |

**Pack contents (markdown format, content-addressed):**

```
# Pack <id>

## Task
<user-provided description>

## Acceptance criteria
<from host planner if provided>

## Scope
<files included, sorted>

## Type signatures
<extracted relevant types>

## Code excerpts
<from context_budgeter — issue-centered windows>

## Conventions
<relevant rules from project_memory.db>

## Manifest
Consumed by: /muscle:review, /muscle:fix, /muscle:verify
Created: <ISO-8601>
Content hash: sha256(...)
```

**`packs.py` — full module skeleton:**

```python
"""Content-addressed task-context packs for reuse across MUSCLE subtasks."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .optimization.context_budgeter import ContextBudgeter
from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)

PACK_CONSUMERS = "/muscle:review, /muscle:fix, /muscle:verify"


@dataclass
class Pack:
    id: str                     # sha256 of content (first 16 chars used as filename)
    path: Path                  # .muscle/packs/<id>.md
    task: str
    scope: list[Path]
    acceptance: str
    content_sha: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PackBuilder:
    def __init__(self, project_path: Path, context_budgeter: ContextBudgeter) -> None:
        self._project = Path(project_path)
        self._budgeter = context_budgeter
        self._pm = ProjectMemory(str(project_path))

    def build(self, task: str, scope: Path, acceptance: str = "") -> Pack:
        """Assemble a pack. Deterministic: same inputs → same pack id.

        Steps:
        1. Collect files in scope (recursive if dir, single if file).
        2. Ask context_budgeter for issue-centered windows across those files.
        3. Extract type signatures (top-level def/class + signature lines).
        4. Pull relevant rules from project_memory.db matching scope paths.
        5. Assemble markdown body; compute content hash; write to disk.
        """
        scope_files = self._collect_scope_files(scope)
        excerpts = self._budgeter.select_windows(task=task, paths=scope_files)
        signatures = self._extract_signatures(scope_files)
        rules = self._relevant_rules(scope_files)

        body = self._render_markdown(
            task=task,
            acceptance=acceptance,
            scope_files=scope_files,
            excerpts=excerpts,
            signatures=signatures,
            rules=rules,
        )
        content_sha = hashlib.sha256(body.encode()).hexdigest()
        pack_id = content_sha[:16]

        packs_dir = self._project / ".muscle" / "packs"
        packs_dir.mkdir(parents=True, exist_ok=True)
        path = packs_dir / f"{pack_id}.md"
        path.write_text(body)

        pack = Pack(
            id=pack_id,
            path=path,
            task=task,
            scope=scope_files,
            acceptance=acceptance,
            content_sha=content_sha,
        )
        PackStore(self._project).put(pack)
        return pack

    def _collect_scope_files(self, scope: Path) -> list[Path]:
        if scope.is_file():
            return [scope]
        return sorted(p for p in scope.rglob("*") if p.is_file() and self._include(p))

    @staticmethod
    def _include(path: Path) -> bool:
        # Skip binary / generated dirs. Keep aligned with context_budgeter.
        skip_parts = {".git", ".muscle", "__pycache__", ".venv", "node_modules", "dist", "build"}
        return not any(part in skip_parts for part in path.parts)

    def _extract_signatures(self, files: list[Path]) -> dict[str, list[str]]:
        """Return {relative_path: [def/class signature lines]} for Python files."""
        import re
        sig_re = re.compile(r"^(async\s+def|def|class)\s+[\w_]+.*:", re.MULTILINE)
        out: dict[str, list[str]] = {}
        for f in files:
            if f.suffix != ".py":
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            matches = [m.group(0).rstrip() for m in sig_re.finditer(text)]
            if matches:
                out[str(f.relative_to(self._project))] = matches
        return out

    def _relevant_rules(self, files: list[Path]) -> list[str]:
        """Query project_memory.db for rules whose scope matches any scope file."""
        # Reference existing schema; adjust if project_memory.db uses different table/column names.
        paths = [str(f.relative_to(self._project)) for f in files]
        if not paths:
            return []
        # Bridge pattern pending [PM-01]:
        import sqlite3
        db = self._project / ".muscle" / "project_memory.db"
        if not db.exists():
            return []
        with sqlite3.connect(db) as conn:
            placeholders = ",".join("?" * len(paths))
            rows = conn.execute(
                f"SELECT text FROM rules WHERE scope_path IN ({placeholders}) "
                "AND promoted = 1 ORDER BY score DESC LIMIT 20",
                paths,
            ).fetchall()
        return [r[0] for r in rows]

    def _render_markdown(
        self,
        task: str,
        acceptance: str,
        scope_files: list[Path],
        excerpts: dict[str, str],
        signatures: dict[str, list[str]],
        rules: list[str],
    ) -> str:
        lines = [
            f"# Pack — {task[:80]}",
            "",
            "## Task",
            task,
            "",
        ]
        if acceptance:
            lines.extend(["## Acceptance criteria", acceptance, ""])
        lines.append("## Scope")
        for f in scope_files:
            lines.append(f"- `{f.relative_to(self._project)}`")
        lines.append("")

        if signatures:
            lines.append("## Type signatures")
            for path, sigs in sorted(signatures.items()):
                lines.append(f"### `{path}`")
                lines.extend(f"- `{s}`" for s in sigs)
                lines.append("")

        if excerpts:
            lines.append("## Code excerpts")
            for path, snippet in sorted(excerpts.items()):
                lines.append(f"### `{path}`")
                lines.append("```")
                lines.append(snippet)
                lines.append("```")
                lines.append("")

        if rules:
            lines.append("## Conventions")
            lines.extend(f"- {r}" for r in rules)
            lines.append("")

        lines.extend([
            "## Manifest",
            f"Consumed by: {PACK_CONSUMERS}",
            f"Created: {datetime.now(timezone.utc).isoformat()}",
        ])
        return "\n".join(lines) + "\n"


class PackStore:
    """Metadata-only store. Pack bodies live on disk; this tracks ids + paths."""

    def __init__(self, project_path: Path) -> None:
        self._project = Path(project_path)
        self._dir = self._project / ".muscle" / "packs"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pm = ProjectMemory(str(project_path))

    def get(self, pack_id: str) -> Pack | None:
        path = self._dir / f"{pack_id}.md"
        if not path.exists():
            return None
        # Rehydrate from DB metadata if available; otherwise minimal reconstruction.
        return Pack(
            id=pack_id,
            path=path,
            task="",           # filled from DB if caller needs
            scope=[],
            acceptance="",
            content_sha=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def put(self, pack: Pack) -> None:
        """Persist metadata to packs table (see _0016_packs migration)."""
        import sqlite3
        db = self._project / ".muscle" / "project_memory.db"
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO packs (id, path, task, content_sha, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    pack.id,
                    str(pack.path),
                    pack.task,
                    pack.content_sha,
                    pack.created_at.isoformat(),
                ),
            )

    def list(self) -> list[Pack]:
        return [self.get(p.stem) for p in sorted(self._dir.glob("*.md")) if self.get(p.stem)]

    def gc(self, older_than: timedelta) -> int:
        cutoff = datetime.now(timezone.utc) - older_than
        removed = 0
        import sqlite3
        db = self._project / ".muscle" / "project_memory.db"
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT id, path FROM packs WHERE created_at < ?", (cutoff.isoformat(),)
            ).fetchall()
            for pack_id, path in rows:
                try:
                    Path(path).unlink()
                    removed += 1
                except OSError:
                    pass
                conn.execute("DELETE FROM packs WHERE id = ?", (pack_id,))
        return removed
```

**Migration `_0016_packs.py` schema:**

```sql
CREATE TABLE IF NOT EXISTS packs (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    task TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_packs_created ON packs(created_at);
```

**CLI integration in `cli.py`** — add:

```python
@cli.command(name="pack")
@click.option("--task", required=True)
@click.option("--scope", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--acceptance", default="")
@click.option("--out", type=click.Path(path_type=Path), default=None)
def pack_cmd(task: str, scope: Path, acceptance: str, out: Path | None) -> None:
    """Build a content-addressed context pack for reuse across MUSCLE subtasks."""
    from tools.muscle.packs import PackBuilder
    from tools.muscle.optimization.context_budgeter import ContextBudgeter

    builder = PackBuilder(Path.cwd(), ContextBudgeter())
    pack = builder.build(task=task, scope=scope, acceptance=acceptance)
    click.echo(f"Pack id: {pack.id}")
    click.echo(f"Pack path: {pack.path}")
    if out:
        Path(out).write_text(pack.path.read_text())
        click.echo(f"Copied to: {out}")
```

And extend `muscle review` to accept `--pack <id>`: look up the pack, pass `pack.id` to `m27_client.chat_structured` cache-key computation (via B.3's `build_key(..., pack_id=pack.id)`). When `--pack` is present, context-budgeter is skipped entirely; the pack body is the context.

**Integration with B.3 (cache):** response cache keys include `pack_id` when a pack is in use, so identical pack + identical task → cache hit.

**Required tests:**
- `test_build_pack_produces_content_hash`.
- `test_identical_inputs_produce_identical_pack_id`.
- `test_pack_reuse_across_subtasks`: build once, consume from 3 different commands; assert builder called once.
- `test_gc_removes_old_packs`.
- `test_pack_integrates_with_response_cache`: verify cache key includes pack_id.

**Acceptance metric:** on a representative 10-subtask delegation chain, total input tokens with `--pack` reuse drop ≥30% vs. fresh-budget-per-call.

**Delegation hint:** planner for the pack schema; M2.7 for builder + cache plumbing + tests.

---

## 7. Phase C — Pre-release hardening (parallel, Week 6+)

Burn down open findings from `docs/REMAINING_TODOS.md`. This phase can interleave with Phase B but **must be complete before tagging a release**.

### 7.1 🔴 High-severity (ship-blocking) — address first

Dispatch each as an isolated agent task using the handoff format at the bottom of `docs/REMAINING_TODOS.md`. All acceptance criteria specify a regression test.

| Finding | File | Fix direction |
|---|---|---|
| `[LC-01]` Budget arithmetic goes negative | `loop_controller.py:626-631` | Clamp `remaining_tokens` at 0; emit one-shot overspend event. |
| `[LC-02]` `resume_context` mutated without lock | `loop_controller.py:511-534` | Deep-copy on entry OR require exclusive ownership via `_running: bool` with assert. |
| `[CG-02]` Streaming accumulates full response in RAM | `code_generator.py:429-437` | Track deltas; stream to disk/parser; keep rolling 16 KB window for fence detection. |
| `[FG-02]` `.bak` cleanup not exception-safe | `fix_generator.py:207-227` | Context manager; startup sweep for stale `*.muscle.bak`. |
| `[RC-02]` Worktree cleanup swallows exceptions | `review_controller.py:289-291` | Counter + `muscle doctor --clean-worktrees`. |
| `[RC-03]` `fix_lock` scope regression test | `review_controller.py:696-739` | Force each exception path inside locked region; assert lock released. |
| `[TU-02]` TUI dead-code fallback silently renders fake data | `tui/views.py:65-166` | Replace with explicit "data unavailable" panel + underlying exception + retry keybind. |

### 7.2 🟠 Medium — ship alongside 🔴 work or in first hotfix

Curated highlights (full list in `docs/REMAINING_TODOS.md`):

- `[M27-05]` narrow bare `except Exception: break` in `m27_client` retry loop.
- `[LC-04]` / `[LC-05]` signal handler + `LoopStats.start_time` `default_factory` audit.
- `[CG-04]` / `[CG-05]` fenced-block exception + UTF-8 fallback in `code_generator`.
- `[SM-03]` restrict session-id sanitizer to ASCII alnum + `_-`.
- `[BM-02]` validate budget-file values (non-neg int + type check).
- `[CLI-02]` / `[CLI-03]` / `[TY-01]` move `MAX_TASK_LENGTH` / `MAX_TIMEOUT_SECONDS` into `RunConfig.__post_init__`; require HTTPS for webhooks.
- `[CR-05]` thread `max_issues_per_batch` through `ReviewConfig`.
- `[FG-04]` implement or delete `fix_generator.verify_fix()`.
- `[SH-04]` assert `_in_progress_jobs` lock contract; concurrent-start test.
- `[PL-02]` / `[PL-03]` prune plugin docs to live CLI surface; decide "filesystem-is-truth" vs "manifest-is-truth" (recommend filesystem).
- `[AD-token-tests]` new `tests/unit/test_http_utils.py` with `redact_secrets` table tests for Bearer / `ghp_*` / `glpat_*` / `Authorization:` / `token=...`.
- `[PM-01]` `@contextmanager def _conn(self)` in `project_memory.py`; migrate all ~15 call sites.
- `[MG-01]` / `[MG-02]` uniform migration template `version check → run → version insert` in `BEGIN; … COMMIT;`; parametrized double-apply test.

### 7.3 🟡 Low — post-release

`[DOC-03]` phase labels in `MUSCLE_PLAN.md` (partly moot; this roadmap supersedes). `[PKG-02]` / `[PKG-03]` `uv.lock` hygiene + mypy pinning. `[CHK-01]` `muscle check --target <file>` CLI UX fix. `[TEST-09]` TUI test environment mock (skip in CI). `[TEST-10]` relatedness-summary extend-or-update-tests decision.

### 7.4 Test gaps (all 🟠)

- `[TEST-01]` shadow-worker crash/heartbeat tests (kill mid-job, assert orphaned marking).
- `[TEST-02]` fix-verification multi-language rollback tests.
- `[TEST-03]` concurrent-review stress.
- `[TEST-04]` migration double-apply (covered in §7.2 alongside `[MG-02]`).
- `[TEST-05]` rewrite `tests/integration/test_shadow_nightly.py` against current `ShadowBroker` (6 stale `SHADOW_JOBS_FILE` refs).
- `[TEST-06]` / `[TEST-07]` / `[TEST-08]` isolate fixtures from real `~/.muscle/` state.

---

## 8. Phase D — Deferred (post-release, gated)

### 8.1 Phase A.2 — Foresight preflight + short-term memory (from `Forsight-plan.md`)

**Gate:** ship only after Phase A delegation overhaul is stable in production. Foresight's temporary root-`CLAUDE.md` injection must use **distinct markers** (`MUSCLE_FORESIGHT_START/END`, not `MUSCLE_PUBLISHED_*`) and `host_memory_optimizer` must refuse to rewrite while a live Foresight region is present.

**Tasks (from the handoff):**

- `foresight_manager.py`: intake, candidate retrieval, bounded M2.7 ranking call with fallback, temporary root-CLAUDE.md injection + cleanup, task-tree reference counting.
- `short_term_memory.py`: `.muscle/MUSCLE_SHORT_TERM.md`, 50-line cap, dedupe, freshness.
- CLI group `muscle foresight run|enable|disable|status|refresh-short-term`.
- TUI config fields: `foresight_enabled`, `foresight_experimental`, `foresight_use_root_claude`, `foresight_use_shared_short_term`.
- `plugin/commands/foresight.md`.
- **Hard invariant:** Foresight never promotes long-term rules. Enforce with a test.

**Verification:** one-shot and session-mode each inject distinct marker regions; cleanup runs on task-tree completion; short-term file stays capped; invariant test passes.

### 8.2 Phase A.3 — Consensus review (from `GroupTink-collab.md`)

**Gate:** defer until Phase B.6 (observability) has produced ≥1 month of data showing cost-per-review trend. Consensus is a net cost increase per invocation; we only ship it once we can measure "expensive mistakes avoided" against "consensus tokens spent."

**Tasks:**
- `muscle consensus` command: `--target`, `--mode {supervisor|consensus|gate}`, `--method {auto|fan_out_fan_in|debate|...}`, `--profile`, `--models`, `--apply-memory`, `--output`.
- `muscle review --backend {local|supervisor|consensus|hybrid}` — hybrid runs MUSCLE local first then escalates flagged issues.
- Selective memory publishing: only important/repeated lessons reach root CLAUDE.md from consensus.
- Plugin commands + agents.

**Verification:** hybrid review on fixture project escalates only low-confidence issues; escalation fires on <10% of findings by default; balanced credit strategy stays within per-review budget ceiling.

### 8.3 Phase B.7 — Cross-project pack library

**Gate:** once B.5 has produced a library's worth of reusable packs (est. 20+ scrubbed packs across projects).

**Tasks:**
- Extend `transferable_lesson_scrubber.py` to scrub packs.
- Store scrubbed packs in `~/.muscle/pack-library/`.
- Add `muscle pack search --task "..."`.
- Respect project-first rule: library packs are suggestions, never auto-imported.

---

## 9. Parallel hygiene track

Continuously throughout Phases A–C:

- **Keep CLAUDE.md, PROJECT_INDEX.md, docs/architecture.md in sync with code.** After each phase, `grep -rn "Opus 4.7\|AGENTS.md\|MiniMax M2.7" CLAUDE.md PROJECT_INDEX.md docs/architecture.md MUSCLE_ROADMAP.md` to confirm references are current.
- **Never introduce new mypy or pytest regressions.** Compare against baseline after every change.
- **Every new module has a unit test file in `tests/unit/` named `test_<module>.py`**.
- **Every new migration has a double-apply test** (see `[MG-02]` in §7).
- **Every new CLI subcommand is advertised in both `cli.py` (Click) and `plugin/.claude-plugin/plugin.json`** (filesystem truth rule per `[PL-03]` recommendation).
- **Every M2.7 call goes through `chat_structured` after B.2 lands** (no raw parsing in new code).
- **Every CLI entry point instruments `DelegationMetrics.record(...)` after B.6 lands**.

---

## 10. Definition of Done (release gate)

MUSCLE is ready for release when **all ten** items are simultaneously true:

1. **Phase A (delegation overhaul) 10/10 verification items pass** (see `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md:1083-1098`).
2. **Phase B.1–B.6 ship** with individual acceptance metrics met.
3. **Phase C 🔴 High-severity items all closed** with regression tests.
4. **`muscle cost --delegation-report`** on a representative project shows:
   - M2.7 absorbs **≥70%** of bulk-execution tokens (multi-file reviews, test sweeps, fix generation).
   - Cache hit rate **≥40%** on second-pass runs.
   - Escalation rate **<15%** of total delegations.
   - Estimated host tokens avoided > M2.7 tokens spent × 5 (the cost ratio from Phase A).
5. **`muscle long-eval benchmark --enforce-gates`** passes — overlay / pinned / dynamic behavior does not regress baseline.
6. **Quality gates** (`mypy`, `ruff check`, `ruff format --check`, `pytest`) show no new regressions vs. 2026-04-17 baseline (4 pre-existing mypy errors, 1 pre-existing pytest env failure, all cataloged).
7. **Pre-release smoke tests** from `docs/REMAINING_TODOS.md:240-255` pass:
   - `muscle run --task "hello world script"` — no dangling `.bak`, SIGTERM-safe, no negative `remaining_tokens`.
   - `muscle review --path <sample>` — committee dedup works, auto-fix blocks on syntax-invalid LLM output, handoff markdown passes CommonMark.
   - Three concurrent `muscle review` calls against same project — no deadlock; no orphaned `running` jobs after `SIGKILL` (covers `[TEST-01]`).
   - Plugin lint: every `/muscle:*` manifest entry has a matching file under `commands/` (covers `[PL-03]`).
8. **Root `CLAUDE.md`, `PROJECT_INDEX.md`, `docs/architecture.md`, `MUSCLE_ROADMAP.md`** accurately describe shipped posture. No stale "host-model detection" or "Anthropic fallback" language survives.
9. **Plugin manifest** (`tools/muscle/plugin/.claude-plugin/plugin.json`) lists every shipped slash command; filesystem and manifest agree.
10. **One full review cycle on a real external project** completes end-to-end: Opus 4.7 plans, MUSCLE executes via `muscle review` + M2.7, findings appear in root `CLAUDE.md` + `AGENTS.md` inside pinned-and-dynamic regions, `muscle cost --delegation-report` shows the expected token-shift ratio, no escalations for straightforward issues, rescue + verification agents invoked correctly for complex ones.

When all ten are simultaneously true, tag `v0.2.0` and open a release PR with the delegation report + benchmark results attached.

---

## 11. Execution Model Guidance — GLM 5.1 as host, M2.7 via MUSCLE

**Recommendation:** Use **GLM 5.1 as the Claude Code host** (planner / synthesizer / decision-maker) and delegate mechanical sub-tasks to **MiniMax M2.7 via MUSCLE itself** through the plan-then-hand-off architecture this roadmap is building. This dogfoods the whole plan: GLM plans Phase A in Claude Code, hands execution of Phase A.1.1 (template constants), A.1.2 (memory manager seed), A.1.5 (manifest), A.1.6 (markdown edits), A.1.7 (helper extraction), A.1.9 (tests) to M2.7 via `/muscle:route` → `/muscle:review` / direct M2.7 code-generation calls. GLM handles A.1.3 (publisher refactor) and A.1.4 (optimizer module) itself.

**Why GLM 5.1 over M2.7 for the host role:**
- GLM 5.1 has stronger multi-file synthesis and architectural judgment than M2.7. Phase A.1.3 (publisher refactor with new import graph, multi-target loop, idempotent rebuild) needs that.
- Using M2.7 to build M2.7's own delegation surface is recursive and risky: if M2.7 misdesigns its own cost-saving infrastructure, the failure is silent because M2.7 is also the diagnostician. GLM is the outside auditor.
- GLM 5.1's context window comfortably holds the 1,119-line `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md` plus referenced source files. M2.7's context is tighter.

**Why keep M2.7 for the execution role:**
- Validates the plan-then-hand-off architecture in practice before we trust it in production.
- M2.7 is trained on the same kind of code-review mechanics the roadmap delegates to it.
- Cost: M2.7 is 5–10× cheaper than GLM on output tokens. For bulk test-writing and schema work, that matters.

### 11.1 Coding conventions (for both models — M2.7 tends to regress on these)

Every new module in this roadmap **must**:

1. Start with `from __future__ import annotations` — enables 3.10+ union syntax (`int | None`) on older type-checkers.
2. Use `pathlib.Path`, not `os.path.join`. Use `Path(...).read_text()` / `.write_text(...)`, not `open(...).read()`.
3. Use context managers for file and DB I/O (`with open(...) as f:`, `with sqlite3.connect(...) as conn:`). Never bare `connect()` or `open()`.
4. Use `int | None` union syntax, not `Optional[int]` or `Union[int, None]`.
5. Use `@dataclass` for internal types (input to/output from functions within MUSCLE). Use Pydantic v2 models **only** at M2.7 response boundaries (`structured_io.py`).
6. Include a `logger = logging.getLogger(__name__)` at the top. Log at `info` for control flow, `warning` for recoverable failures, `error` for unrecoverable, `debug` for noisy detail.
7. All public functions have type hints on every parameter and the return. Mypy strict is on.
8. All new modules have a `tests/unit/test_<module_name>.py` file with at minimum: one happy-path test, one edge-case test, one error-path test.
9. `from ..other_module import X` (explicit relative), not `from tools.muscle.other_module import X`. Except in CLI entry points (`cli.py` uses absolute imports for click subcommand registration).
10. Module-top constants are UPPERCASE_WITH_UNDERSCORES. No magic numbers inside function bodies — lift to a module-top constant with a brief comment.

### 11.2 GLM 5.1–specific guidance (host role)

- GLM sometimes emits `from typing import Optional, Union, List, Dict`. Reject and rewrite to PEP 604 union syntax + builtins (`list`, `dict`).
- GLM sometimes uses `print()` for diagnostic output. Force `logger.info(...)` / `logger.warning(...)` instead.
- GLM occasionally falls back to `os.path.join(...)`. Rewrite as `Path(a) / b`.
- GLM defaults to Pydantic v1 syntax if unprompted (`class Config:`, `from pydantic import BaseModel`). Phase B.2 explicitly pins Pydantic v2 — enforce: `model_json_schema()`, `model_validate()`, `Field(ge=...)`, `Literal`.
- When GLM proposes adding a new abstraction, ask "does this fit into an existing module?" first. GLM's default is to create new modules; in this codebase, prefer extending existing ones.
- GLM reads the full roadmap well — give it the whole file as context, not just the current phase.

### 11.3 M2.7-specific guidance (execution role)

- M2.7 context is tighter. For each delegated sub-task, **quote the existing file top** (imports + first 20 lines) inline in the prompt rather than expecting M2.7 to retrieve it. Example: don't say "add a method to `M27Client`"; say "here's the top of `m27_client.py`: [quoted]; add this method after the existing `chat` method."
- M2.7 is stronger at schema/template generation than at multi-file refactors. Delegate: template constants, test scaffolds from a spec, migration SQL, marker-string edits, single-function additions. Retain: refactor of `_update_published_section`, new module design, any judgment call.
- Break Phase B.1 into three sequential M2.7 calls: (1) "create `routing.py` module body," (2) "add Click subcommand to `cli.py`," (3) "write `tests/unit/test_routing.py` from this spec." Do not ask M2.7 to do all three in one call.
- Bundle 2–3 Phase C hardening findings per M2.7 task (e.g., `[M27-05]` + `[LC-04]` + `[LC-05]` as one task since they're all in one or two files). One-per-task has too much orchestration overhead.
- M2.7 occasionally regresses to f-strings inside SQL literals (injection risk). Every SQL edit goes through a second pass: "does every user-provided value use a parameterized query placeholder (`?`)? If not, fix."
- When M2.7 output fails schema validation twice (per B.2's `chat_structured` retry), escalate to GLM — don't retry a third time.

### 11.4 Task sizing rules (for either model)

| Task class | Appropriate model | Max scope per call |
|---|---|---|
| Module skeleton from verbatim spec | M2.7 | 1 file, ≤300 lines |
| Test file from spec | M2.7 | 1 file, 5–8 tests |
| Migration SQL | M2.7 | 1 migration file |
| Single-file refactor with before/after | M2.7 | 1 file, ≤5 edits |
| Multi-file refactor (e.g., Phase B.2 parser migration) | GLM | 4 files, coordinated changes |
| New module design (e.g., routing, packs) | GLM | 1 module, 1 test file |
| Publisher refactor (A.1.3) | GLM | 1 file, 4 sub-edits |
| Hardening finding (🔴 High) | GLM | 1 finding per call |
| Hardening finding (🟠 Medium) | M2.7 | 2–3 findings per call |
| Documentation edit | M2.7 | no limit |
| CLI subcommand addition | Either | 1 command per call |

### 11.5 Verification discipline under two-model workflow

After every M2.7-executed task, **GLM must review**:
1. Diff the change with `git diff`.
2. Run the relevant quality-gate subset (e.g., after a module add: `uv run mypy tools/muscle/<module>.py` + `uv run ruff check tools/muscle/<module>.py` + `uv run pytest tests/unit/test_<module>.py`).
3. Confirm coding conventions from §11.1 are followed.
4. Only then continue to the next task.

This is MUSCLE's verification loop (`verification_loop.py`) applied at the human-visible level. Don't skip.

---

## 12. Plan file map — what this document supersedes vs. references

| File | Role going forward |
|---|---|
| `MUSCLE_ROADMAP.md` (this file) | **Living plan. Single source of truth for order, priorities, DoD.** |
| `PLAN_OPUS_4_7_DELEGATION_OVERHAUL.md` | **Implementation reference for Phase A.** Keep as-is; Sonnet executes from it verbatim. |
| `MUSCLE_HANDOFF_DELEGATION_AND_COST_SAVINGS.md` | Absorbed into this roadmap. Keep as historical context; planning role ends here. |
| `MUSCLE_PLAN.md` | Superseded as planning document. Add a pointer header: *"Active roadmap is `MUSCLE_ROADMAP.md`; this file retained for historical phase descriptions."* |
| `docs/REMAINING_TODOS.md` | Active audit register. Keep updating as findings close. Roadmap §7 sequences its 🔴 items; detail stays in the audit file. |
| `Forsight-plan.md` | Deferred to Phase D.1. Keep; reference but don't execute until gate opens. |
| `GroupTink-collab.md` | Deferred to Phase D.2. Same. |
| `docs/project-first-growth-model-pack-roadmap.md` | Largely shipped. Keep for its W7 (release hardening) detail; cross-reference from §7 hardening items. |
| `docs/architecture.md` | Authoritative design doc. Keep updated per §9 hygiene rules. |
| `CLAUDE.md` | Maintainer guide. Already refreshed 2026-04-17. Keep updated per §9. |
| `PROJECT_INDEX.md` | Navigational map. Keep updated per §9. |
| `README.md` | Public-facing overview. Update when Phase A ships with a note about delegation. |

---

## 13. Change log

| Date | Change |
|---|---|
| 2026-04-17 | Initial consolidation. Absorbs `MUSCLE_HANDOFF_DELEGATION_AND_COST_SAVINGS.md`. Sequences Phase A (delegation overhaul), Phase B.1–B.6 (cost-savings features), Phase C (pre-release hardening), Phase D (deferred). |
| 2026-04-17 | Hardening pass for GLM 5.1 / MiniMax M2.7 execution. Added §6.2.bis (Pydantic v2 pin), inlined missing implementations (B.1 cache helpers, B.2 `chat_structured`, B.5 `PackBuilder`), added `pack_id` to B.3 cache key, explicit host-side surface for B.4 (3 touchpoints), `[PM-01]` prerequisite + bridge pattern for B.6, and new §11 Execution Model Guidance with per-model coding conventions, task-sizing rules, and the GLM-host + M2.7-via-MUSCLE recommendation. |

---

*This is a living document. Update §3 Execution Timeline when priorities shift; update §10 Definition of Done when ship criteria firm up; update §12 with every material revision.*
