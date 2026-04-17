"""Records and reports cost-delegation events for muscle cost delegation-report."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Average tokens per equivalent task on the host model.  Clearly labeled as
# "estimated" in every report surface — these are NOT measured.
HOST_TOKEN_ESTIMATES: dict[str, int] = {
    "claude-opus-4-7": 8000,
    "claude-sonnet-4-6": 5000,
    "codex-default": 8000,
}

DEFAULT_HOST_MODEL = "claude-opus-4-7"


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
        self._project_path = Path(project_path)
        self._db_path = self._project_path / ".muscle" / "project_memory.db"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def record(self, event: DelegationEvent) -> None:
        """Insert one event.  Idempotency not enforced — callers own session dedup."""
        if not self._db_path.exists():
            logger.warning("No project_memory.db at %s — skipping delegation event", self._db_path)
            return
        try:
            with self._connect() as conn:
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
        except sqlite3.OperationalError:
            logger.debug("delegation_events table missing — migration may not have run")

    def report(
        self,
        since: timedelta = timedelta(days=7),
        host_model: str = DEFAULT_HOST_MODEL,
    ) -> DelegationReport:
        """Build a DelegationReport covering the trailing *since* window."""
        cutoff = datetime.now(timezone.utc) - since
        if not self._db_path.exists():
            return DelegationReport(since=cutoff, total_events=0)

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT task_tier, m27_tokens_in, m27_tokens_out, m27_usd_cents,
                          cache_hits, cache_tokens_saved, escalations_emitted
                   FROM delegation_events
                   WHERE created_at >= ?""",
                    (cutoff.isoformat(),),
                ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("delegation_events table missing — returning empty report")
            return DelegationReport(since=cutoff, total_events=0)

        rpt = DelegationReport(since=cutoff, total_events=len(rows))
        if not rows:
            return rpt

        for r in rows:
            tier = r[0] or "unknown"
            rpt.m27_tokens_by_tier[tier] = rpt.m27_tokens_by_tier.get(tier, 0) + r[1] + r[2]
            rpt.m27_usd_cents += r[3]
            rpt.cache_tokens_saved += r[5]

        total = rpt.total_events
        rpt.cache_hit_rate = sum(r[4] for r in rows) / total if total else 0.0
        total_escalations = sum(1 for r in rows if r[6] > 0)
        rpt.escalation_rate = total_escalations / total if total else 0.0

        avg = HOST_TOKEN_ESTIMATES.get(host_model, 8000)
        rpt.estimated_host_tokens_avoided = total * avg
        return rpt

    def format_text(self, rpt: DelegationReport) -> str:
        """Human-readable report for `muscle cost delegation-report`."""
        lines = [
            f"=== MUSCLE Delegation Report (since {rpt.since.date()}) ===",
            f"Total delegated tasks: {rpt.total_events}",
            "",
            "M2.7 tokens by tier:",
        ]
        for tier, tokens in sorted(rpt.m27_tokens_by_tier.items()):
            lines.append(f"  {tier:20s} {tokens:>10,} tokens")
        lines.extend(
            [
                "",
                f"M2.7 spend:                  ${rpt.m27_usd_cents / 100:.2f}",
                f"Cache hit rate:              {rpt.cache_hit_rate:.1%}",
                f"Cache tokens saved:          {rpt.cache_tokens_saved:,}",
                f"Escalation rate:             {rpt.escalation_rate:.1%}",
                f"Estimated host tokens        {rpt.estimated_host_tokens_avoided:,}",
                "  avoided (NOT measured):",
            ]
        )
        return "\n".join(lines)

    def format_json(self, rpt: DelegationReport) -> str:
        """Machine-readable report."""
        return json.dumps(
            {
                "since": rpt.since.isoformat(),
                "total_events": rpt.total_events,
                "m27_tokens_by_tier": rpt.m27_tokens_by_tier,
                "m27_usd_cents": rpt.m27_usd_cents,
                "cache_hit_rate": rpt.cache_hit_rate,
                "cache_tokens_saved": rpt.cache_tokens_saved,
                "escalation_rate": rpt.escalation_rate,
                "estimated_host_tokens_avoided": rpt.estimated_host_tokens_avoided,
            },
            indent=2,
        )
