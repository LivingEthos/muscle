"""
Active review snapshot and external catchup helpers.

Architecture Decision Record (ADR):
- Keep project_memory.db authoritative and generate a bounded markdown snapshot.
- Reuse imported external benchmark turns for catchup instead of creating
  another transcript store.
- Deduplicate host-facing messages with semantic digests derived from stable
  structured payloads, not volatile timestamps or absolute paths.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .optimization import ExternalBenchmarkImporter
from .project_memory import ProjectMemory
from .tui.project_manager import ProjectManager

logger = logging.getLogger(__name__)

ACTIVE_REVIEW_FILENAME = "active-review.md"
ACTIVE_REVIEW_DIGEST_KEY = "host.active_review.digest"
CATCHUP_SUMMARY_KEY = "host.catchup.last_summary"
CATCHUP_SUMMARY_DIGEST_KEY = "host.catchup.last_summary.digest"


@dataclass
class CatchupSummary:
    """Summarized external catchup state for the current project."""

    summary: str
    digest: str
    changed: bool
    turn_count: int
    imported: dict[str, dict[str, Any]]
    providers: dict[str, dict[str, Any]]


@dataclass
class ActiveReviewUpdate:
    """Result of regenerating `.muscle/active-review.md`."""

    project_path: str
    snapshot_path: str
    digest: str
    changed: bool
    generated_at: str
    reason: str
    content: str
    data: dict[str, Any]


@dataclass
class ProjectRefreshResult:
    """Combined catchup + snapshot refresh result."""

    active_review: ActiveReviewUpdate
    catchup: CatchupSummary | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _safe_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _display_path(path_value: str | None, project_path: str) -> str:
    if not path_value:
        return "."
    path = Path(path_value)
    root = Path(project_path)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return path.name or str(path)


def _relative_cli_path(path_value: str | None) -> str:
    if not path_value:
        return "unresolved"
    if " " in path_value:
        return path_value
    return Path(path_value).name if Path(path_value).exists() else path_value


def _semantic_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _load_state_value(pm: ProjectMemory, project_path: str, key: str) -> str | None:
    state = pm.get_automation_state(project_path, key)
    if not state:
        return None
    value = state.get("state_value")
    return str(value) if value is not None else None


def _build_catchup_payload(turns: list[dict[str, Any]]) -> dict[str, Any]:
    provider_counts: dict[str, dict[str, Any]] = {}
    categories: Counter[str] = Counter()
    models: Counter[str] = Counter()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for turn in turns:
        grouped[str(turn.get("provider") or "unknown")].append(turn)
        categories[str(turn.get("category") or "unknown")] += 1
        models[str(turn.get("model") or "unknown")] += 1

    for provider_name, provider_turns in grouped.items():
        session_ids = {
            str(turn.get("external_session_id") or "")
            for turn in provider_turns
            if turn.get("external_session_id")
        }
        provider_counts[provider_name] = {
            "turns": len(provider_turns),
            "sessions": len(session_ids),
            "latest_turn_id": max(_safe_int(turn.get("id")) for turn in provider_turns),
            "categories": dict(
                Counter(str(turn.get("category") or "unknown") for turn in provider_turns)
            ),
        }

    top_categories = [
        {"name": category, "count": count}
        for category, count in categories.most_common(3)
        if category and count
    ]
    top_models = [model for model, _count in models.most_common(3) if model]

    summary_parts = []
    for provider_name in sorted(provider_counts):
        provider_info = provider_counts[provider_name]
        category_bits = ", ".join(
            f"{name} {count}"
            for name, count in Counter(provider_info["categories"]).most_common(2)
            if name
        )
        provider_label = provider_name.capitalize()
        detail = (
            f"{provider_label}: {provider_info['turns']} turns across "
            f"{provider_info['sessions']} session(s)"
        )
        if category_bits:
            detail += f" [{category_bits}]"
        summary_parts.append(detail)

    payload = {
        "summary": "; ".join(summary_parts) if summary_parts else "No new external catchup.",
        "turn_count": len(turns),
        "providers": provider_counts,
        "top_categories": top_categories,
        "top_models": top_models,
    }
    return payload


def refresh_external_catchup(
    project_path: str,
    provider: str = "all",
    *,
    since_days: int = 30,
    import_new: bool = True,
) -> CatchupSummary:
    """Import and summarize newly imported external turns for one project."""

    resolved_project = str(Path(project_path).resolve())
    pm = ProjectMemory(resolved_project)
    importer = ExternalBenchmarkImporter(pm, resolved_project)
    imported = (
        importer.import_sessions_with_deltas(provider=provider, since_days=since_days)
        if import_new
        else {}
    )

    provider_names = ["claude", "codex"] if provider == "all" else [provider]
    new_turns: list[dict[str, Any]] = []
    latest_turn_ids: dict[str, int] = {}

    for provider_name in provider_names:
        last_turn_id = _safe_int(
            _load_state_value(pm, resolved_project, f"host.sync.{provider_name}.last_turn_id")
        )
        provider_turns = pm.list_external_benchmark_turns(
            resolved_project,
            provider=provider_name,
            min_turn_id=last_turn_id,
            limit=400,
        )
        if not provider_turns:
            continue
        new_turns.extend(provider_turns)
        latest_turn_ids[provider_name] = max(_safe_int(turn.get("id")) for turn in provider_turns)

    for provider_name, latest_turn_id in latest_turn_ids.items():
        pm.set_automation_state(
            resolved_project,
            f"host.sync.{provider_name}.last_turn_id",
            str(latest_turn_id),
        )

    previous_digest = _load_state_value(pm, resolved_project, CATCHUP_SUMMARY_DIGEST_KEY) or ""
    previous_payload = _safe_json_loads(
        _load_state_value(pm, resolved_project, CATCHUP_SUMMARY_KEY)
    )

    if not new_turns:
        previous_summary = str(
            previous_payload.get("summary") or "No external catchup recorded yet."
        )
        previous_providers = previous_payload.get("providers")
        providers = previous_providers if isinstance(previous_providers, dict) else {}
        return CatchupSummary(
            summary=previous_summary,
            digest=previous_digest,
            changed=False,
            turn_count=_safe_int(previous_payload.get("turn_count")),
            imported=imported,
            providers=providers,
        )

    payload = _build_catchup_payload(new_turns)
    digest = _semantic_digest(payload)
    pm.set_automation_state(
        resolved_project,
        CATCHUP_SUMMARY_KEY,
        json.dumps(payload, sort_keys=True),
    )
    pm.set_automation_state(resolved_project, CATCHUP_SUMMARY_DIGEST_KEY, digest)
    return CatchupSummary(
        summary=str(payload["summary"]),
        digest=digest,
        changed=digest != previous_digest,
        turn_count=_safe_int(payload.get("turn_count")),
        imported=imported,
        providers=dict(payload.get("providers") or {}),
    )


def _build_current_state(
    project_path: str,
    project_config: Any | None,
    pm: ProjectMemory,
) -> dict[str, Any]:
    manager = ProjectManager(base_path=Path(project_path))
    latest_model = pm.get_latest_model_identity(project_path)
    return {
        "project": getattr(project_config, "name", Path(project_path).name),
        "initialized": bool((Path(project_path) / ".muscle").exists()),
        "enabled": manager.is_project_enabled(Path(project_path)),
        "platform": getattr(project_config, "platform", "auto"),
        "hooks_enabled": bool(getattr(project_config, "hooks_enabled", True)),
        "review_execution": getattr(project_config, "review_execution", "local"),
        "cli_path": getattr(project_config, "cli_path", None) or manager.detect_cli_location(),
        "canonical_model_key": (
            (latest_model or {}).get("canonical_model_key")
            or getattr(project_config, "canonical_model_key", None)
        ),
        "model_identity_source": (
            (latest_model or {}).get("identity_source")
            or getattr(project_config, "model_identity_source", "unresolved")
        ),
    }


def _build_latest_review(pm: ProjectMemory, project_path: str) -> dict[str, Any]:
    latest_review = pm.get_latest_review_run(project_path)
    if latest_review is None:
        return {"exists": False}

    findings = pm.list_findings_for_run(_safe_int(latest_review.get("id")))
    severity_counts = Counter(str(item.get("severity") or "").lower() for item in findings)
    return {
        "exists": True,
        "id": _safe_int(latest_review.get("id")),
        "review_mode": str(latest_review.get("review_mode") or "review"),
        "target_path": _display_path(str(latest_review.get("target_path") or "."), project_path),
        "created_at": str(latest_review.get("created_at") or ""),
        "findings_count": _safe_int(latest_review.get("findings_count")),
        "token_cost": _safe_int(latest_review.get("token_cost")),
        "duration_ms": _safe_int(latest_review.get("duration_ms")),
        "severity_counts": {
            severity: count for severity, count in severity_counts.items() if severity and count
        },
    }


def _build_shadow_jobs(pm: ProjectMemory, project_path: str) -> dict[str, Any]:
    active_jobs = pm.get_active_shadow_jobs(project_path)
    recent_jobs = pm.list_shadow_jobs(project_path=project_path, limit=3)
    return {
        "active_count": len(active_jobs),
        "active_jobs": [
            {
                "job_id": str(job.get("job_id") or ""),
                "status": str(job.get("status") or "unknown"),
                "target_path": _display_path(str(job.get("target_path") or "."), project_path),
                "created_at": str(job.get("created_at") or ""),
            }
            for job in active_jobs[:3]
        ],
        "recent_jobs": [
            {
                "job_id": str(job.get("job_id") or ""),
                "status": str(job.get("status") or "unknown"),
                "target_path": _display_path(str(job.get("target_path") or "."), project_path),
                "created_at": str(job.get("created_at") or ""),
            }
            for job in recent_jobs[:3]
        ],
    }


def _build_verification(pm: ProjectMemory, project_path: str) -> dict[str, Any]:
    verification = pm.get_latest_verification_summary(project_path)
    if verification is None:
        return {"exists": False}
    return {
        "exists": True,
        "created_at": str(verification.get("created_at") or ""),
        "verification_passed": bool(_safe_int(verification.get("verification_passed"))),
        "notes": str(verification.get("notes") or ""),
        "review_run_id": _safe_int(verification.get("review_run_id")),
        "review_mode": str(verification.get("review_mode") or ""),
        "target_path": _display_path(str(verification.get("target_path") or "."), project_path),
        "file_path": _display_path(str(verification.get("file_path") or "."), project_path),
        "line_number": _safe_int(verification.get("line_number")),
        "severity": str(verification.get("severity") or "").lower(),
    }


def _build_external_catchup(pm: ProjectMemory, project_path: str) -> dict[str, Any]:
    payload = _safe_json_loads(_load_state_value(pm, project_path, CATCHUP_SUMMARY_KEY))
    digest = _load_state_value(pm, project_path, CATCHUP_SUMMARY_DIGEST_KEY) or ""
    sessions = pm.list_external_benchmark_sessions(project_path=project_path, limit=5)
    return {
        "summary": str(payload.get("summary") or "No external catchup recorded yet."),
        "digest": digest,
        "turn_count": _safe_int(payload.get("turn_count")),
        "providers": payload.get("providers") if isinstance(payload.get("providers"), dict) else {},
        "session_count": len(sessions),
    }


def _build_recommended_actions(
    current_state: dict[str, Any],
    latest_review: dict[str, Any],
    shadow_jobs: dict[str, Any],
    verification: dict[str, Any],
    external_catchup: dict[str, Any],
) -> list[str]:
    actions: list[str] = []

    if not current_state.get("enabled"):
        actions.append("Run `muscle enable` to re-enable project-local automation state.")
    if shadow_jobs.get("active_count"):
        actions.append("Run `muscle probe` to inspect active shadow jobs.")
        recent_jobs = shadow_jobs.get("recent_jobs") or []
        if recent_jobs:
            actions.append("Run `muscle diagnosis` when the current shadow job completes.")
    if not latest_review.get("exists"):
        actions.append("Run `muscle review --target .` to create a fresh baseline review.")
    if verification.get("exists") and not verification.get("verification_passed"):
        actions.append(
            "Run `muscle review --target . --mode hybrid --execution worktree` "
            "to revisit the last failed verification safely."
        )
    if current_state.get("model_identity_source") == "unresolved":
        actions.append(
            "Run `muscle model select --canonical-model <model-key>` if the backing model is known."
        )
    if not external_catchup.get("session_count"):
        actions.append(
            "Run `muscle optimize import --provider all` to seed external benchmark data."
        )
    if not actions:
        actions.append("Run `muscle status --refresh` after substantive review or fix activity.")
    return actions[:4]


def _render_snapshot(data: dict[str, Any], generated_at: str, reason: str) -> str:
    current_state = data["current_state"]
    latest_review = data["latest_review"]
    shadow_jobs = data["shadow_jobs"]
    verification = data["verification"]
    external_catchup = data["external_catchup"]
    recommended_actions = data["recommended_actions"]

    current_lines = [
        f"- Project: `{current_state['project']}`",
        f"- Enabled: `{'yes' if current_state['enabled'] else 'no'}`",
        f"- Platform: `{current_state['platform']}`",
        f"- Hooks: `{'enabled' if current_state['hooks_enabled'] else 'disabled'}`",
        f"- Review execution: `{current_state['review_execution']}`",
        f"- CLI path: `{_relative_cli_path(current_state.get('cli_path'))}`",
        "- Model identity: "
        f"`{current_state.get('canonical_model_key') or 'unresolved'}` "
        f"({current_state.get('model_identity_source') or 'unresolved'})",
    ]

    if latest_review.get("exists"):
        severity_bits = ", ".join(
            f"{severity} {count}"
            for severity, count in sorted((latest_review.get("severity_counts") or {}).items())
        )
        latest_review_lines = [
            f"- Run: `#{latest_review['id']}` `{latest_review['review_mode']}` "
            f"on `{latest_review['target_path']}`",
            f"- Created: `{_format_timestamp(latest_review['created_at'])}`",
            f"- Findings: `{latest_review['findings_count']}`",
            f"- Token cost: `{latest_review['token_cost']}`",
            f"- Duration: `{latest_review['duration_ms']} ms`",
        ]
        if severity_bits:
            latest_review_lines.append(f"- Severity mix: `{severity_bits}`")
    else:
        latest_review_lines = ["- No review runs recorded yet."]

    active_jobs = shadow_jobs.get("active_jobs") or []
    if active_jobs:
        shadow_lines = [f"- Active jobs: `{shadow_jobs['active_count']}`"]
        for job in active_jobs:
            shadow_lines.append(
                f"- `{job['job_id']}` `{job['status']}` on `{job['target_path']}` "
                f"({_format_timestamp(job['created_at'])})"
            )
    else:
        recent_jobs = shadow_jobs.get("recent_jobs") or []
        if recent_jobs:
            shadow_lines = ["- No active jobs. Recent:"]
            for job in recent_jobs:
                shadow_lines.append(
                    f"- `{job['job_id']}` `{job['status']}` on `{job['target_path']}` "
                    f"({_format_timestamp(job['created_at'])})"
                )
        else:
            shadow_lines = ["- No shadow jobs recorded."]

    if verification.get("exists"):
        verification_lines = [
            "- Latest verification: "
            f"`{'passed' if verification['verification_passed'] else 'failed'}`",
            f"- Review run: `#{verification['review_run_id']}` `{verification['review_mode']}` "
            f"on `{verification['target_path']}`",
            f"- Finding location: `{verification['file_path']}:{verification['line_number']}`",
            f"- Recorded: `{_format_timestamp(verification['created_at'])}`",
        ]
        if verification.get("notes"):
            verification_lines.append(f"- Notes: `{verification['notes'][:160]}`")
    else:
        verification_lines = ["- No verification attempts recorded."]

    external_lines = [
        f"- Summary: {external_catchup['summary']}",
        f"- Imported session count: `{external_catchup['session_count']}`",
        f"- Catchup digest: `{external_catchup.get('digest') or 'none'}`",
    ]

    action_lines = [f"- {action}" for action in recommended_actions]

    return "\n".join(
        [
            "# Active Review Snapshot",
            "",
            f"Generated: `{generated_at}`",
            f"Reason: `{reason}`",
            (
                "Authoritative sources: `project_memory.db`, `.muscle/packs/`, review artifacts, "
                "and published memory. This file is generated convenience output only."
            ),
            "",
            "## Current State",
            *current_lines,
            "",
            "## Latest Review",
            *latest_review_lines,
            "",
            "## Shadow Jobs",
            *shadow_lines,
            "",
            "## Verification",
            *verification_lines,
            "",
            "## External Catchup",
            *external_lines,
            "",
            "## Recommended Actions",
            *action_lines,
            "",
        ]
    )


def refresh_active_review(project_path: str, reason: str) -> ActiveReviewUpdate:
    """Regenerate `.muscle/active-review.md` from project DB + config state."""

    resolved_project = str(Path(project_path).resolve())
    manager = ProjectManager(base_path=Path(resolved_project))
    project_config = manager.load_config(Path(resolved_project))
    pm = ProjectMemory(resolved_project)

    current_state = _build_current_state(resolved_project, project_config, pm)
    latest_review = _build_latest_review(pm, resolved_project)
    shadow_jobs = _build_shadow_jobs(pm, resolved_project)
    verification = _build_verification(pm, resolved_project)
    external_catchup = _build_external_catchup(pm, resolved_project)
    recommended_actions = _build_recommended_actions(
        current_state,
        latest_review,
        shadow_jobs,
        verification,
        external_catchup,
    )

    data = {
        "current_state": current_state,
        "latest_review": latest_review,
        "shadow_jobs": shadow_jobs,
        "verification": verification,
        "external_catchup": external_catchup,
        "recommended_actions": recommended_actions,
    }
    digest = _semantic_digest(data)
    previous_digest = _load_state_value(pm, resolved_project, ACTIVE_REVIEW_DIGEST_KEY) or ""
    generated_at = _now_iso()
    content = _render_snapshot(data, generated_at=generated_at, reason=reason)

    snapshot_path = Path(resolved_project) / ".muscle" / ACTIVE_REVIEW_FILENAME
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(content, encoding="utf-8")
    pm.set_automation_state(resolved_project, ACTIVE_REVIEW_DIGEST_KEY, digest)

    return ActiveReviewUpdate(
        project_path=resolved_project,
        snapshot_path=str(snapshot_path),
        digest=digest,
        changed=digest != previous_digest,
        generated_at=generated_at,
        reason=reason,
        content=content,
        data=data,
    )


def refresh_project_state(
    project_path: str,
    reason: str,
    *,
    import_provider: str | None = None,
    since_days: int = 30,
) -> ProjectRefreshResult:
    """Refresh external catchup first when requested, then regenerate the snapshot."""

    catchup: CatchupSummary | None = None
    if import_provider:
        try:
            catchup = refresh_external_catchup(
                project_path,
                provider=import_provider,
                since_days=since_days,
                import_new=True,
            )
        except Exception as exc:
            logger.warning("External catchup refresh failed for %s: %s", project_path, exc)

    active_review = refresh_active_review(project_path, reason=reason)
    return ProjectRefreshResult(active_review=active_review, catchup=catchup)


def snapshot_age_seconds(project_path: str) -> float | None:
    """Return the age of `.muscle/active-review.md` in seconds, if present."""

    snapshot_path = Path(project_path).resolve() / ".muscle" / ACTIVE_REVIEW_FILENAME
    if not snapshot_path.exists():
        return None
    return max(0.0, datetime.now().timestamp() - snapshot_path.stat().st_mtime)


def load_active_review_snapshot(project_path: str) -> dict[str, Any]:
    """Return the latest snapshot metadata for reporting surfaces."""

    resolved_project = str(Path(project_path).resolve())
    snapshot_path = Path(resolved_project) / ".muscle" / ACTIVE_REVIEW_FILENAME
    if not snapshot_path.parent.exists():
        return {
            "path": str(snapshot_path),
            "exists": False,
            "digest": "",
            "age_seconds": None,
            "catchup_summary": {},
            "catchup_digest": "",
        }
    pm = ProjectMemory(resolved_project)
    return {
        "path": str(snapshot_path),
        "exists": snapshot_path.exists(),
        "digest": _load_state_value(pm, resolved_project, ACTIVE_REVIEW_DIGEST_KEY) or "",
        "age_seconds": snapshot_age_seconds(resolved_project),
        "catchup_summary": _safe_json_loads(
            _load_state_value(pm, resolved_project, CATCHUP_SUMMARY_KEY)
        ),
        "catchup_digest": _load_state_value(pm, resolved_project, CATCHUP_SUMMARY_DIGEST_KEY) or "",
    }


def active_review_to_dict(update: ActiveReviewUpdate) -> dict[str, Any]:
    """Serialize an active review update for JSON output/tests."""

    return asdict(update)
