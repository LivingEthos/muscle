"""
Unit tests for active-review snapshots, doctor reporting, and host runtime.
"""

from __future__ import annotations

from pathlib import Path

from tools.muscle.active_review import (
    refresh_active_review,
    refresh_external_catchup,
)
from tools.muscle.doctor import build_doctor_report
from tools.muscle.host_runtime import run_host_hook
from tools.muscle.project_memory import ProjectMemory
from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager


def _init_project(tmp_path: Path) -> ProjectMemory:
    manager = ProjectManager(tmp_path)
    config = ProjectConfig(
        name="demo",
        path=tmp_path,
        languages=["Python"],
        platform="codex",
    )
    assert manager.init_project(config) is True
    assert manager.set_project_enabled(tmp_path, True) is True
    return ProjectMemory(str(tmp_path))


def test_refresh_active_review_generates_stable_digest(tmp_path: Path) -> None:
    pm = _init_project(tmp_path)
    review_run_id = pm.insert_review_run(
        project_path=str(tmp_path),
        review_mode="review",
        target_path=str(tmp_path / "src"),
        findings_count=1,
        token_cost=42,
        duration_ms=900,
        created_at="2026-04-20T12:00:00+00:00",
    )
    finding_id = pm.insert_review_finding(
        review_run_id=review_run_id,
        rule_id="demo.rule",
        severity="HIGH",
        file_path=str(tmp_path / "src" / "app.py"),
        line_number=12,
        message="demo issue",
    )
    pm.insert_fix_attempt(
        finding_id=finding_id,
        verification_passed=False,
        notes="verification failed",
    )

    first = refresh_active_review(str(tmp_path), reason="test")
    second = refresh_active_review(str(tmp_path), reason="test-repeat")

    assert (tmp_path / ".muscle" / "active-review.md").exists()
    assert "## Current State" in first.content
    assert "## Latest Review" in first.content
    assert "## External Catchup" in first.content
    assert first.digest == second.digest
    assert second.changed is False


def test_refresh_external_catchup_hides_raw_transcript_text(tmp_path: Path) -> None:
    pm = _init_project(tmp_path)
    session_id = pm.upsert_external_benchmark_session(
        project_path=str(tmp_path),
        provider="codex",
        external_session_id="session-1",
        source_path=str(tmp_path / "rollout.jsonl"),
        normalized_project_path=str(tmp_path),
        metadata_json="{}",
    )
    pm.insert_external_benchmark_turn(
        benchmark_session_id=session_id,
        timestamp="2026-04-20T12:05:00+00:00",
        category="edit",
        model="gpt-5.4",
        input_tokens=10,
        output_tokens=5,
        cache_tokens=0,
        reasoning_tokens=0,
        retry_count=0,
        success_signal=True,
        token_cost=15,
        tool_names_json='["Write"]',
        metadata_json='{"user_message":"SECRET USER MESSAGE"}',
        dedup_key="codex:test:1",
    )

    summary = refresh_external_catchup(str(tmp_path), provider="codex", import_new=False)

    assert summary.turn_count == 1
    assert "SECRET USER MESSAGE" not in summary.summary
    assert "Codex" in summary.summary or "codex" in summary.summary


def test_build_doctor_report_surfaces_new_plugin_checks(tmp_path: Path) -> None:
    _init_project(tmp_path)
    refresh_active_review(str(tmp_path), reason="doctor-test")

    report = build_doctor_report(str(tmp_path), refresh=False)
    checks = {check.key: check for check in report.checks}

    assert "claude_marketplace_manifest" in checks
    assert "codex_manifest" in checks
    assert "plugin_manifest_digests" in checks
    assert "plugin_hook_digests" in checks
    assert "plugin_command_docs_parity" in checks
    assert "plugin_assets" in checks
    assert "plugin_hook_runtime" in checks
    assert "active_review_snapshot" in checks
    assert "provider_endpoint" in checks
    assert checks["project_initialized"].status == "ok"
    assert checks["plugin_command_docs_parity"].status == "ok"


def test_build_doctor_report_warns_on_real_anthropic_endpoint(
    tmp_path: Path, monkeypatch
) -> None:
    """B3: doctor surfaces a warn when ANTHROPIC_BASE_URL points at the real
    Anthropic API instead of MiniMax. Without this, MUSCLE silently sends
    M2.7-shaped traffic to Anthropic."""
    _init_project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    report = build_doctor_report(str(tmp_path), refresh=False)
    checks = {check.key: check for check in report.checks}
    assert checks["provider_endpoint"].status == "warn"
    assert "anthropic.com" in checks["provider_endpoint"].detail.lower()


def test_build_doctor_report_passes_on_minimax_endpoint(tmp_path: Path, monkeypatch) -> None:
    """B3: doctor reports OK when ANTHROPIC_BASE_URL points at MiniMax."""
    _init_project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    report = build_doctor_report(str(tmp_path), refresh=False)
    checks = {check.key: check for check in report.checks}
    assert checks["provider_endpoint"].status == "ok"


def test_run_host_hook_deduplicates_post_write_messages(tmp_path: Path) -> None:
    _init_project(tmp_path)

    first = run_host_hook("codex", "post_write", str(tmp_path), tool_name="Write")
    second = run_host_hook("codex", "post_write", str(tmp_path), tool_name="Write")

    assert first.ok is True
    assert first.changed is True
    assert first.message
    assert second.ok is True
    assert second.changed is False
    assert second.message == ""
