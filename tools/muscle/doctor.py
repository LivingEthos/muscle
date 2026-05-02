"""
Doctor reporting for MUSCLE lifecycle and plugin diagnostics.

Architecture Decision Record (ADR):
- Keep doctor observational in this pass: it reports and can refresh state,
  but it does not mutate host installations or attempt auto-fixes.
- Reuse the active-review refresh path so status and doctor stay aligned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .active_review import ProjectRefreshResult, load_active_review_snapshot, refresh_project_state
from .optimization.importers import get_codex_home
from .project_memory import ProjectMemory
from .tui.project_manager import ProjectManager

PLUGIN_ROOT = Path(__file__).resolve().parent / "plugin"
CLAUDE_MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
CLAUDE_MARKETPLACE_PATH = PLUGIN_ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
# Two hook files are intentional: Claude Code reads ``<plugin>/hooks/hooks.json``
# (subdir convention), Codex reads ``<plugin>/hooks.json`` (top-level
# convention). Do not "dedupe" — each host expects its own location.
CLAUDE_HOOKS_PATH = PLUGIN_ROOT / "hooks" / "hooks.json"
CODEX_HOOKS_PATH = PLUGIN_ROOT / "hooks.json"
PLUGIN_COMMAND_PATTERN = re.compile(r"/muscle:([a-z0-9][a-z0-9\-]*)")


@dataclass
class DoctorCheck:
    """One doctor check result."""

    key: str
    status: str
    label: str
    detail: str


@dataclass
class DoctorReport:
    """Full doctor report payload."""

    project_path: str
    generated_at: str
    checks: list[DoctorCheck]
    refresh: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _snapshot_freshness_label(age_seconds: float | None) -> tuple[str, str]:
    if age_seconds is None:
        return "warn", "missing"
    if age_seconds < 900:
        return "ok", f"{int(age_seconds)}s old"
    if age_seconds < 86400:
        return "warn", f"{int(age_seconds // 60)}m old"
    return "warn", f"{int(age_seconds // 3600)}h old"


def _external_importer_detail(project_path: str, pm: ProjectMemory) -> tuple[str, str]:
    sessions = pm.list_external_benchmark_sessions(project_path=project_path, limit=20)
    imported_count = len(sessions)

    claude_available = (
        Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser() / "projects"
    ).exists()
    codex_available = (get_codex_home() / "sessions").exists()

    sources = []
    if claude_available:
        sources.append("claude")
    if codex_available:
        sources.append("codex")

    if imported_count:
        detail = f"{imported_count} imported session(s); sources available: {', '.join(sources) or 'none'}"
        return "ok", detail
    if sources:
        detail = f"no imported sessions yet; sources available: {', '.join(sources)}"
        return "warn", detail
    return "warn", "no Claude/Codex transcript sources detected"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_detail(paths: list[Path]) -> tuple[str, str]:
    missing = [path.name for path in paths if not path.exists()]
    if missing:
        return "fail", f"missing: {', '.join(missing)}"
    parts = [f"{path.name}:{_hash_file(path)[:12]}" for path in paths]
    return "ok", ", ".join(parts)


def _plugin_command_parity_detail() -> tuple[str, str]:
    if not CLAUDE_MANIFEST_PATH.exists():
        return "fail", "Claude manifest missing"
    try:
        manifest = json.loads(CLAUDE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "fail", "Claude manifest is invalid JSON"
    manifest_commands = set(PLUGIN_COMMAND_PATTERN.findall(str(manifest.get("description", ""))))
    filesystem_commands = {path.stem for path in (PLUGIN_ROOT / "commands").glob("*.md")}
    missing_files = sorted(manifest_commands - filesystem_commands)
    unadvertised = sorted(filesystem_commands - manifest_commands)
    if missing_files or unadvertised:
        return (
            "fail",
            f"missing files={missing_files or 'none'}; unadvertised={unadvertised or 'none'}",
        )
    return "ok", f"{len(filesystem_commands)} command docs match manifest"


def _plugin_asset_detail() -> tuple[str, str]:
    if not CODEX_MANIFEST_PATH.exists():
        return "warn", "Codex manifest missing"
    try:
        manifest = json.loads(CODEX_MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "fail", "Codex manifest is invalid JSON"
    interface = manifest.get("interface", {})
    if not isinstance(interface, dict):
        return "fail", "Codex interface block missing"
    missing: list[str] = []
    for asset_key in ("composerIcon", "logo"):
        asset_value = interface.get(asset_key)
        asset_path = PLUGIN_ROOT / str(asset_value or "")
        if not asset_value or not asset_path.exists():
            missing.append(asset_key)
    if missing:
        return "fail", f"missing asset(s): {', '.join(missing)}"
    return "ok", "Codex composer icon and logo present"


def _provider_endpoint_detail() -> tuple[str, str]:
    """Surface ANTHROPIC_BASE_URL misconfiguration (B3).

    MUSCLE's m27_client honours ``ANTHROPIC_BASE_URL`` blindly, so a user who
    already exports ``https://api.anthropic.com`` for the real Anthropic SDK
    will silently send M2.7-shaped traffic to Anthropic. Doctor reports this
    as a warning so the misconfig is visible before the first real request.
    """
    base = os.environ.get("ANTHROPIC_BASE_URL")
    if not base:
        return "ok", "default MiniMax endpoint"
    host = base.lower()
    if "minimax" in host:
        return "ok", base
    if "anthropic.com" in host:
        return (
            "warn",
            f"{base} (MiniMax client will POST to real Anthropic; "
            "unset ANTHROPIC_BASE_URL or point it at MiniMax)",
        )
    return "info", base


def _hook_runtime_degradation_detail(project_path: str) -> tuple[str, str]:
    state_path = Path(project_path) / ".muscle" / "hook-runtime.json"
    if not state_path.exists():
        return "info", "no hook degradation state recorded"
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "warn", "hook degradation state is invalid JSON"
    degraded = data.get("degraded")
    if degraded:
        reason = str(data.get("reason") or "degraded")
        return "warn", reason
    return "ok", "hook runtime healthy"


def build_doctor_report(
    project_path: str,
    *,
    refresh: bool = False,
) -> DoctorReport:
    """Build a doctor report for one project."""

    resolved_project = str(Path(project_path).resolve())
    manager = ProjectManager(base_path=Path(resolved_project))
    config = manager.load_config(Path(resolved_project))
    initialized = (Path(resolved_project) / ".muscle").exists()
    refresh_result: ProjectRefreshResult | None = None

    if refresh and initialized:
        refresh_result = refresh_project_state(
            resolved_project,
            reason="doctor-refresh",
            import_provider="all",
        )

    pm = ProjectMemory(resolved_project) if initialized else None
    snapshot = load_active_review_snapshot(resolved_project)
    snapshot_status, snapshot_detail = _snapshot_freshness_label(snapshot.get("age_seconds"))
    latest_model = pm.get_latest_model_identity(resolved_project) if pm is not None else None
    model_key = (latest_model or {}).get("canonical_model_key") or getattr(
        config,
        "canonical_model_key",
        None,
    )
    model_source = (latest_model or {}).get("identity_source") or getattr(
        config,
        "model_identity_source",
        "unresolved",
    )
    manifest_digest_status, manifest_digest_detail = _digest_detail(
        [CLAUDE_MANIFEST_PATH, CLAUDE_MARKETPLACE_PATH, CODEX_MANIFEST_PATH]
    )
    hook_digest_status, hook_digest_detail = _digest_detail([CLAUDE_HOOKS_PATH, CODEX_HOOKS_PATH])
    command_parity_status, command_parity_detail = _plugin_command_parity_detail()
    asset_status, asset_detail = _plugin_asset_detail()
    hook_runtime_status, hook_runtime_detail = _hook_runtime_degradation_detail(resolved_project)
    provider_endpoint_status, provider_endpoint_detail = _provider_endpoint_detail()

    checks = [
        DoctorCheck(
            key="project_initialized",
            status="ok" if initialized else "fail",
            label="Project Initialized",
            detail="yes" if initialized else "no",
        ),
        DoctorCheck(
            key="project_enabled",
            status="ok" if manager.is_project_enabled(Path(resolved_project)) else "warn",
            label="Project Enabled",
            detail="yes" if manager.is_project_enabled(Path(resolved_project)) else "no",
        ),
        DoctorCheck(
            key="platform",
            status="info",
            label="Selected Platform",
            detail=(config.platform if config is not None else manager.detect_platform()),
        ),
        DoctorCheck(
            key="cli_path",
            status="ok"
            if ((config and config.cli_path) or manager.detect_cli_location())
            else "warn",
            label="CLI Path",
            detail=(config.cli_path if config is not None else None)
            or manager.detect_cli_location()
            or "unresolved",
        ),
        DoctorCheck(
            key="api_key",
            status="ok"
            if os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            else "warn",
            label="API Key",
            detail="present"
            if os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            else "missing",
        ),
        DoctorCheck(
            key="provider_endpoint",
            status=provider_endpoint_status,
            label="Provider Endpoint",
            detail=provider_endpoint_detail,
        ),
        DoctorCheck(
            key="claude_manifest",
            status="ok" if CLAUDE_MANIFEST_PATH.exists() else "fail",
            label="Claude Manifest",
            detail="present" if CLAUDE_MANIFEST_PATH.exists() else "missing",
        ),
        DoctorCheck(
            key="claude_marketplace_manifest",
            status="ok" if CLAUDE_MARKETPLACE_PATH.exists() else "warn",
            label="Claude Marketplace Manifest",
            detail="present" if CLAUDE_MARKETPLACE_PATH.exists() else "missing",
        ),
        DoctorCheck(
            key="codex_manifest",
            status="ok" if CODEX_MANIFEST_PATH.exists() else "warn",
            label="Codex Manifest",
            detail="present" if CODEX_MANIFEST_PATH.exists() else "missing",
        ),
        DoctorCheck(
            key="claude_hooks",
            status="ok" if CLAUDE_HOOKS_PATH.exists() else "warn",
            label="Claude Hooks",
            detail="present" if CLAUDE_HOOKS_PATH.exists() else "missing",
        ),
        DoctorCheck(
            key="codex_hooks",
            status="ok" if CODEX_HOOKS_PATH.exists() else "warn",
            label="Codex Hooks",
            detail="present" if CODEX_HOOKS_PATH.exists() else "missing",
        ),
        DoctorCheck(
            key="plugin_manifest_digests",
            status=manifest_digest_status,
            label="Plugin Manifest Digests",
            detail=manifest_digest_detail,
        ),
        DoctorCheck(
            key="plugin_hook_digests",
            status=hook_digest_status,
            label="Plugin Hook Digests",
            detail=hook_digest_detail,
        ),
        DoctorCheck(
            key="plugin_command_docs_parity",
            status=command_parity_status,
            label="Plugin Command Docs Parity",
            detail=command_parity_detail,
        ),
        DoctorCheck(
            key="plugin_assets",
            status=asset_status,
            label="Plugin Assets",
            detail=asset_detail,
        ),
        DoctorCheck(
            key="plugin_hook_runtime",
            status=hook_runtime_status,
            label="Plugin Hook Runtime",
            detail=hook_runtime_detail,
        ),
        DoctorCheck(
            key="active_review_snapshot",
            status=snapshot_status,
            label="Active Review Snapshot",
            detail=snapshot_detail,
        ),
        DoctorCheck(
            key="model_identity",
            status="ok" if model_key else "warn",
            label="Model Identity",
            detail=f"{model_key or 'unresolved'} ({model_source})",
        ),
    ]

    if pm is not None:
        importer_status, importer_detail = _external_importer_detail(resolved_project, pm)
    else:
        importer_status, importer_detail = "warn", "project not initialized"
    checks.append(
        DoctorCheck(
            key="external_importer",
            status=importer_status,
            label="External Importer",
            detail=importer_detail,
        )
    )

    refresh_payload = None
    if refresh_result is not None:
        refresh_payload = {
            "active_review_digest": refresh_result.active_review.digest,
            "active_review_changed": refresh_result.active_review.changed,
            "catchup_digest": refresh_result.catchup.digest if refresh_result.catchup else "",
            "catchup_changed": refresh_result.catchup.changed if refresh_result.catchup else False,
            "catchup_summary": refresh_result.catchup.summary if refresh_result.catchup else "",
        }

    return DoctorReport(
        project_path=resolved_project,
        generated_at=_now_iso(),
        checks=checks,
        refresh=refresh_payload,
    )


def doctor_report_to_dict(report: DoctorReport) -> dict[str, Any]:
    """Serialize a doctor report for JSON output/tests."""

    return asdict(report)
