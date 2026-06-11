"""Tests for delegation_metrics — Phase B.6 observability."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from muscle.cost_optimizer import estimate_request_cost
from muscle.delegation_metrics import (
    DelegationEvent,
    DelegationMetrics,
    estimate_m27_cents,
    resolve_m27_token_split,
)
from muscle.migrations._0013_delegation_events import MIGRATION_SQL
from muscle.migrations._0017_delegation_event_metadata import (
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
        assert "estimated_host_usd_avoided" in parsed
        assert "estimated_net_savings_usd" in parsed
        assert parsed["host_model"] == "claude-fable-5"

    def test_host_dollar_estimate_uses_fable5_pricing(self, project_db: Path) -> None:
        _insert_event(project_db, session_id="s1", m27_usd_cents=100)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1), host_model="claude-fable-5")

        # 8000 avoided tokens at 75% input ($10/MTok) + 25% output ($50/MTok).
        expected = (6000 * 10.00 + 2000 * 50.00) / 1_000_000
        assert rpt.estimated_host_usd_avoided == pytest.approx(expected)
        assert rpt.estimated_net_savings_usd == pytest.approx(expected - 1.00)
        text = metrics.format_text(rpt)
        assert "claude-fable-5" in text
        assert "Est. host cost avoided" in text

    def test_unknown_host_model_is_rejected(self, project_db: Path) -> None:
        metrics = DelegationMetrics(project_db)
        with pytest.raises(ValueError, match="unknown host model"):
            metrics.report(since=timedelta(days=1), host_model="claude-typo-9")


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


class TestSavingsMath:
    def test_net_savings_subtracts_real_m27_cost(self, project_db: Path) -> None:
        """Net savings must subtract MUSCLE's own M3 spend, not equal gross avoided.

        Regression for COST#1: m27_usd_cents used to default to 0 at every call
        site, so net savings collapsed onto gross host-avoided and implied MUSCLE
        ran for free.
        """
        _insert_event(project_db, session_id="s1", m27_usd_cents=250)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert rpt.m27_usd_cents == 250
        assert rpt.estimated_net_savings_usd == pytest.approx(rpt.estimated_host_usd_avoided - 2.50)
        # Net must be strictly less than gross once M3 spend is non-zero.
        assert rpt.estimated_net_savings_usd < rpt.estimated_host_usd_avoided

    def test_output_tokens_counted_in_tier_volume(self, project_db: Path) -> None:
        """Tier sums must include output tokens (COST#2)."""
        _insert_event(
            project_db,
            session_id="s1",
            task_tier="tierA",
            m27_tokens_in=1000,
            m27_tokens_out=400,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert rpt.m27_tokens_by_tier["tierA"] == 1400


class TestSplitAndCostHelpers:
    def test_real_split_passes_through(self) -> None:
        # When the measured split is present, it is returned verbatim.
        assert resolve_m27_token_split(900, 300, 1200) == (900, 300)

    def test_zero_split_attributes_remainder_to_input(self) -> None:
        # Resumed legacy session: split fields are 0 but a combined total exists.
        assert resolve_m27_token_split(0, 0, 1200) == (1200, 0)

    def test_partial_split_attributes_only_the_remainder(self) -> None:
        # Combined total exceeds the recorded split: the unaccounted remainder
        # (1200 - (700 + 200) = 300) lands on input; output is left untouched.
        assert resolve_m27_token_split(700, 200, 1200) == (1000, 200)

    def test_split_clamps_negative_inputs(self) -> None:
        assert resolve_m27_token_split(-5, -3, -10) == (0, 0)

    def test_split_no_remainder_when_split_covers_total(self) -> None:
        # Combined total smaller than the measured split (e.g. stale total):
        # no negative remainder is fabricated.
        assert resolve_m27_token_split(900, 300, 100) == (900, 300)

    def test_estimate_cents_matches_cost_optimizer(self) -> None:
        cents = estimate_m27_cents("MiniMax-M3", 6000, 2000)
        expected = round(estimate_request_cost("MiniMax-M3", 6000, 2000) * 100)
        assert cents == expected

    def test_estimate_cents_defaults_model_when_none(self) -> None:
        assert estimate_m27_cents(None, 100, 50) == estimate_m27_cents("MiniMax-M3", 100, 50)


class TestCacheHitRateBounded:
    def test_cache_hit_rate_never_exceeds_one(self, project_db: Path) -> None:
        """Regression for COST#3: a large per-event hit COUNT must not inflate the
        rate above 1.0 (previously summed counts / events → e.g. 1200%)."""
        _insert_event(project_db, session_id="s1", cache_hits=12)
        _insert_event(project_db, session_id="s2", cache_hits=8)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert rpt.cache_hit_rate == pytest.approx(1.0)
        assert 0.0 <= rpt.cache_hit_rate <= 1.0

    def test_cache_hit_rate_is_event_fraction(self, project_db: Path) -> None:
        _insert_event(project_db, session_id="s1", cache_hits=5)
        _insert_event(project_db, session_id="s2", cache_hits=0)
        _insert_event(project_db, session_id="s3", cache_hits=0)
        _insert_event(project_db, session_id="s4", cache_hits=3)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert rpt.cache_hit_rate == pytest.approx(0.5)


def _insert_event_with_metadata(
    db_path: Path,
    *,
    session_id: str,
    metadata: dict | None,
    m27_tokens_in: int = 1000,
    m27_tokens_out: int = 500,
    m27_usd_cents: int = 5,
    created_at: str | None = None,
) -> None:
    """Insert an event with arbitrary metadata_json (for provider tests)."""
    full_db = db_path / ".muscle" / "project_memory.db"
    with sqlite3.connect(str(full_db)) as conn:
        conn.execute(
            """INSERT INTO delegation_events
               (session_id, created_at, task_tier, entry_point,
               m27_tokens_in, m27_tokens_out, m27_usd_cents,
               verifications_run, verifications_failed,
               escalations_emitted, cache_hits, cache_tokens_saved,
                    pack_id, pack_reused, metadata_json)
               VALUES (?, ?, NULL, 'review:review', ?, ?, ?, 0, 0, 0, 0, 0, NULL, 0, ?)""",
            (
                session_id,
                created_at or datetime.now(timezone.utc).isoformat(),
                m27_tokens_in,
                m27_tokens_out,
                m27_usd_cents,
                json.dumps(metadata) if metadata is not None else "{}",
            ),
        )


class TestProviderBreakdown:
    def test_groups_events_by_provider(self, project_db: Path) -> None:
        _insert_event_with_metadata(
            project_db,
            session_id="m1",
            metadata={
                "provider": "minimax-plan",
                "execution_model": "MiniMax-M3",
                "billing": "plan-quota",
            },
            m27_tokens_in=1000,
            m27_tokens_out=400,
        )
        _insert_event_with_metadata(
            project_db,
            session_id="a1",
            metadata={
                "provider": "anthropic-api",
                "execution_model": "claude-opus-4-8",
                "billing": "api-dollars",
            },
            m27_tokens_in=2000,
            m27_tokens_out=600,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert set(rpt.provider_breakdown) == {"minimax-plan", "anthropic-api"}
        mp = rpt.provider_breakdown["minimax-plan"]
        assert mp.events == 1
        assert mp.tokens_in == 1000
        assert mp.tokens_out == 400
        ap = rpt.provider_breakdown["anthropic-api"]
        assert ap.events == 1
        assert ap.tokens_in == 2000
        assert ap.tokens_out == 600

    def test_legacy_event_without_provider_buckets_as_minimax_plan(self, project_db: Path) -> None:
        # An event written before provider stamping (metadata '{}') must bucket
        # under minimax-plan rather than being dropped.
        _insert_event(project_db, session_id="legacy", m27_tokens_in=300, m27_tokens_out=100)

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert "minimax-plan" in rpt.provider_breakdown
        bucket = rpt.provider_breakdown["minimax-plan"]
        assert bucket.events == 1
        assert bucket.usd_cents is None  # plan quota: no marginal dollars

    def test_plan_quota_provider_has_no_dollar_figure(self, project_db: Path) -> None:
        _insert_event_with_metadata(
            project_db,
            session_id="m1",
            metadata={
                "provider": "minimax-plan",
                "execution_model": "MiniMax-M3",
                "billing": "plan-quota",
            },
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        bucket = rpt.provider_breakdown["minimax-plan"]
        assert bucket.usd_cents is None
        assert "plan quota" in bucket.billing_label.lower()

        text = metrics.format_text(rpt)
        assert "By provider" in text
        assert "tokens consumed" in text
        # A quota provider must never print a fabricated spend figure.
        assert "minimax-plan" in text

    def test_agent_sdk_credit_label_for_claude_subscription(self, project_db: Path) -> None:
        _insert_event_with_metadata(
            project_db,
            session_id="cs1",
            metadata={
                "provider": "claude-subscription",
                "execution_model": "claude-opus-4-8",
                "billing": "agent-sdk-credit",
            },
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        bucket = rpt.provider_breakdown["claude-subscription"]
        assert bucket.usd_cents is None
        assert "agent sdk credit" in bucket.billing_label.lower()

    def test_api_dollars_provider_computes_usd_from_opus_pricing(self, project_db: Path) -> None:
        _insert_event_with_metadata(
            project_db,
            session_id="a1",
            metadata={
                "provider": "anthropic-api",
                "execution_model": "claude-opus-4-8",
                "billing": "api-dollars",
            },
            m27_tokens_in=100_000,
            m27_tokens_out=20_000,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        bucket = rpt.provider_breakdown["anthropic-api"]
        expected_usd = estimate_request_cost("claude-opus-4-8", 100_000, 20_000)
        assert bucket.usd_cents == round(expected_usd * 100)
        assert "anthropic api dollars" in bucket.billing_label.lower()

    def test_json_includes_provider_breakdown(self, project_db: Path) -> None:
        _insert_event_with_metadata(
            project_db,
            session_id="a1",
            metadata={
                "provider": "anthropic-api",
                "execution_model": "claude-opus-4-8",
                "billing": "api-dollars",
            },
            m27_tokens_in=100_000,
            m27_tokens_out=20_000,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))
        parsed = json.loads(metrics.format_json(rpt))
        assert "provider_breakdown" in parsed
        assert "anthropic-api" in parsed["provider_breakdown"]
        entry = parsed["provider_breakdown"]["anthropic-api"]
        assert entry["events"] == 1
        assert entry["usd_cents"] == round(
            estimate_request_cost("claude-opus-4-8", 100_000, 20_000) * 100
        )

    def test_net_savings_subtracts_claude_execution_cost(self, project_db: Path) -> None:
        # A Claude (anthropic-api) execution event must shrink net savings by the
        # real host execution dollars, beyond MUSCLE's own recorded m27 spend.
        _insert_event_with_metadata(
            project_db,
            session_id="a1",
            metadata={
                "provider": "anthropic-api",
                "execution_model": "claude-opus-4-8",
                "billing": "api-dollars",
            },
            m27_tokens_in=100_000,
            m27_tokens_out=20_000,
            m27_usd_cents=50,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        host_exec = estimate_request_cost("claude-opus-4-8", 100_000, 20_000)
        expected = rpt.estimated_host_usd_avoided - 0.50 - host_exec
        assert rpt.estimated_net_savings_usd == pytest.approx(expected)

    def test_minimax_api_execution_not_double_subtracted(self, project_db: Path) -> None:
        # MiniMax api-dollar spend is already represented by m27_usd_cents, so it
        # must NOT be subtracted a second time via provider_usd. Net savings here
        # must match the legacy formula (gross avoided minus m27 spend only).
        _insert_event_with_metadata(
            project_db,
            session_id="ma1",
            metadata={
                "provider": "minimax-api",
                "execution_model": "MiniMax-M3",
                "billing": "api-dollars",
            },
            m27_tokens_in=10_000,
            m27_tokens_out=2_000,
            m27_usd_cents=40,
        )

        metrics = DelegationMetrics(project_db)
        rpt = metrics.report(since=timedelta(days=1))

        assert rpt.estimated_net_savings_usd == pytest.approx(rpt.estimated_host_usd_avoided - 0.40)
        # The provider bucket still reports its own estimated MiniMax dollars.
        assert rpt.provider_breakdown["minimax-api"].usd_cents is not None


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
