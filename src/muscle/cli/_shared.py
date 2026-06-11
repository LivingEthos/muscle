"""Shared CLI state: console, helpers, and the root ``cli`` group.

Imported by every command submodule. Imports only non-CLI modules to
avoid import cycles.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    import orjson  # type: ignore[import-not-found]

    _HAS_ORJSON = True
except ImportError:
    _HAS_ORJSON = False

import click
from rich.console import Console
from rich.table import Table

from ..active_review import (
    refresh_active_review,
    refresh_project_state,
)
from ..backup_manager import BackupManager
from ..lesson_resolver import LessonResolver
from ..loop_controller import LoopEvent
from ..m27_client import DEFAULT_MODEL, M27Client
from ..model_identity import ModelIdentityResolver
from ..model_packs import ModelPackManager
from ..optimization import (
    ContextBudgeter,
    TelemetryRecorder,
    WorkflowOptimizer,
)
from ..optimization.context_budgeter import (
    DEFAULT_ESCALATION_LINE_BUDGET,
    LARGE_WINDOW_ESCALATION_LINE_BUDGET,
)
from ..project_fingerprint import (
    build_project_fingerprint,
    explain_relatedness,
    fingerprint_from_row,
)
from ..project_memory import ProjectMemory
from ..providers import create_client
from ..strategy_kb import GlobalKnowledgeBase
from ..system_db import DEFAULT_SYSTEM_DB_PATH, SystemDatabase
from ..types import BudgetMode, EvalMode, SessionReport, SessionStatus
from ..visual_devflow import VisualDevFlowBridge

console = Console()

MAX_TASK_LENGTH = 10000
MAX_TIMEOUT_SECONDS = 86400
MAX_TASK_PREVIEW_LENGTH = 60


def _resolve_log_level() -> int:
    """Resolve the root log level from MUSCLE_LOG_LEVEL, defaulting to WARNING.

    Accepts standard level names (case-insensitive). Falls back to WARNING for
    unset or unrecognized values so first runs stay quiet by default.
    """
    raw = os.environ.get("MUSCLE_LOG_LEVEL")
    if raw:
        resolved = logging.getLevelName(raw.strip().upper())
        if isinstance(resolved, int):
            return resolved
    return logging.WARNING


logging.basicConfig(
    level=_resolve_log_level(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

TRANSFER_AUDIT_ACTIONS = [
    "related_project_imported",
    "related_project_attached",
    "related_project_unlinked",
    "related_import_scrub",
    "transferred_lesson_validated",
    "transferred_lesson_promoted",
    "transferred_lesson_archived",
]
RELEASE_GATE_TEST_TARGETS = [
    "tests/unit/test_cli_run_offline.py",
    "tests/unit/test_cli_review.py::TestReviewCommand::test_review_does_not_trigger_remote_model_pack_fetch",
    "tests/unit/test_cross_project_learning.py::test_lesson_resolver_uses_remote_installed_pack_without_fetch",
]


def _print_backup_scope_note(backup_manager: BackupManager) -> None:
    """Print one concise note about project-local vs global MUSCLE backups."""
    scope = backup_manager.describe_backup_scope(DEFAULT_SYSTEM_DB_PATH)
    excluded = scope.get("excluded_paths", [])
    if not isinstance(excluded, list) or not excluded:
        return
    global_entry = excluded[0]
    if not isinstance(global_entry, dict):
        return
    global_path = global_entry.get("path")
    if not isinstance(global_path, str):
        return
    console.print(
        "[dim]Project backups cover project-local `.muscle/` state only. "
        f"Global shared MUSCLE state at `{global_path}` is not included; "
        "back it up separately if you need cross-project, model-pack, or submission metadata.[/dim]"
    )


def _resolve_project_context(start_path: Path | None = None) -> tuple[Path, Any]:
    from ..tui.project_manager import ProjectManager

    base_path = (start_path or Path.cwd()).resolve()
    manager = ProjectManager(base_path=base_path)
    config = manager.load_nearest_config(base_path)
    if config is not None:
        return config.path, config

    project_path = manager.find_nearest_project_path(base_path)
    if project_path is not None:
        return project_path, manager.load_config(project_path)

    fallback = base_path.parent if base_path.is_file() else base_path
    return fallback, None


def _resolve_review_execution_mode(
    target_path: Path,
    cli_execution_mode: str | None,
) -> tuple[str, Path, Any]:
    project_path, project_config = _resolve_project_context(target_path)
    if cli_execution_mode:
        return cli_execution_mode, project_path, project_config
    if project_config is not None:
        return project_config.review_execution, project_path, project_config
    return "local", project_path, project_config


def _create_m27_client() -> M27Client:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    return create_client(api_key=api_key, project_path=Path.cwd())


def _build_context_budgeter(settings: dict[str, str]) -> ContextBudgeter:
    # MiniMax-M3's 1M context window can afford a larger escalated whole-file
    # slice than smaller-window models. The compact base budget is unchanged;
    # only the escalation ceiling scales with the active model.
    escalation = (
        LARGE_WINDOW_ESCALATION_LINE_BUDGET
        if "m3" in _requested_model_label().lower()
        else DEFAULT_ESCALATION_LINE_BUDGET
    )
    return ContextBudgeter(
        review_strategy=settings.get("optimize.context.semantic_review"),
        fix_strategy=settings.get("optimize.context.fix_generation"),
        escalation_line_budget=escalation,
    )


def _requested_model_label() -> str:
    return (
        os.environ.get("ANTHROPIC_MODEL")
        or os.environ.get("MINIMAX_MODEL")
        or os.environ.get("MUSCLE_MODEL")
        or DEFAULT_MODEL
    )


def _provider_endpoint() -> str | None:
    return os.environ.get("ANTHROPIC_BASE_URL")


def _emit_json(data: object) -> None:
    """Emit machine JSON without Rich wrapping or styling."""

    click.echo(json.dumps(data, indent=2))


def _refresh_project_state_safe(
    project_path: str | Path,
    reason: str,
    *,
    import_provider: str | None = None,
) -> None:
    """Refresh active-review state without failing the invoking command."""

    project_root = Path(project_path).resolve()
    if not (project_root / ".muscle").exists():
        return
    try:
        refresh_project_state(
            str(project_root),
            reason=reason,
            import_provider=import_provider,
        )
    except Exception as exc:
        logger.warning("Active review refresh failed for %s: %s", project_path, exc)


def _refresh_active_review_safe(project_path: str | Path, reason: str) -> None:
    """Regenerate `.muscle/active-review.md` without surfacing refresh failures."""

    project_root = Path(project_path).resolve()
    if not (project_root / ".muscle").exists():
        return
    try:
        refresh_active_review(str(project_root), reason=reason)
    except Exception as exc:
        logger.warning("Active review snapshot refresh failed for %s: %s", project_path, exc)


def _format_snapshot_age(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "missing"
    if age_seconds < 60:
        return f"{int(age_seconds)}s old"
    if age_seconds < 3600:
        return f"{int(age_seconds // 60)}m old"
    if age_seconds < 86400:
        return f"{int(age_seconds // 3600)}h old"
    return f"{int(age_seconds // 86400)}d old"


def _render_doctor_report(report: Any) -> None:
    table = Table(title="MUSCLE Doctor")
    table.add_column("Status", style="cyan")
    table.add_column("Check", style="white")
    table.add_column("Detail", style="green")

    status_label = {
        "ok": "[green]OK[/green]",
        "warn": "[yellow]WARN[/yellow]",
        "fail": "[red]FAIL[/red]",
        "info": "[cyan]INFO[/cyan]",
    }

    for check in report.checks:
        table.add_row(
            status_label.get(check.status, check.status.upper()),
            check.label,
            check.detail,
        )

    console.print(table)
    if report.refresh:
        console.print(
            "[dim]Refresh: "
            f"snapshot {'changed' if report.refresh.get('active_review_changed') else 'unchanged'}; "
            f"catchup {'changed' if report.refresh.get('catchup_changed') else 'unchanged'}"
            "[/dim]"
        )


def _render_savings_report(report: dict[str, Any]) -> None:
    """Render savings report for humans."""
    table = Table(title="MUSCLE Savings")
    table.add_column("Area", style="cyan")
    table.add_column("Value", style="green")

    llm = report.get("llm_calls", {})
    commands = report.get("command_evidence", {})
    totals = report.get("totals", {})
    table.add_row("LLM Calls", str(llm.get("count", 0)))
    table.add_row("LLM Tokens", str(llm.get("total_tokens", 0)))
    table.add_row("Prompt Compaction Saved", str(llm.get("prompt_compaction_tokens_saved", 0)))
    table.add_row("Cache Tokens", str(llm.get("cache_tokens", 0)))
    table.add_row("Command Evidence Runs", str(commands.get("count", 0)))
    table.add_row("Command Compaction Saved", str(commands.get("tokens_saved_estimate", 0)))
    table.add_row("Parser Tiers", json.dumps(commands.get("parser_tier_counts", {})))
    table.add_row("Total Saved Estimate", str(totals.get("tokens_saved_estimate", 0)))
    console.print(table)

    stages = report.get("high_cost_stages") or []
    if stages:
        stage_table = Table(title="High-Cost Stages")
        stage_table.add_column("Stage")
        stage_table.add_column("Calls")
        stage_table.add_column("Tokens")
        for row in stages:
            stage_table.add_row(
                str(row.get("stage") or "unknown"),
                str(row.get("call_count") or 0),
                str(row.get("total_tokens") or 0),
            )
        console.print(stage_table)


def _render_discovery_report(report: dict[str, Any]) -> None:
    """Render discovery report for humans."""
    summary = report.get("summary", {})
    table = Table(title="MUSCLE Discovery")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Imported Turns Scanned", str(summary.get("imported_turns_scanned", 0)))
    table.add_row("Review Runs Seen", str(summary.get("review_runs_seen", 0)))
    table.add_row("Open Finding Files", str(summary.get("open_finding_files", 0)))
    table.add_row("Opportunities", str(summary.get("opportunity_count", 0)))
    console.print(table)

    opportunities = report.get("opportunities") or []
    if not opportunities:
        console.print("[green]No missed MUSCLE opportunities found.[/green]")
        return
    opp_table = Table(title="Opportunities")
    opp_table.add_column("Severity")
    opp_table.add_column("Type")
    opp_table.add_column("Message")
    for item in opportunities:
        opp_table.add_row(
            str(item.get("severity") or "info"),
            str(item.get("type") or "unknown"),
            str(item.get("message") or ""),
        )
    console.print(opp_table)


def _render_foresight_report(report: dict[str, Any]) -> None:
    """Render a concise foresight report for humans."""

    status = str(report.get("status") or "unknown")
    if report.get("short_term_written"):
        console.print("[green]Foresight preflight written[/green]")
        console.print(f"Short-term file: {report.get('short_term_path')}")
    elif status == "not-initialized":
        console.print("[yellow]Foresight preflight generated but not persisted[/yellow]")
    else:
        console.print("[cyan]Foresight preflight preview[/cyan]")

    for warning in report.get("warnings") or []:
        console.print(f"[yellow]WARN[/yellow] {warning}")

    target = report.get("target") or {}
    memory = report.get("memory") or {}
    table = Table(title="MUSCLE Foresight")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Project", str(report.get("project_path") or ""))
    table.add_row("Target", str(target.get("display_path") or target.get("path") or ""))
    table.add_row("Target Exists", "yes" if target.get("exists") else "no")
    table.add_row("Memory Status", str(memory.get("status") or "unknown"))
    table.add_row("Network Required", "no")
    console.print(table)

    actions = report.get("preflight") or []
    if actions:
        console.print("[bold]Preflight[/bold]")
        for idx, action in enumerate(actions, start=1):
            console.print(f"{idx}. {action}")


def _resolve_model_identity(
    project_path: str,
    project_config: Any | None,
    project_memory: ProjectMemory | None = None,
    system_db: SystemDatabase | None = None,
) -> dict[str, Any]:
    system_store = system_db or SystemDatabase()
    resolver = ModelIdentityResolver(system_store)
    identity = resolver.resolve(
        requested_label=_requested_model_label(),
        provider_endpoint=_provider_endpoint(),
        manual_override=getattr(project_config, "model_manual_override", None),
    )
    pm = project_memory or ProjectMemory(project_path)
    pm.insert_model_identity_history(project_path, identity.__dict__)
    return identity.__dict__


def _build_lesson_resolver(
    project_path: str,
    project_config: Any | None,
    project_memory: ProjectMemory | None = None,
    system_db: SystemDatabase | None = None,
) -> tuple[LessonResolver, dict[str, Any], SystemDatabase]:
    pm = project_memory or ProjectMemory(project_path)
    system_store = system_db or SystemDatabase()
    identity = _resolve_model_identity(
        project_path=project_path,
        project_config=project_config,
        project_memory=pm,
        system_db=system_store,
    )
    resolver = LessonResolver(
        project_path=project_path,
        project_memory=pm,
        system_db=system_store,
        global_kb=GlobalKnowledgeBase(),
        project_config=project_config,
        requested_model_label=str(identity.get("requested_label") or _requested_model_label()),
        provider_endpoint=str(identity.get("provider_endpoint") or _provider_endpoint() or ""),
    )
    return resolver, identity, system_store


def _suggest_related_projects(
    project_path: Path,
    project_config: Any | None,
    system_db: SystemDatabase | None = None,
    limit: int = 3,
    threshold: float = 0.35,
    refresh_current: bool = False,
    prune_stale: bool = False,
    stale_days: int = 90,
    include_stale: bool = False,
) -> list[dict[str, Any]]:
    system_store = system_db or SystemDatabase()
    current_fp = build_project_fingerprint(
        project_path,
        display_name=getattr(project_config, "name", project_path.name),
        languages=getattr(project_config, "languages", None),
    )
    if refresh_current:
        system_store.register_project(current_fp)
    if prune_stale:
        system_store.prune_registered_projects(
            stale_after_days=stale_days,
            keep_paths=[str(project_path.resolve())],
        )
    candidates: list[dict[str, Any]] = []
    for row in system_store.list_registered_projects(
        exclude_path=str(project_path.resolve()),
        stale_after_days=stale_days,
        include_stale=include_stale,
    ):
        candidate_fp = fingerprint_from_row(row)
        explanation = explain_relatedness(current_fp, candidate_fp)
        score = float(explanation["score"])
        if score < threshold:
            continue
        candidates.append(
            {
                "project_path": candidate_fp.project_path,
                "display_name": candidate_fp.display_name,
                "score": score,
                "languages": candidate_fp.languages,
                "frameworks": candidate_fp.frameworks,
                "why": explanation["summary"],
                "overlap": explanation["overlap"],
                "component_scores": explanation["component_scores"],
                "shared_total": explanation["shared_total"],
                "stale": bool(row.get("stale")),
                "age_days": row.get("age_days"),
            }
        )
    candidates.sort(
        key=lambda item: (
            -float(item["score"]),
            -int(item.get("shared_total", 0) or 0),
            str(item["display_name"]).lower(),
            str(item["project_path"]).lower(),
        )
    )
    return candidates[:limit]


def _attach_optimization_runtime(
    project_path: str,
    m27_client: M27Client,
) -> tuple[
    ProjectMemory | None,
    WorkflowOptimizer | None,
    ContextBudgeter | None,
    TelemetryRecorder | None,
    LessonResolver | None,
    dict[str, Any] | None,
    SystemDatabase | None,
]:
    try:
        pm = ProjectMemory(project_path)
        optimizer = WorkflowOptimizer(pm, project_path)
        settings = optimizer.get_applied_settings()
        context_budgeter = _build_context_budgeter(settings)
        recorder = TelemetryRecorder(pm)
        m27_client.set_telemetry_sink(recorder)
        project_config = _resolve_project_context(Path(project_path))[1]
        lesson_resolver, identity, system_db = _build_lesson_resolver(
            project_path=project_path,
            project_config=project_config,
            project_memory=pm,
        )
        m27_client.set_model_identity(identity)
        try:
            manager = ModelPackManager(project_path)
            m27_client._cache_pack_id = manager.get_active_pack_id(  # noqa: SLF001
                str(identity.get("canonical_model_key")) if identity else None
            )
        except Exception:
            logger.debug("Model-pack cache key wiring unavailable", exc_info=True)
        return pm, optimizer, context_budgeter, recorder, lesson_resolver, identity, system_db
    except Exception as exc:
        logger.warning("Optimization runtime disabled for %s: %s", project_path, exc)
        return None, None, None, None, None, None, None


def _resolve_stage_totals(
    project_memory: ProjectMemory | None,
    project_path: str,
    session_id: str,
) -> dict[str, int]:
    if project_memory is None:
        return {}
    calls = project_memory.list_llm_calls(
        project_path=project_path, session_id=session_id, limit=5000
    )
    totals: dict[str, int] = {}
    for call in calls:
        stage = str(call.get("stage") or "unknown")
        totals[stage] = (
            totals.get(stage, 0)
            + int(call.get("input_tokens", 0) or 0)
            + int(call.get("output_tokens", 0) or 0)
        )
    return totals


@dataclass
class _StreamingState:
    chunks: list[str] = field(default_factory=list)


def _event_handler(
    event: LoopEvent,
    data: dict,
    state: _StreamingState,
    visual_bridge: VisualDevFlowBridge | None = None,
) -> None:
    if visual_bridge is not None:
        visual_bridge.handle_loop_event(event, data)
    if event == LoopEvent.ITERATION_START:
        state.chunks = []
        console.print(f"\n[cyan]Iteration {data['iteration']}[/cyan]")
    elif event == LoopEvent.GENERATION_STREAM:
        chunk = data.get("chunk", "")
        if chunk:
            state.chunks.append(chunk)
    elif event == LoopEvent.GENERATION_END:
        state.chunks = []
        console.print(f"  Generated (tokens: {data.get('tokens', 0)})")
    elif event == LoopEvent.EVALUATION_END:
        if data.get("passed"):
            console.print("  [green]Evaluation PASSED[/green]")
        else:
            console.print(f"  [red]Evaluation failed ({data.get('errors', 0)} errors)[/red]")
    elif event == LoopEvent.EVALUATION_START:
        if data.get("eval_mode") == EvalMode.PARALLEL:
            console.print("  [cyan]Running compiler, tests, linter in parallel...[/cyan]")
    elif event == LoopEvent.EVOLUTION_END:
        console.print(f"  Evolved strategy (tokens: {data.get('tokens', 0)})")
    elif event == LoopEvent.SESSION_COMPLETE:
        status = data.get("status", "unknown")
        reason = data.get("reason", "")
        if status == SessionStatus.SUCCESS.value:
            console.print("\n[bold green]SUCCESS![/bold green] Session complete")
        else:
            console.print(f"\n[bold red]FAILED[/bold red] {reason}")
    elif event == LoopEvent.BUDGET_WARNING:
        console.print(
            f"[yellow]Budget warning at iteration {data['iteration']}: {data['total_tokens']} tokens used[/yellow]"
        )


def _create_event_handler(
    visual_bridge: VisualDevFlowBridge | None = None,
) -> tuple[_StreamingState, Any]:
    state = _StreamingState()

    def handler(event: LoopEvent, data: dict) -> None:
        _event_handler(event, data, state, visual_bridge)

    return state, handler


def _read_session_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _parse_since(since_str: str) -> timedelta:
    """Parse a human-friendly duration like '7d', '14d', '30d'."""
    unit = since_str[-1].lower()
    value = int(since_str[:-1])
    if unit == "d":
        return timedelta(days=value)
    if unit == "h":
        return timedelta(hours=value)
    raise click.BadParameter(f"Unsupported duration unit '{unit}'. Use 'd' (days) or 'h' (hours).")


def _session_report_to_dict(report: SessionReport) -> dict:
    from ..types import BudgetInfo, CodeArtifact, IterationReport

    def iter_report_to_dict(ir: IterationReport) -> dict:
        return {
            "iteration": ir.iteration,
            "success": ir.success,
            "errors": ir.errors,
            "warnings": ir.warnings,
            "token_cost": ir.token_cost,
            "duration_seconds": ir.duration_seconds,
            "files_generated": ir.files_generated,
            "evolved_strategy": ir.evolved_strategy,
        }

    def budget_info_to_dict(bi: BudgetInfo) -> dict:
        return {
            "mode": bi.mode.value,
            "limit": bi.limit,
            "spent": bi.spent,
            "remaining": bi.remaining,
            "percentage": bi.percentage,
        }

    def artifact_to_dict(artifact: CodeArtifact) -> dict:
        return {
            "file_path": artifact.file_path,
            "content_hash": artifact.content_hash,
            "language": artifact.language,
            "lines": artifact.lines,
        }

    return {
        "session_id": report.session_id,
        "task": report.task,
        "status": report.status.value,
        "total_iterations": report.total_iterations,
        "total_tokens": report.total_tokens,
        "total_duration_seconds": report.total_duration_seconds,
        "iterations": [iter_report_to_dict(ir) for ir in report.iterations],
        "final_strategy": report.final_strategy,
        "artifacts": [artifact_to_dict(a) for a in report.artifacts],
        "budget_info": budget_info_to_dict(report.budget_info) if report.budget_info else None,
        "git_commit": report.git_commit,
    }


def _serialize_json(data: dict) -> str:
    if _HAS_ORJSON:
        return str(orjson.dumps(data, option=orjson.OPT_INDENT_2).decode())
    return json.dumps(data, indent=2)


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _source_project_name(source_project_path: str) -> str:
    """Return a compact label for a source project path."""
    if not source_project_path:
        return "-"
    return Path(source_project_path).name or source_project_path


def _parse_json_dict(payload: Any) -> dict[str, Any]:
    """Parse a JSON payload into a dictionary for CLI rendering."""
    if isinstance(payload, dict):
        return payload
    if not payload:
        return {}
    try:
        parsed = json.loads(str(payload))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _lesson_usage_source_label(row: dict[str, Any]) -> str:
    """Format a compact source label for one lesson-usage event."""
    lesson_source = str(row.get("lesson_source") or "unknown")
    if lesson_source == "related_project":
        return f"related:{_source_project_name(str(row.get('source_project_path') or ''))}"
    if lesson_source == "model_pack":
        return f"pack:{str(row.get('canonical_model_key') or 'unknown')}"
    return lesson_source


def _format_size(size_bytes: float) -> str:
    """Format byte size as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"


def _parse_timeout(timeout_str: str) -> int:
    if not timeout_str:
        return 3600
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = timeout_str[-1].lower()
    if unit in multipliers:
        try:
            value = int(timeout_str[:-1])
            if value < 0:
                return 3600
            seconds = value * multipliers[unit]
            return min(seconds, MAX_TIMEOUT_SECONDS)
        except ValueError:
            return 3600
    try:
        seconds = int(timeout_str)
        if seconds < 0:
            return 3600
        return min(seconds, MAX_TIMEOUT_SECONDS)
    except ValueError:
        return 3600


def _parse_budget(budget_str: str) -> tuple[BudgetMode, int]:
    if budget_str.lower() == "unlimited":
        return BudgetMode.UNLIMITED, 0
    if budget_str.lower() == "auto":
        return BudgetMode.AUTO, 0
    try:
        return BudgetMode.FIXED, int(budget_str)
    except ValueError:
        return BudgetMode.UNLIMITED, 0


def _run_benchmark_release_invariants() -> dict[str, Any]:
    """Run the focused offline guardrail tests used by release-gate mode."""
    command = [sys.executable, "-m", "pytest", *RELEASE_GATE_TEST_TARGETS, "-q"]
    result = subprocess.run(
        command,
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
    )
    stdout_lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    stderr_lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
    return {
        "checked": True,
        "passed": result.returncode == 0,
        "summary": "Focused offline guardrails for normal run/review paths and installed-pack prompt resolution.",
        "details": {
            "command": " ".join(command),
            "targets": list(RELEASE_GATE_TEST_TARGETS),
            "returncode": result.returncode,
            "stdout_tail": stdout_lines[-12:],
            "stderr_tail": stderr_lines[-12:],
        },
    }


def _get_status_color(status: str) -> str:
    color_map = {
        "pending": "yellow",
        "running": "cyan",
        "completed": "green",
        "failed": "red",
        "cancelled": "dim",
    }
    return color_map.get(status, "white")


# ---------------------------------------------------------------------------
# Memory inspection
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="muscle-cli")
def cli() -> None:
    """MUSCLE - MiniMax Unified Self-Correcting Learning Engine

    Project-first review, memory, and iterative generation using MiniMax M3.
    """
    pass
