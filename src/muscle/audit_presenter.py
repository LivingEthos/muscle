"""
Audit presenter helpers for CLI and TUI explainability.

Architecture Decision Record (ADR):
- Keep raw audit data in project_memory.db and format it at the edges
- Reuse one formatter across CLI and TUI so lifecycle messaging stays consistent
- Prefer compact, provenance-aware summaries over dumping raw JSON blobs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ACTION_LABELS = {
    "publish": "published",
    "backup": "backup",
    "restore": "restore",
    "skill_create": "skill created",
    "skill_revise": "skill revised",
    "skill_archive": "skill archived",
    "agent_create": "agent created",
    "agent_archive": "agent archived",
    "related_project_imported": "project imported",
    "related_project_attached": "project attached",
    "related_project_unlinked": "project unlinked",
    "related_import_scrub": "import scrubbed",
    "transferred_lesson_validated": "lesson validated",
    "transferred_lesson_promoted": "lesson promoted",
    "transferred_lesson_archived": "lesson archived",
    "model_pack_export_scrub": "model pack exported",
}

ENTITY_LABELS = {
    "related_project": "related-project",
    "transferred_lesson": "lesson",
    "claude_md": "claude-md",
    "model_pack_export": "model-pack",
}


def _parse_details(details_json: Any) -> dict[str, Any]:
    """Parse action-log details into a dictionary."""
    if isinstance(details_json, dict):
        return dict(details_json)
    if not details_json:
        return {}
    try:
        parsed = json.loads(str(details_json))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_label(source_project_path: str | None) -> str:
    """Return a compact display name for a source project path."""
    if not source_project_path:
        return "unknown"
    return Path(source_project_path).name or source_project_path


def format_action_log_entry(entry: dict[str, Any]) -> dict[str, str]:
    """Return consistent display fields for one audit log entry."""
    details_obj = _parse_details(entry.get("details_json"))
    action_type = str(entry.get("action_type", "") or "")
    entity_type = str(entry.get("entity_type", "") or "")
    entity_id = entry.get("entity_id")

    if entity_type == "backup":
        details = details_obj.get("backup_type", "")
        if action_type == "restore":
            details = f"{details}, restored={details_obj.get('restored_count', '?')} files"
    elif entity_type == "skill":
        details = (
            str(details_obj.get("skill_name", "") or "")
            or str(details_obj.get("trigger_pattern", "") or "")
            or str(details_obj.get("skill_path", "") or "")
        )
    elif entity_type == "agent":
        details = str(details_obj.get("agent_name", "") or "") or str(
            details_obj.get("trigger_pattern", "") or ""
        )
    elif entity_type == "claude_md":
        details = "CLAUDE.md published"
    elif entity_type == "related_project":
        source_label = _source_label(str(details_obj.get("source_project_path", "") or ""))
        if action_type == "related_project_imported":
            details = (
                f"{source_label}: imported {details_obj.get('imported', 0)} lessons"
                f", rejected {details_obj.get('rejected', 0)}"
            )
        elif action_type == "related_project_attached":
            details = f"{source_label}: attached for live read-through"
        elif action_type == "related_project_unlinked":
            details = (
                f"{source_label}: unlinked, removed "
                f"{details_obj.get('deleted_snapshot_lessons', 0)} snapshot lessons"
            )
        elif action_type == "related_import_scrub":
            details = (
                f"{source_label}: scrubbed import "
                f"(accepted {details_obj.get('imported', 0)}, "
                f"rejected {len(details_obj.get('rejected', []))})"
            )
        else:
            details = str(details_obj)
    elif entity_type == "transferred_lesson":
        source_label = _source_label(str(details_obj.get("source_project_path", "") or ""))
        lesson_key = str(details_obj.get("lesson_key", "") or "")
        lesson_label = lesson_key[:8] if lesson_key else "lesson"
        if action_type == "transferred_lesson_validated":
            details = (
                f"{source_label}/{lesson_label}: validated after "
                f"{details_obj.get('success_count', 0)}/{details_obj.get('validation_count', 0)} successes"
            )
        elif action_type == "transferred_lesson_promoted":
            details = (
                f"{source_label}/{lesson_label}: promoted to local rule "
                f"#{details_obj.get('promoted_rule_id', '?')}"
            )
        elif action_type == "transferred_lesson_archived":
            details = f"{source_label}/{lesson_label}: archived ({details_obj.get('reason', '')})"
        else:
            details = str(details_obj)
    elif entity_type == "model_pack_export":
        canonical_model_key = str(details_obj.get("canonical_model_key", "") or "unknown")
        details = (
            f"{canonical_model_key}: exported {details_obj.get('lesson_count', 0)} lessons"
            f", rejected {len(details_obj.get('rejected', []))}"
        )
    else:
        details = str(details_obj) if details_obj else str(entry.get("details_json", "") or "")

    action_label = ACTION_LABELS.get(action_type, action_type)
    entity_label = ENTITY_LABELS.get(entity_type, entity_type or "—")
    if entity_type == "transferred_lesson":
        source_label = _source_label(str(details_obj.get("source_project_path", "") or ""))
        entity = (
            f"{entity_label}:{entity_id}@{source_label}"
            if entity_id
            else f"{entity_label}@{source_label}"
        )
    elif entity_type == "related_project":
        source_label = _source_label(str(details_obj.get("source_project_path", "") or ""))
        entity = f"{entity_label}:{source_label}"
    else:
        entity = f"{entity_label}:{entity_id}" if entity_id else entity_label
    return {
        "when": str(entry.get("created_at", "") or "")[:16],
        "action": action_label,
        "entity": entity,
        "details": details[:120],
    }
