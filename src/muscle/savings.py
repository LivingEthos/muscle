"""
Savings reporting for MUSCLE local evidence.

Architecture Decision Record (ADR):
- Savings are computed from project-local MUSCLE stores and command evidence
  artifacts only. No anonymous/global telemetry is introduced.
- Report fields are stable for plugin automation while the human CLI view can
  summarize the same payload.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .command_evidence import iter_command_evidence
from .project_memory import ProjectMemory


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _intish(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sum_metadata_int(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> int:
    total = 0
    for row in rows:
        meta = _metadata(row)
        total += sum(_intish(meta.get(key)) for key in keys)
    return total


def build_savings_report(project_path: str | Path, *, limit: int = 5000) -> dict[str, Any]:
    """Build a stable savings report for one project."""
    resolved_project = str(Path(project_path).resolve())
    pm = ProjectMemory(resolved_project)
    llm_calls = pm.list_llm_calls(project_path=resolved_project, limit=limit)
    token_ledger = pm.get_token_savings_summary(resolved_project)
    high_cost_stages = pm.get_llm_stage_summary(resolved_project, limit=10)
    command_rows = iter_command_evidence(resolved_project, limit=limit)

    llm_input_tokens = sum(_intish(row.get("input_tokens")) for row in llm_calls)
    llm_output_tokens = sum(_intish(row.get("output_tokens")) for row in llm_calls)
    llm_total_tokens = llm_input_tokens + llm_output_tokens
    prompt_compaction_saved = _sum_metadata_int(
        llm_calls,
        (
            "prompt_compaction_estimated_tokens_saved",
            "compacted_prompt_tokens_saved",
            "prompt_tokens_saved",
        ),
    )
    cache_tokens = _sum_metadata_int(
        llm_calls,
        ("cache_tokens", "cache_read_tokens", "cached_input_tokens"),
    )

    parser_counts = Counter(str(row.get("parser_tier") or "UNKNOWN") for row in command_rows)
    command_raw_tokens = sum(_intish(row.get("tokens_raw_estimate")) for row in command_rows)
    command_compact_tokens = sum(
        _intish(row.get("tokens_compact_estimate")) for row in command_rows
    )
    command_saved = sum(_intish(row.get("tokens_saved_estimate")) for row in command_rows)
    command_failures = sum(1 for row in command_rows if _intish(row.get("exit_code")) != 0)
    command_truncations = sum(
        1
        for row in command_rows
        if bool(row.get("stdout_truncated")) or bool(row.get("stderr_truncated"))
    )

    return {
        "project_path": resolved_project,
        "llm_calls": {
            "count": len(llm_calls),
            "success_count": sum(1 for row in llm_calls if bool(row.get("success"))),
            "input_tokens": llm_input_tokens,
            "output_tokens": llm_output_tokens,
            "total_tokens": llm_total_tokens,
            "prompt_compaction_tokens_saved": prompt_compaction_saved,
            "cache_tokens": cache_tokens,
        },
        "token_savings_ledger": token_ledger,
        "command_evidence": {
            "count": len(command_rows),
            "raw_tokens_estimate": command_raw_tokens,
            "compact_tokens_estimate": command_compact_tokens,
            "tokens_saved_estimate": command_saved,
            "failure_count": command_failures,
            "truncation_count": command_truncations,
            "parser_tier_counts": dict(sorted(parser_counts.items())),
        },
        "totals": {
            "tokens_observed": llm_total_tokens + command_raw_tokens,
            "tokens_saved_estimate": (
                _intish(token_ledger.get("net_tokens_saved"))
                + prompt_compaction_saved
                + command_saved
                + cache_tokens
            ),
        },
        "high_cost_stages": high_cost_stages,
    }
