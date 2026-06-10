"""Records and reports cost-delegation events for muscle cost delegation-report."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .cost_optimizer import (
    DEFAULT_PRICING_MODEL,
    HOST_MODEL_PRICING,
    estimate_host_request_cost,
    estimate_request_cost,
)

logger = logging.getLogger(__name__)


def resolve_m27_token_split(
    input_tokens: int, output_tokens: int, combined_total: int
) -> tuple[int, int]:
    """Resolve the real (input, output) M3 token split for a delegation event.

    The runtime now threads the measured per-call ``input_tokens`` /
    ``output_tokens`` split through every layer, so the common case returns those
    values verbatim. The ``combined_total`` argument is the legacy-data fallback:
    sessions resumed from older persisted state expose only a combined token
    count (``total``) with both split fields at 0. Any remainder of
    ``combined_total`` not covered by ``input_tokens + output_tokens`` is
    attributed to input so resumed legacy sessions are still priced rather than
    silently dropping their spend. Negative inputs are clamped to 0.
    """
    tokens_in = max(0, input_tokens)
    tokens_out = max(0, output_tokens)
    remainder = max(0, combined_total) - (tokens_in + tokens_out)
    if remainder > 0:
        tokens_in += remainder
    return tokens_in, tokens_out


def estimate_m27_cents(model: str | None, tokens_in: int, tokens_out: int) -> int:
    """Estimate MUSCLE's M3 spend for a delegation event, in whole USD cents."""
    cost = estimate_request_cost(model or DEFAULT_PRICING_MODEL, tokens_in, tokens_out)
    return round(cost * 100)


# Average tokens per equivalent task on the host model.  Clearly labeled as
# "estimated" in every report surface — these are NOT measured.
HOST_TOKEN_ESTIMATES: dict[str, int] = {
    "claude-fable-5": 8000,
    "claude-opus-4-8": 8000,
    "claude-opus-4-7": 8000,
    "claude-sonnet-4-6": 5000,
    "codex-default": 8000,
}

DEFAULT_HOST_MODEL = "claude-fable-5"

# Assumed share of avoided host tokens that would have been *output* tokens.
# Output bills 5x input on Claude hosts, so the split materially affects the
# dollar estimate; like HOST_TOKEN_ESTIMATES this is an assumption, not measured.
HOST_AVOIDED_OUTPUT_SHARE = 0.25


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
    metadata: dict[str, object] = field(default_factory=dict)


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
    route_breakdown: dict[str, dict[str, float | int]] = field(default_factory=dict)
    host_model: str = DEFAULT_HOST_MODEL
    estimated_host_usd_avoided: float = 0.0
    estimated_net_savings_usd: float = 0.0


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
                        pack_id, pack_reused, metadata_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        json.dumps(event.metadata, sort_keys=True),
                    ),
                )
        except sqlite3.OperationalError:
            logger.debug("delegation_events table missing — migration may not have run")

    def report(
        self,
        since: timedelta = timedelta(days=7),
        host_model: str = DEFAULT_HOST_MODEL,
    ) -> DelegationReport:
        """Build a DelegationReport covering the trailing *since* window.

        Raises ``ValueError`` for a host model with no pricing entry — a silent
        fallback here would misprice every savings line in the report.
        """
        if host_model not in HOST_MODEL_PRICING:
            known = ", ".join(sorted(HOST_MODEL_PRICING))
            raise ValueError(f"unknown host model {host_model!r}; known: {known}")
        cutoff = datetime.now(timezone.utc) - since
        if not self._db_path.exists():
            return DelegationReport(since=cutoff, total_events=0, host_model=host_model)

        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT task_tier, m27_tokens_in, m27_tokens_out, m27_usd_cents,
                          cache_hits, cache_tokens_saved, escalations_emitted, metadata_json
                   FROM delegation_events
                   WHERE created_at >= ?""",
                    (cutoff.isoformat(),),
                ).fetchall()
        except sqlite3.OperationalError:
            logger.debug("delegation_events table missing — returning empty report")
            return DelegationReport(since=cutoff, total_events=0, host_model=host_model)

        rpt = DelegationReport(since=cutoff, total_events=len(rows), host_model=host_model)
        if not rows:
            return rpt

        for r in rows:
            tier = r[0] or "unknown"
            rpt.m27_tokens_by_tier[tier] = rpt.m27_tokens_by_tier.get(tier, 0) + r[1] + r[2]
            rpt.m27_usd_cents += r[3]
            rpt.cache_tokens_saved += r[5]
            metadata = _load_json_dict(r[7] if len(r) > 7 else None)
            route_key = str(metadata.get("route_recommended") or "unknown")
            route_bucket = rpt.route_breakdown.setdefault(
                route_key,
                {
                    "events": 0,
                    "cache_tokens_saved": 0,
                    "verification_failures": 0,
                    "verification_verified": 0,
                    "avg_route_confidence": 0.0,
                },
            )
            route_bucket["events"] = _as_int(route_bucket["events"]) + 1
            route_bucket["cache_tokens_saved"] = _as_int(
                route_bucket["cache_tokens_saved"]
            ) + _as_int(metadata.get("token_savings_signal", 0))
            verification_status = str(metadata.get("verification_status") or "")
            if verification_status == "verification_failed":
                route_bucket["verification_failures"] = (
                    _as_int(route_bucket["verification_failures"]) + 1
                )
            if verification_status == "verified":
                route_bucket["verification_verified"] = (
                    _as_int(route_bucket["verification_verified"]) + 1
                )
            route_bucket["avg_route_confidence"] = _as_float(
                route_bucket["avg_route_confidence"]
            ) + (_as_float(metadata.get("route_confidence", 0.0)))

        total = rpt.total_events
        # cache_hit_rate is the *fraction of events that saw at least one cache
        # hit* — a true rate in [0, 1]. r[4] (cache_hits) is an unbounded per-event
        # count, so summing it and dividing by event count could exceed 1.0 (e.g.
        # render as "1200%"). Count events with hits>0 instead.
        events_with_cache_hit = sum(1 for r in rows if r[4] > 0)
        rpt.cache_hit_rate = events_with_cache_hit / total if total else 0.0
        total_escalations = sum(1 for r in rows if r[6] > 0)
        rpt.escalation_rate = total_escalations / total if total else 0.0
        for route_bucket in rpt.route_breakdown.values():
            events = _as_int(route_bucket["events"]) or 1
            route_bucket["avg_route_confidence"] = round(
                _as_float(route_bucket["avg_route_confidence"]) / events,
                3,
            )

        avg = HOST_TOKEN_ESTIMATES.get(host_model, 8000)
        rpt.estimated_host_tokens_avoided = total * avg
        avoided_output = int(rpt.estimated_host_tokens_avoided * HOST_AVOIDED_OUTPUT_SHARE)
        avoided_input = rpt.estimated_host_tokens_avoided - avoided_output
        rpt.estimated_host_usd_avoided = estimate_host_request_cost(
            host_model, avoided_input, avoided_output
        )
        rpt.estimated_net_savings_usd = rpt.estimated_host_usd_avoided - rpt.m27_usd_cents / 100
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
                f"Host model:                  {rpt.host_model}",
                f"Estimated host tokens        {rpt.estimated_host_tokens_avoided:,}",
                "  avoided (NOT measured):",
                f"Est. host cost avoided:      ${rpt.estimated_host_usd_avoided:.2f}",
                f"Est. net savings:            ${rpt.estimated_net_savings_usd:.2f}",
                "  (both estimated, NOT measured)",
            ]
        )
        if rpt.route_breakdown:
            lines.extend(["", "Route outcomes:"])
            for route_name, route_stats in sorted(rpt.route_breakdown.items()):
                lines.append(
                    "  "
                    f"{route_name:20s} events={int(route_stats['events']):>3} "
                    f"verified={int(route_stats['verification_verified']):>3} "
                    f"failed={int(route_stats['verification_failures']):>3} "
                    f"saved={int(route_stats['cache_tokens_saved']):>6}"
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
                "host_model": rpt.host_model,
                "estimated_host_usd_avoided": round(rpt.estimated_host_usd_avoided, 4),
                "estimated_net_savings_usd": round(rpt.estimated_net_savings_usd, 4),
                "route_breakdown": rpt.route_breakdown,
            },
            indent=2,
        )


def _load_json_dict(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0
