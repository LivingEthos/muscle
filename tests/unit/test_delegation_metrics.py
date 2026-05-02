"""Tests for delegation_metrics — Phase B.6 observability."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.muscle.delegation_metrics import (
    DelegationEvent,
    DelegationMetrics,
)
from tools.muscle.migrations._0013_delegation_events import MIGRATION_SQL
from tools.muscle.migrations._0017_delegation_event_metadata import (
    migrate as migrate_delegation_metadata,
)


@pytest.fixture()
def project_db(tmp_path: Path) -> Path:
    """Create a temp project dir with migrated project_memory.db."""
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    db_path = muscle_dir / "project_memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(MIGRATION_SQL)
    migrate_delegation_metadata(conn)
    conn.close()
    return tmp_path


def _insert_event(
    db_path: Path,
    session_id: str = "sess-001",
    task_tier: str | None = None,
    entry_point: str = "review:review",
    m27_tokens_in: int = 1000,
    m27_tokens_out: int = 500,
    m27_usd_cents: int = 5,
    cache_hits: int = 0,
    cache_tokens_saved: int = 0,
    escalations_emitted: int = 0,
    created_at: str | None = None,
) -> None:
    """Low-level insert bypassing DelegationMetrics.record for controlled tests."""
    full_db = db_path / ".muscle" / "project_memory.db"
    with sqlite3.connect(str(full_db)) as conn:
        conn.execute(
            """INSERT INTO delegation_events
               (session_id, created_at, task_tier, entry_point,
               m27_tokens_in, m27_tokens_out, m27_usd_cents,
               verifications_run, verifications_failed,
               escalations_emitted, cache_hits, cache_tokens_saved,
                    pack_id, pack_reused, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, NULL, 0, '{}')""",
            (
                session_id,
                created_at or datetime.now(timezone.utc).isoformat(),
                task_tier,
                entry_point,
                m27_tokens_in,
                m27_tokens_out,
                m27_usd_cents,
                escalations_emitted,
                cache_hits,
                cache_tokens_saved,
            ),
        )


class TestRecordAndRetrieve:
    def test_record_and_retrieve_single_event(self, project_db: Path) -> None:
        metrics = DelegationMetrics(project_db)
        metrics.record(
            DelegationEvent(
                session_id="sess-001",
                entry_point="review:review",
                task_tier="mechanical",
                m27_tokens_in=1000,
                m27_tokens_out=500,
                m27_usd_cents=5,
            )
        )

        rpt = metrics.report(since=timedelta(days=1))
        assert rpt.total_events == 1
        assert rpt.m27_tokens_by_tier.get("mechanical") == 1500
        assert rpt.m27_usd_cents == 5

    def test_report_aggregates_by_tier(self, project_db: Path) -> None:
        _insert_event(
            project_db,
            session_id="s1",
            task_tier="mechanical",
            m27_tokens_in=100,
            m27_tokens_out=50,
        )
        _insert_event(
            project_db,
            session_id="s2",
            task_tier="mechanical",
            m27_tokens_in=200,
            m27_tokens_out=100,
        )
        _insert_event(
            project_db,
            session_id="s3",
            task_tier="reasoning",
            m27_tokens_in=500,
            m27_tokens_out=250,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert rpt.total_events == 3
        assert rpt.m27_tokens_by_tier["mechanical"] == 450  # 150 + 300
        assert rpt.m27_tokens_by_tier["reasoning"] == 750  # 500 + 250

    def test_report_since_window_excludes_old_events(self, project_db: Path) -> None:
        # Insert an event from 30 days ago
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        _insert_event(project_db, session_id="old", created_at=old_ts)
        # Insert a recent event
        _insert_event(project_db, session_id="recent")

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=7))

        assert rpt.total_events == 1

    def test_report_empty_db(self, project_db: Path) -> None:
        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=7))
        assert rpt.total_events == 0
        assert rpt.m27_usd_cents == 0


class TestReportFormatting:
    def test_text_format_contains_required_fields(self, project_db: Path) -> None:
        _insert_event(
            project_db, session_id="s1", m27_usd_cents=42, cache_hits=1, escalations_emitted=0
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        text = metrics.format_text(rpt)

        assert "delegated tasks" in text.lower()
        assert "$0.42" in text  # m27_usd_cents / 100
        assert "Cache hit rate" in text
        assert "Escalation rate" in text
        assert "Estimated host tokens" in text
        assert "NOT measured" in text

    def test_text_format_includes_route_breakdown_when_present(self, project_db: Path) -> None:
        metrics = DelegationMetrics(project_db)
        metrics.record(
            DelegationEvent(
                session_id="sess-001",
                entry_point="review:review",
                task_tier="reasoning",
                metadata={
                    "route_recommended": "m27_with_verify",
                    "verification_status": "verified",
                    "token_savings_signal": 128,
                },
            )
        )

        rpt = metrics.report(since=timedelta(days=1))
        text = metrics.format_text(rpt)
        assert "Route outcomes" in text
        assert "m27_with_verify" in text

    def test_json_format_is_valid_json(self, project_db: Path) -> None:
        _insert_event(project_db, session_id="s1")

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        raw = metrics.format_json(rpt)

        parsed = json.loads(raw)
        assert "total_events" in parsed
        assert "m27_usd_cents" in parsed
        assert "estimated_host_tokens_avoided" in parsed


class TestReconcileWithBudgetManager:
    def test_reconcile_with_budget_manager(self, project_db: Path) -> None:
        """Verify m27_usd_cents in report matches raw cents inserted."""
        _insert_event(project_db, session_id="s1", m27_usd_cents=10)
        _insert_event(project_db, session_id="s2", m27_usd_cents=25)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        # Total cents should be 35; reconcile within 1 cent.
        assert abs(rpt.m27_usd_cents - 35) <= 1


class TestCacheAndEscalationRates:
    def test_cache_hit_rate(self, project_db: Path) -> None:
        _insert_event(project_db, session_id="s1", cache_hits=1, cache_tokens_saved=500)
        _insert_event(project_db, session_id="s2", cache_hits=0, cache_tokens_saved=0)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        assert rpt.cache_hit_rate == 0.5  # 1 out of 2 events had cache hit
        assert rpt.cache_tokens_saved == 500

    def test_escalation_rate(self, project_db: Path) -> None:
        _insert_event(project_db, session_id="s1", escalations_emitted=0)
        _insert_event(project_db, session_id="s2", escalations_emitted=1)
        _insert_event(project_db, session_id="s3", escalations_emitted=0)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        assert abs(rpt.escalation_rate - (1 / 3)) < 0.01


class TestMissingDb:
    def test_graceful_when_no_db(self, tmp_path: Path) -> None:
        """DelegationMetrics should not raise when no DB exists."""
        metrics = DelegationMetrics(tmp_path)
        rpt = metrics.report(since=timedelta(days=7))
        assert rpt.total_events == 0

    def test_record_skips_when_no_db(self, tmp_path: Path) -> None:
        """record() should log a warning but not raise."""
        metrics = DelegationMetrics(tmp_path)
        metrics.record(DelegationEvent(session_id="s1", entry_point="review:review"))
        # No assertion needed — just no exception.
