"""
Unit tests for savings and discovery reports.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.muscle.command_evidence import ParserTier, build_command_evidence
from tools.muscle.discovery import build_discovery_report
from tools.muscle.project_memory import ProjectMemory
from tools.muscle.savings import build_savings_report


def test_savings_aggregates_llm_ledger_and_command_evidence(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()
    pm = ProjectMemory(str(tmp_path))
    pm.insert_llm_call(
        project_path=str(tmp_path),
        call_id="call-1",
        session_id="session-1",
        stage="semantic-review",
        model="m",
        input_tokens=100,
        output_tokens=50,
        duration_ms=10,
        success=True,
        metadata_json=json.dumps(
            {
                "prompt_compaction_estimated_tokens_saved": 25,
                "cache_tokens": 12,
            }
        ),
    )
    pm.insert_token_savings_entry(
        project_path=str(tmp_path),
        session_id="session-1",
        stage="semantic-review",
        workflow_name=None,
        comparable_key="k",
        actual_tokens=150,
        delta_tokens=20,
        confidence=0.9,
        realized=True,
        estimation_type="observed",
    )
    build_command_evidence(
        command=["tool"],
        cwd=str(tmp_path),
        exit_code=1,
        duration_ms=1,
        raw_stdout="x" * 1000,
        raw_stderr="error",
        parser_tier=ParserTier.PASSTHROUGH,
    )

    report = build_savings_report(tmp_path)

    assert report["llm_calls"]["count"] == 1
    assert report["llm_calls"]["total_tokens"] == 150
    assert report["llm_calls"]["prompt_compaction_tokens_saved"] == 25
    assert report["token_savings_ledger"]["net_tokens_saved"] == 20
    assert report["command_evidence"]["count"] == 1
    assert report["command_evidence"]["failure_count"] == 1
    assert report["command_evidence"]["parser_tier_counts"]["PASSTHROUGH"] == 1
    assert report["totals"]["tokens_saved_estimate"] >= 57


def test_discovery_reports_repeated_failed_commands_and_does_not_write_memory(
    tmp_path: Path,
) -> None:
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    memory_file = tmp_path / "AGENTS.md"
    memory_file.write_text("user content", encoding="utf-8")
    pm = ProjectMemory(str(tmp_path))
    session_id = pm.upsert_external_benchmark_session(
        project_path=str(tmp_path),
        provider="codex",
        external_session_id="external-1",
        source_path="session.jsonl",
        normalized_project_path=str(tmp_path),
    )
    for index in range(2):
        pm.insert_external_benchmark_turn(
            benchmark_session_id=session_id,
            timestamp=f"2026-05-01T00:00:0{index}+00:00",
            category="verify",
            model="m",
            input_tokens=10,
            output_tokens=5,
            cache_tokens=0,
            reasoning_tokens=0,
            retry_count=1,
            success_signal=False,
            token_cost=15,
            tool_names_json=json.dumps(["bash"]),
            metadata_json=json.dumps({"user_message": "uv run pytest"}),
            dedup_key=f"turn-{index}",
        )

    report = build_discovery_report(tmp_path, since_days=30)

    assert memory_file.read_text(encoding="utf-8") == "user content"
    assert report["no_write_guarantee"]["memory_files_edited"] is False
    opportunity_types = {item["type"] for item in report["opportunities"]}
    assert "repeated_failed_commands" in opportunity_types
    assert "repeated_cli_mistakes" in opportunity_types
