"""
Shared host runtime for Claude Code / Codex lifecycle hooks.

Architecture Decision Record (ADR):
- Centralize host lifecycle behavior behind one runtime entry so plugin hook
  files stay thin and CLI-callable.
- Keep runtime fail-open: degraded hook behavior should not block the host.
- Preserve the existing Claude Stop low-severity review behavior, but route
  messaging and snapshot refresh through one deduplicated path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .active_review import refresh_active_review, refresh_project_state
from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)


@dataclass
class HostHookResult:
    """Outcome returned by `run_host_hook`."""

    message: str
    digest: str
    changed: bool
    ok: bool


def _event_state_key(platform: str, event: str) -> str:
    return f"host.emit.{platform}.{event}.digest"


def _stable_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _load_digest(pm: ProjectMemory, project_path: str, key: str) -> str:
    state = pm.get_automation_state(project_path, key)
    if not state or state.get("state_value") is None:
        return ""
    return str(state["state_value"])


def _set_digest(pm: ProjectMemory, project_path: str, key: str, digest: str) -> None:
    pm.set_automation_state(project_path, key, digest)


def _format_latest_review(data: dict[str, Any]) -> str:
    latest_review = data.get("latest_review") or {}
    if not latest_review.get("exists"):
        return "no review yet"
    return (
        f"#{latest_review['id']} {latest_review['review_mode']} on "
        f"{latest_review['target_path']} ({latest_review['findings_count']} findings)"
    )


def _format_verification(data: dict[str, Any]) -> str:
    verification = data.get("verification") or {}
    if not verification.get("exists"):
        return "no verification yet"
    state = "passed" if verification.get("verification_passed") else "failed"
    return f"{state} at {verification['file_path']}:{verification['line_number']}"


def _build_session_banner(data: dict[str, Any], catchup_summary: str | None = None) -> str:
    current_state = data.get("current_state") or {}
    shadow_jobs = data.get("shadow_jobs") or {}
    actions = data.get("recommended_actions") or []
    lines = [
        "MUSCLE state",
        (
            f"- Enabled: {'yes' if current_state.get('enabled') else 'no'} | "
            f"Platform: {current_state.get('platform') or 'auto'} | "
            f"Model: {current_state.get('canonical_model_key') or 'unresolved'}"
        ),
        f"- Latest review: {_format_latest_review(data)}",
        f"- Shadow jobs: {shadow_jobs.get('active_count', 0)} active",
        f"- Verification: {_format_verification(data)}",
    ]
    if catchup_summary:
        lines.append(f"- Catchup: {catchup_summary}")
    if actions:
        lines.append(f"- Next: {actions[0]}")
    return "\n".join(lines)


def _build_prompt_reminder(data: dict[str, Any]) -> str:
    actions = data.get("recommended_actions") or []
    next_action = actions[0] if actions else "Run `muscle status --refresh` for current state."
    return f"MUSCLE active review: {_format_latest_review(data)}. Next: {next_action}"


def _run_stop_review(project_path: str) -> str | None:
    if not (os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return None

    cmd = [
        sys.executable,
        "-m",
        "tools.muscle.cli",
        "review",
        "--target",
        ".",
        "--mode",
        "review",
        "--severity",
        "low",
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=project_path,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "MUSCLE_HOST_HOOK_CONTEXT": "stop"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Claude stop review hook degraded for %s: %s", project_path, exc)
        return "stop-review-unavailable"

    if completed.returncode == 0:
        return "stop-review-ran"
    logger.warning(
        "Claude stop review exited non-zero for %s: %s",
        project_path,
        completed.stderr.strip(),
    )
    return "stop-review-failed"


def _emit_if_changed(
    pm: ProjectMemory,
    project_path: str,
    key: str,
    digest: str,
    message: str,
) -> HostHookResult:
    previous_digest = _load_digest(pm, project_path, key)
    changed = digest != previous_digest
    if changed:
        _set_digest(pm, project_path, key, digest)
    return HostHookResult(
        message=message if changed else "",
        digest=digest,
        changed=changed,
        ok=True,
    )


def run_host_hook(
    platform: str,
    event: str,
    project_path: str,
    tool_name: str | None = None,
) -> HostHookResult:
    """Run a host lifecycle hook without blocking the host on degraded state."""

    try:
        resolved_project = str(Path(project_path).resolve())
        if not (Path(resolved_project) / ".muscle").exists():
            return HostHookResult(message="", digest="", changed=False, ok=True)

        pm = ProjectMemory(resolved_project)
        event_key = _event_state_key(platform, event)

        if event == "session_start":
            refresh_result = refresh_project_state(
                resolved_project,
                reason=f"{platform}:{event}",
                import_provider="all",
            )
            digest = _stable_digest(
                {
                    "snapshot": refresh_result.active_review.digest,
                    "catchup": refresh_result.catchup.digest if refresh_result.catchup else "",
                }
            )
            message = _build_session_banner(
                refresh_result.active_review.data,
                catchup_summary=refresh_result.catchup.summary if refresh_result.catchup else None,
            )
            return _emit_if_changed(pm, resolved_project, event_key, digest, message)

        if event == "user_prompt_submit":
            active_review = refresh_active_review(resolved_project, reason=f"{platform}:{event}")
            digest = active_review.digest
            return _emit_if_changed(
                pm,
                resolved_project,
                event_key,
                digest,
                _build_prompt_reminder(active_review.data),
            )

        if event == "post_write":
            active_review = refresh_active_review(
                resolved_project,
                reason=f"{platform}:{event}:{tool_name or 'write'}",
            )
            digest = active_review.digest
            return _emit_if_changed(
                pm,
                resolved_project,
                event_key,
                digest,
                "MUSCLE refreshed its active-review snapshot after write/edit activity.",
            )

        if event == "stop":
            stop_status = _run_stop_review(resolved_project) if platform == "claude-code" else None
            active_review = refresh_active_review(resolved_project, reason=f"{platform}:{event}")
            digest = _stable_digest(
                {
                    "snapshot": active_review.digest,
                    "stop_status": stop_status or "not-run",
                }
            )
            actions = active_review.data.get("recommended_actions") or []
            message = "MUSCLE stop check refreshed."
            if actions:
                message += f" Next: {actions[0]}"
            return _emit_if_changed(pm, resolved_project, event_key, digest, message)

        return HostHookResult(message="", digest="", changed=False, ok=True)
    except Exception as exc:
        logger.warning(
            "Host hook degraded for platform=%s event=%s project=%s: %s",
            platform,
            event,
            project_path,
            exc,
        )
        return HostHookResult(
            message="MUSCLE host hook degraded; continuing without blocking the host.",
            digest="",
            changed=False,
            ok=False,
        )
