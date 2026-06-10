"""
Read-only discovery of missed MUSCLE opportunities.

Architecture Decision Record (ADR):
- Discovery reports opportunities from imported host sessions and local MUSCLE
  state, but never edits project memory files or learned-rule sections.
- Heuristics are intentionally conservative and evidence-backed so follow-up
  automation can decide whether to act.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .code_review.static_analyzer import LANGUAGE_EXTENSIONS, LANGUAGE_TOOLS
from .project_memory import ProjectMemory

EDIT_TOOLS = {"edit", "write", "apply_patch", "multi_tool_use.parallel"}
VERIFY_TOOLS = {"bash", "test", "lint", "functions.exec_command"}


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        data = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recent_turns(turns: list[dict[str, Any]], since_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    recent = []
    for row in turns:
        timestamp = _parse_dt(row.get("timestamp"))
        if timestamp is None or timestamp >= cutoff:
            recent.append(row)
    return recent


def _detected_languages(project_path: Path) -> list[str]:
    excluded_parts = {".git", ".venv", "venv", "node_modules", "__pycache__", ".muscle"}
    found: set[str] = set()
    for path in project_path.rglob("*"):
        if not path.is_file() or any(part in excluded_parts for part in path.parts):
            continue
        suffix = path.suffix.lower()
        for language, extensions in LANGUAGE_EXTENSIONS.items():
            if suffix in extensions:
                found.add(language)
    return sorted(found)


def _missing_analyzers(project_path: Path) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []
    for language in _detected_languages(project_path):
        missing = [
            str(tool["name"])
            for tool in LANGUAGE_TOOLS.get(language, [])
            if not shutil.which(str(tool["cmd"][0]))
        ]
        if missing:
            opportunities.append(
                {
                    "type": "missing_analyzers",
                    "severity": "medium",
                    "language": language,
                    "missing_tools": missing,
                    "message": f"{language} files detected but analyzer tools are missing",
                }
            )
    return opportunities


def _open_findings(pm: ProjectMemory, project_path: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for run in pm.list_review_runs(project_path=project_path, limit=50):
        run_id = int(run.get("id") or 0)
        if not run_id:
            continue
        for finding in pm.list_findings_for_run(run_id):
            if not bool(finding.get("fix_applied")):
                counts[str(finding.get("file_path") or "")] += 1
    return dict(counts)


def build_discovery_report(
    project_path: str | Path,
    *,
    since_days: int = 30,
    limit: int = 500,
) -> dict[str, Any]:
    """Build a read-only discovery report for one project."""
    resolved_project = str(Path(project_path).resolve())
    project_root = Path(resolved_project)
    pm = ProjectMemory(resolved_project)
    turns = _recent_turns(
        pm.list_external_benchmark_turns(project_path=resolved_project, limit=limit),
        since_days,
    )
    reviews = pm.list_review_runs(project_path=resolved_project, limit=50)
    latest_review = reviews[0] if reviews else None
    open_finding_counts = _open_findings(pm, resolved_project)

    opportunities: list[dict[str, Any]] = []
    opportunities.extend(_missing_analyzers(project_root))

    edit_turns: list[dict[str, Any]] = []
    failed_verify_by_message: Counter[str] = Counter()
    repeated_tool_failures: Counter[str] = Counter()
    direct_fix_turns: list[dict[str, Any]] = []

    for row in turns:
        tool_names = {name.lower() for name in _parse_json_list(row.get("tool_names_json"))}
        metadata = _parse_metadata(row.get("metadata_json"))
        user_message = str(metadata.get("user_message") or "")
        has_edit = bool(tool_names & EDIT_TOOLS)
        has_verify = bool(tool_names & VERIFY_TOOLS)
        success = bool(row.get("success_signal"))

        if has_edit:
            edit_turns.append(row)
            if open_finding_counts and any(
                str(path).lower() in user_message.lower() for path in open_finding_counts
            ):
                direct_fix_turns.append(row)

        if has_verify and not success:
            message_key = user_message.strip().lower()[:120] or ",".join(sorted(tool_names))
            failed_verify_by_message[message_key] += 1
            for tool_name in tool_names & VERIFY_TOOLS:
                repeated_tool_failures[tool_name] += 1

    if edit_turns and latest_review is None:
        opportunities.append(
            {
                "type": "edits_without_review",
                "severity": "high",
                "count": len(edit_turns),
                "message": "Imported host sessions show edits but no MUSCLE review run is recorded",
            }
        )

    repeated_failed = [
        {"signature": key, "count": count}
        for key, count in failed_verify_by_message.most_common()
        if count >= 2
    ]
    if repeated_failed:
        opportunities.append(
            {
                "type": "repeated_failed_commands",
                "severity": "medium",
                "failures": repeated_failed[:10],
                "message": "Repeated failed verification turns may need a MUSCLE review/check gate",
            }
        )

    repeated_cli = [
        {"tool": tool, "count": count}
        for tool, count in repeated_tool_failures.most_common()
        if count >= 2
    ]
    if repeated_cli:
        opportunities.append(
            {
                "type": "repeated_cli_mistakes",
                "severity": "low",
                "tools": repeated_cli[:10],
                "message": "Same CLI/tool path failed repeatedly in imported sessions",
            }
        )

    if direct_fix_turns:
        opportunities.append(
            {
                "type": "direct_fixes_to_open_findings",
                "severity": "medium",
                "count": len(direct_fix_turns),
                "open_finding_files": sorted(open_finding_counts)[:20],
                "message": "Imported edits mention files with unresolved MUSCLE findings",
            }
        )

    return {
        "project_path": resolved_project,
        "since_days": since_days,
        "summary": {
            "imported_turns_scanned": len(turns),
            "review_runs_seen": len(reviews),
            "open_finding_files": len(open_finding_counts),
            "opportunity_count": len(opportunities),
        },
        "opportunities": opportunities,
        "no_write_guarantee": {
            "memory_files_edited": False,
            "managed_memory_paths": [
                ".muscle/CLAUDE.md",
                ".muscle/AGENT.md",
                ".muscle/MEMORY.md",
                "CLAUDE.md",
                "AGENTS.md",
            ],
        },
    }
