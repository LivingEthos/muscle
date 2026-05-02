"""
CLI - Command-line interface for MUSCLE.

Provides commands for running, resuming, and managing self-improvement loops.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
from contextlib import nullcontext, redirect_stdout
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
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from .active_review import load_active_review_snapshot, refresh_active_review, refresh_project_state
from .audit_presenter import format_action_log_entry
from .backup_manager import BackupManager
from .budget_manager import BudgetManager
from .code_generator import CodeGenerator
from .code_review.learning_pipeline import LearningPipeline
from .cost_optimizer import CostOptimizer
from .doctor import build_doctor_report, doctor_report_to_dict
from .evolver import Evolver
from .host_runtime import run_host_hook
from .interactive import InteractiveHandler
from .learning_ingestor import LearningIngestor
from .lesson_resolver import LessonResolver
from .loop_controller import LoopController, LoopEvent
from .m27_client import DEFAULT_MODEL, M27Client
from .model_identity import SUPPORTED_CANONICAL_MODELS, ModelIdentityResolver
from .model_packs import DEFAULT_MODEL_PACK_REF, DEFAULT_MODEL_PACK_REPO, ModelPackManager
from .optimization import (
    ContextBudgeter,
    ExternalBenchmarkImporter,
    TelemetryRecorder,
    WorkflowOptimizer,
)
from .project_builder import ProjectBuilder
from .project_fingerprint import (
    build_project_fingerprint,
    explain_relatedness,
    fingerprint_from_row,
)
from .project_memory import ProjectMemory
from .project_memory_types import TaskStatus
from .self_improver import SelfImprover
from .session_manager import SessionManager
from .strategy_kb import GlobalKnowledgeBase
from .system_db import DEFAULT_SYSTEM_DB_PATH, SystemDatabase
from .types import BudgetMode, EvalMode, RunConfig, SessionReport, SessionStatus
from .webhook_notifier import WebhookNotifier

console = Console()

MAX_TASK_LENGTH = 10000
MAX_TIMEOUT_SECONDS = 86400
MAX_TASK_PREVIEW_LENGTH = 60

logging.basicConfig(
    level=logging.INFO,
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
    from .tui.project_manager import ProjectManager

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
    return M27Client(api_key=api_key)


def _build_context_budgeter(settings: dict[str, str]) -> ContextBudgeter:
    return ContextBudgeter(
        review_strategy=settings.get("optimize.context.semantic_review"),
        fix_strategy=settings.get("optimize.context.fix_generation"),
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


def _event_handler(event: LoopEvent, data: dict, state: _StreamingState) -> None:
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


def _create_event_handler() -> tuple[_StreamingState, Any]:
    state = _StreamingState()

    def handler(event: LoopEvent, data: dict) -> None:
        _event_handler(event, data, state)

    return state, handler


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """MUSCLE - MiniMax Unified Self-Correcting Learning Engine

    Project-first review, memory, and iterative generation using MiniMax M2.7.
    """
    pass


@cli.command()
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
@click.option(
    "--platform",
    type=click.Choice(["auto", "opencode", "claude-code", "codex"]),
    default="auto",
    help="Target platform",
)
@click.option(
    "--review-execution",
    type=click.Choice(["local", "worktree"]),
    default=None,
    help="Default execution mode for auto-fix and hybrid runs",
)
@click.option("--api-key", help="MINIMAX/M2.7 API key (or set MINIMAX_API_KEY env var)")
@click.option("--hooks/--no-hooks", default=True, help="Enable/disable post-task review hooks")
@click.option("--cli-path", help="Path to muscle CLI (auto-detected if not specified)")
@click.option(
    "--related-mode",
    type=click.Choice(["off", "suggest"]),
    default=None,
    help="Project-level related-project suggestion mode",
)
@click.option(
    "--pack-mode",
    type=click.Choice(["off", "suggest", "auto"]),
    default=None,
    help="Project-level model-pack mode",
)
@click.option(
    "--canonical-model",
    default=None,
    help="Manual canonical model override to apply during initialization",
)
def init(
    non_interactive: bool,
    platform: str,
    review_execution: str | None,
    api_key: str | None,
    hooks: bool,
    cli_path: str | None,
    related_mode: str | None,
    pack_mode: str | None,
    canonical_model: str | None,
) -> None:
    """Initialize MUSCLE for the current project.

    Creates .muscle/ with configuration, project-local memory, and bounded
    markdown memory files. This also bootstraps project-first growth settings
    such as related-project suggestion mode, model-pack mode, and optional
    canonical model selection.

    For OpenCode integration, run with --platform opencode.
    For Claude Code integration, run with --platform claude-code.
    For Codex integration, run with --platform codex.
    """
    from .tui.project_manager import ProjectConfig, ProjectManager

    console.print("[bold cyan]MUSCLE Initialization[/bold cyan]")
    console.print("=" * 50)

    manager = ProjectManager()
    detected = manager.detect_project()
    current_platform = manager.detect_platform()

    effective_platform = platform
    if platform == "auto":
        effective_platform = current_platform
        console.print(f"[dim]Detected platform: {current_platform}[/dim]")

    if not detected:
        console.print("[yellow]No project detected. Creating default project...[/yellow]")
        project = ProjectConfig(
            name="my-project",
            path=Path.cwd(),
            languages=[],
        )
    else:
        project = detected

    project.platform = effective_platform
    project.hooks_enabled = hooks
    project.cli_path = cli_path or manager.detect_cli_location()

    console.print(f"Project: [cyan]{project.name}[/cyan]")
    console.print(f"Path: [cyan]{project.path}[/cyan]")
    if project.languages:
        console.print(f"Languages: [cyan]{', '.join(project.languages)}[/cyan]")
    console.print(f"Platform: [cyan]{effective_platform}[/cyan]")
    console.print()

    if non_interactive:
        project.automation_level = "auto-fix"
        project.review_gate = "block+fix"
        project.review_execution = review_execution or "local"
        project.triggers = ["review-gate", "manual"]
        project.github_enabled = False
        project.memory_location = ".muscle"
        project.related_project_mode = related_mode or "suggest"
        project.model_pack_mode = pack_mode or "suggest"
    else:
        console.print("[bold]Automation Level:[/bold]")
        console.print("  [1] Auto-fix (Recommended)")
        console.print("  [2] Propose only")
        console.print("  [3] Hybrid")
        console.print("  [4] Ask every time")
        choice = console.input("Select [1-4] (default: 1): ").strip() or "1"
        levels = {"1": "auto-fix", "2": "propose", "3": "hybrid", "4": "ask"}
        project.automation_level = levels.get(choice, "auto-fix")

        console.print("\n[bold]Review Gate:[/bold]")
        console.print("  [1] Block + Fix (Recommended)")
        console.print("  [2] Block all")
        console.print("  [3] Warn only")
        console.print("  [4] Disabled")
        choice = console.input("Select [1-4] (default: 1): ").strip() or "1"
        gates = {"1": "block+fix", "2": "block-all", "3": "warn", "4": "disabled"}
        project.review_gate = gates.get(choice, "block+fix")

        if review_execution:
            project.review_execution = review_execution
        else:
            console.print("\n[bold]Fix Execution:[/bold]")
            console.print("  [1] Local checkout (Recommended)")
            console.print("  [2] Isolated worktree for auto-fix/hybrid")
            choice = console.input("Select [1-2] (default: 1): ").strip() or "1"
            project.review_execution = "worktree" if choice == "2" else "local"

        console.print("\n[bold]Triggers:[/bold]")
        console.print("  [x] Review Gate (Recommended)")
        console.print("  [ ] Git pre-commit")
        console.print("  [ ] Git pre-push")
        console.print("  [ ] GitHub Actions")
        console.print("  [x] Manual only")
        project.triggers = ["review-gate", "manual"]

        console.print("\n[bold]GitHub Integration:[/bold]")
        console.print("  [ ] Enable (not implemented yet)")
        project.github_enabled = False

        console.print("\n[bold]API Key:[/bold]")
        if os.environ.get("MINIMAX_API_KEY"):
            console.print("  [green]✓[/green] MINIMAX_API_KEY is set in environment")
            console.print("  [1] Use existing key")
            console.print("  [2] Enter new key")
            choice = console.input("Select [1-2] (default: 1): ").strip() or "1"
            if choice == "2":
                new_key = console.input("Enter API key: ").strip()
                if new_key:
                    os.environ["MINIMAX_API_KEY"] = new_key
                    project.api_key_source = "manual"
        else:
            console.print("  [yellow]No API key detected[/yellow]")
            console.print("  [1] Enter key now")
            console.print("  [2] Enter key later")
            console.print("  [3] Use OpenCode provider auth")
            choice = console.input("Select [1-3] (default: 2): ").strip() or "2"
            if choice == "1":
                new_key = console.input("Enter API key: ").strip()
                if new_key:
                    os.environ["MINIMAX_API_KEY"] = new_key
                    project.api_key_source = "manual"
            elif choice == "3":
                project.api_key_source = "opencode"

        console.print("\n[bold]Post-Task Review Hooks:[/bold]")
        console.print(f"  {'[x]' if hooks else '[ ]'} Enable automatic review after tasks")
        if not non_interactive:
            hook_choice = console.input("Enable hooks? [Y/n]: ").strip().lower()
            if hook_choice == "n":
                project.hooks_enabled = False
            elif hook_choice == "y" or not hook_choice:
                project.hooks_enabled = True

        if effective_platform in ("opencode", "auto"):
            console.print("\n[bold]CLI Path:[/bold]")
            if project.cli_path:
                console.print(f"  Detected: [cyan]{project.cli_path}[/cyan]")
            else:
                console.print("  [yellow]No muscle CLI detected[/yellow]")
            custom_path = console.input(
                "Enter path to muscle CLI (or press Enter to use detected): "
            ).strip()
            if custom_path:
                project.cli_path = custom_path

        if related_mode:
            project.related_project_mode = related_mode
        else:
            console.print("\n[bold]Cross-Project Memory Suggestions:[/bold]")
            console.print("  [1] Suggest related-project imports (Recommended)")
            console.print("  [2] Keep this project fully isolated")
            related_choice = console.input("Select [1-2] (default: 1): ").strip() or "1"
            project.related_project_mode = "off" if related_choice == "2" else "suggest"

        if pack_mode:
            project.model_pack_mode = pack_mode
        else:
            console.print("\n[bold]Model-Pack Suggestions:[/bold]")
            console.print("  [1] Suggest model packs when identity is known (Recommended)")
            console.print("  [2] Auto-apply matching model packs when identity is known")
            console.print("  [3] Disable model-pack suggestions")
            pack_choice = console.input("Select [1-3] (default: 1): ").strip() or "1"
            pack_modes = {"1": "suggest", "2": "auto", "3": "off"}
            project.model_pack_mode = pack_modes.get(pack_choice, "suggest")

    if canonical_model:
        project.model_manual_override = canonical_model

    identity = ModelIdentityResolver(SystemDatabase()).resolve(
        requested_label=_requested_model_label(),
        provider_endpoint=_provider_endpoint(),
        manual_override=project.model_manual_override,
    )
    if not non_interactive and canonical_model is None and identity.canonical_model_key is None:
        console.print("\n[bold]Model Identity:[/bold]")
        console.print("MUSCLE could not confidently verify the backing model for this endpoint.")
        console.print(
            "Select a canonical model to enable model-specific packs, or press Enter to skip."
        )
        for idx, model_name in enumerate(SUPPORTED_CANONICAL_MODELS, start=1):
            console.print(f"  [{idx}] {model_name}")
        manual_choice = console.input("Select model number (or press Enter to skip): ").strip()
        if manual_choice.isdigit():
            selected_index = int(manual_choice) - 1
            if 0 <= selected_index < len(SUPPORTED_CANONICAL_MODELS):
                project.model_manual_override = SUPPORTED_CANONICAL_MODELS[selected_index]
                identity = ModelIdentityResolver(SystemDatabase()).resolve(
                    requested_label=_requested_model_label(),
                    provider_endpoint=_provider_endpoint(),
                    manual_override=project.model_manual_override,
                )

    project.canonical_model_key = identity.canonical_model_key
    project.model_identity_source = identity.identity_source

    console.print()
    console.print("[bold]Initializing...[/bold]")

    if manager.init_project(project):
        console.print("[green]✓[/green] Created .muscle/ directory")
        console.print("[green]✓[/green] Created config.yaml")
        console.print("[green]✓[/green] Created CLAUDE.md, AGENT.md, MEMORY.md")
        console.print("[green]✓[/green] Initialized knowledge base")

        if api_key:
            manager.update_muscle_config(project.path, api_key=api_key)
            console.print("[green]✓[/green] API key configured")

        if effective_platform in ("opencode", "auto"):
            console.print()
            console.print("[bold cyan]Setting up OpenCode integration...[/bold cyan]")
            if manager.init_opencode_config(project, project.path / ".muscle"):
                console.print("[green]✓[/green] Created .opencode/ directory")
                console.print("[green]✓[/green] Created opencode.json")
                console.print("[green]✓[/green] Linked agents and skills")
                console.print()
                console.print("[bold]MUSCLE Tools Available in OpenCode:[/bold]")
                console.print("  muscle_review, muscle_pressure, muscle_rescue, muscle_lifeline")
                console.print("  muscle_check, muscle_probe, muscle_diagnosis, muscle_result")
                console.print("  muscle_history, muscle_kb_stats, muscle_settings_*")
                console.print("  muscle_init, muscle_long_eval, muscle_improve, muscle_cost_*")
                console.print("  muscle_tui, muscle_run, muscle_abort")
                console.print()
                console.print("[dim]MUSCLE automatically calls muscle_review on session idle[/dim]")
            else:
                console.print("[yellow]⚠[/yellow] OpenCode setup skipped (may already exist)")

        # Store project enablement state in project_memory.db
        manager.set_project_enabled(project.path, True)
        console.print("[green]✓[/green] Project enabled in database")
        manager.register_project(project.path)

        try:
            pm = ProjectMemory(str(project.path))
            pm.insert_model_identity_history(str(project.path), identity.__dict__)
        except Exception as exc:
            logger.warning("Could not persist model identity during init: %s", exc)

        _refresh_active_review_safe(project.path, reason="init")

        suggestions = (
            _suggest_related_projects(
                project.path,
                project,
                refresh_current=True,
            )
            if project.related_project_mode != "off"
            else []
        )
        if suggestions:
            console.print("[green]✓[/green] Related-project suggestions available")
            for suggestion in suggestions:
                console.print(
                    f"  - {suggestion['display_name']} "
                    f"({suggestion['score']:.2f}) at {suggestion['project_path']}"
                )
                console.print(f"    why: {suggestion['why']}")

            if not non_interactive:
                choice = (
                    console.input(
                        "Import strongest match now? [s]napshot/[a]ttach/[Enter to skip]: "
                    )
                    .strip()
                    .lower()
                )
                if choice in {"s", "a"}:
                    best = suggestions[0]
                    mode = "snapshot" if choice == "s" else "attach"
                    result = pm.import_project_lessons(
                        project_path=str(project.path),
                        source_project_path=str(best["project_path"]),
                        link_mode=mode,
                        relatedness_score=float(best["score"]),
                    )
                    if mode == "attach":
                        console.print(
                            f"[green]✓[/green] Attached related project: {best['display_name']}"
                        )
                    else:
                        console.print(
                            f"[green]✓[/green] Imported {result['imported']} provisional lessons "
                            f"from {best['display_name']}"
                        )

        console.print()
        console.print("[bold]Setup Summary:[/bold]")
        console.print(f"  Related-project mode: [cyan]{project.related_project_mode}[/cyan]")
        console.print(f"  Model-pack mode: [cyan]{project.model_pack_mode}[/cyan]")
        console.print(
            f"  Canonical model: [cyan]{project.canonical_model_key or 'Unresolved'}[/cyan]"
        )
        if project.canonical_model_key is None:
            console.print(
                "  [dim]Tip: run 'muscle model select --canonical-model <model-key>' "
                "to enable model-specific packs for unresolved endpoints.[/dim]"
            )
        if project.related_project_mode != "off":
            console.print(
                "  [dim]Tip: run 'muscle memory related' to review or import related-project "
                "lessons later without auto-applying them.[/dim]"
            )

        console.print()
        console.print("[bold green]MUSCLE initialized successfully![/bold green]")
        console.print()
        console.print("Run 'muscle tui' to start the TUI")
        console.print("Run 'muscle review --target ./src' to run a review")
        console.print("Run 'muscle status' to check project status")
        if effective_platform == "codex":
            plugin_root = Path(__file__).resolve().parent / "plugin"
            console.print()
            console.print("[bold cyan]Codex plugin bundle[/bold cyan]")
            console.print(f"Point Codex at: [cyan]{plugin_root}[/cyan]")
            console.print(
                "[dim]This bundle includes `.codex-plugin/plugin.json` and "
                "root `hooks.json`; MUSCLE does not create repo-local `.codex/` assets.[/dim]"
            )
        if effective_platform in ("opencode", "auto"):
            console.print()
            console.print("[dim]For OpenCode, use the muscle_* tools directly[/dim]")
    else:
        console.print("[red]Failed to initialize project[/red]")


@cli.command(name="optimize-host-docs")
@click.option("--dry-run", is_flag=True, help="Print a unified diff; do not write.")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt (required in auto mode).",
)
@click.option(
    "--only",
    type=click.Choice(["CLAUDE.md", "AGENTS.md"]),
    default=None,
    help="Restrict to a single target file.",
)
@click.option("--skip-agents", is_flag=True, help="Do not touch AGENTS.md.")
@click.option(
    "--target",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    default=None,
    help="Project root to optimize (defaults to current working directory).",
)
@click.option(
    "--agents/--no-agents",
    default=True,
    help="Include AGENTS.md (alias of --skip-agents). Default: true.",
)
def optimize_host_docs(
    dry_run: bool,
    yes: bool,
    only: str | None,
    skip_agents: bool,
    target: str | None,
    agents: bool,
) -> None:
    """Non-destructively optimize root CLAUDE.md / AGENTS.md into the MUSCLE-preferred format."""
    from .code_review.host_memory_optimizer import run_optimizer

    project_root = Path(target).resolve() if target else Path.cwd()

    # --no-agents is a shorthand alias for --skip-agents.
    effective_skip_agents = skip_agents or (not agents)

    results = run_optimizer(
        project_path=project_root,
        only=only,
        skip_agents=effective_skip_agents,
        dry_run=dry_run,
    )

    any_changed = False
    for r in results:
        click.echo(f"\n=== {r.filename} ===")
        click.echo(r.reason)
        if r.changed and r.diff:
            click.echo(r.diff)
            any_changed = True

    if dry_run:
        sys.exit(1 if any_changed else 0)

    if any_changed and not yes:
        if not click.confirm("Apply these changes?", default=False):
            click.echo("Aborted.")
            sys.exit(1)
    click.echo("Done." if any_changed else "No changes needed.")


@cli.command()
def enable() -> None:
    """Enable MUSCLE for the current project.

    Stores project-local enablement in the project database.
    Use after 'muscle init' if MUSCLE was previously disabled.

    Examples:

        muscle enable
    """
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path = Path.cwd()

    # Check if project is initialized
    if not manager.get_muscle_dir(project_path):
        console.print("[yellow]Project not initialized. Run 'muscle init' first.[/yellow]")
        return

    if manager.set_project_enabled(project_path, True):
        manager.register_project(project_path)
        _refresh_active_review_safe(project_path, reason="enable")
        console.print("[green]MUSCLE enabled for this project.[/green]")
    else:
        console.print("[red]Failed to enable MUSCLE.[/red]")


@cli.command()
def disable() -> None:
    """Disable MUSCLE for the current project.

    Disables MUSCLE for this project without removing configuration.
    Use 'muscle enable' to re-enable.

    Examples:

        muscle disable
    """
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path = Path.cwd()

    # Check if project is initialized
    if not manager.get_muscle_dir(project_path):
        console.print("[yellow]Project not initialized. Run 'muscle init' first.[/yellow]")
        return

    if manager.set_project_enabled(project_path, False):
        _refresh_active_review_safe(project_path, reason="disable")
        console.print("[green]MUSCLE disabled for this project.[/green]")
    else:
        console.print("[red]Failed to disable MUSCLE.[/red]")


@cli.command()
@click.option(
    "--refresh",
    "refresh_state",
    is_flag=True,
    help="Refresh external catchup and `.muscle/active-review.md` before reporting",
)
def status(refresh_state: bool) -> None:
    """Show MUSCLE status for the current project.

    Displays whether MUSCLE is enabled, the active project config, the
    project-local database path, review/run counts, and project-first growth
    state needed to reason about related-project and model-pack overlays.

    Examples:

        muscle status

        muscle status --refresh
    """
    from .project_memory import ProjectMemory
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    start_path = Path.cwd()
    project = (
        manager.load_config(start_path)
        or manager.load_nearest_config(start_path)
        or manager.get_current_project()
    )
    project_path = project.path if project is not None else start_path

    if refresh_state:
        _refresh_project_state_safe(project_path, reason="status-refresh", import_provider="all")

    table = Table(title="MUSCLE Status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    # Check if initialized
    muscle_dir = manager.get_muscle_dir(project_path)
    if not muscle_dir:
        table.add_row("Status", "[yellow]Not initialized[/yellow]")
        table.add_row("Run 'muscle init'", "to initialize")
        console.print(table)
        return

    # Check enabled state
    is_enabled = manager.is_project_enabled(project_path)
    status_str = "[green]Enabled[/green]" if is_enabled else "[red]Disabled[/red]"
    table.add_row("Status", status_str)

    if project:
        table.add_row("Project", project.name)
        table.add_row("Platform", project.platform)
        table.add_row("Languages", ", ".join(project.languages) if project.languages else "None")
        table.add_row("Related Memory Mode", getattr(project, "related_project_mode", "suggest"))
        table.add_row("Model Pack Mode", getattr(project, "model_pack_mode", "suggest"))
    else:
        table.add_row("Project", project_path.name)

    if project is not None:
        manager.register_project(project.path)

    # Database path
    db_path = muscle_dir / "project_memory.db"
    if db_path.exists():
        table.add_row("DB Path", str(db_path))
    else:
        table.add_row("DB Path", "Not created yet")

    # Get statistics from project_memory
    try:
        pm = ProjectMemory(str(project_path))
        stats = pm.get_statistics(str(project_path))
        table.add_row("Total Reviews", str(stats.get("total_reviews", 0)))
        table.add_row("Total Findings", str(stats.get("total_findings", 0)))
        snapshot = load_active_review_snapshot(str(project_path))
        table.add_row("Active Review Snapshot", _format_snapshot_age(snapshot.get("age_seconds")))
        catchup_summary = snapshot.get("catchup_summary") or {}
        table.add_row(
            "Last Catchup Summary",
            str(catchup_summary.get("summary") or "None"),
        )
        table.add_row("Learned Rules", str(stats.get("total_learned_rules", 0)))
        table.add_row("Skills", str(stats.get("total_skills", 0)))
        table.add_row("Related Projects", str(stats.get("related_projects", 0)))
        table.add_row("Transferred Lessons", str(stats.get("transferred_lessons", 0)))

        identity = pm.get_latest_model_identity(str(project_path))
        if identity:
            table.add_row(
                "Canonical Model",
                str(identity.get("canonical_model_key") or "Unresolved"),
            )
            table.add_row(
                "Model Identity",
                f"{identity.get('identity_source', 'unresolved')} "
                f"({float(identity.get('confidence', 0.0) or 0.0):.2f})",
            )
            pack_count = 0
            canonical_model = identity.get("canonical_model_key")
            if canonical_model:
                pack_count = len(
                    [
                        pack
                        for pack in SystemDatabase().list_model_packs()
                        if pack.get("canonical_model_key") == canonical_model
                    ]
                )
            table.add_row("Active Model Packs", str(pack_count))
    except Exception:
        table.add_row("Reviews", "N/A")

    # Escalation summary
    try:
        from .escalation import EscalationRecorder

        unresolved = EscalationRecorder.list_unresolved(project_path)
        if unresolved:
            table.add_row("Unresolved Escalations", str(len(unresolved)))
    except Exception:
        pass

    console.print(table)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Emit structured doctor output")
@click.option(
    "--refresh",
    "refresh_state",
    is_flag=True,
    help="Refresh external catchup and `.muscle/active-review.md` before reporting",
)
def doctor(json_output: bool, refresh_state: bool) -> None:
    """Diagnose MUSCLE project lifecycle, plugin bundle, and snapshot state."""

    report = build_doctor_report(str(Path.cwd()), refresh=refresh_state)
    if json_output:
        console.print(json.dumps(doctor_report_to_dict(report), indent=2))
        return
    _render_doctor_report(report)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Emit structured savings output")
def savings(json_output: bool) -> None:
    """Summarize token, cache, and command-output savings evidence."""

    from .savings import build_savings_report

    project_path, _ = _resolve_project_context(Path.cwd())
    report = build_savings_report(project_path)
    if json_output:
        console.print(json.dumps(report, indent=2))
        return
    _render_savings_report(report)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Emit structured discovery output")
@click.option("--since", "since_days", type=int, default=30, show_default=True)
def discover(json_output: bool, since_days: int) -> None:
    """Report missed MUSCLE opportunities without writing memory files."""

    from .discovery import build_discovery_report

    project_path, _ = _resolve_project_context(Path.cwd())
    report = build_discovery_report(project_path, since_days=max(1, since_days))
    if json_output:
        console.print(json.dumps(report, indent=2))
        return
    _render_discovery_report(report)


@cli.group(name="filters")
def filters_group() -> None:
    """Verify and trust declarative command-output filters."""


@filters_group.command(name="verify")
@click.option("--filter", "filter_name", default=None, help="Verify one filter by name")
@click.option("--require-all", is_flag=True, help="Require inline tests for every filter")
@click.option("--json", "json_output", is_flag=True, help="Emit structured filter output")
def filters_verify(filter_name: str | None, require_all: bool, json_output: bool) -> None:
    """Verify built-in and trusted project-local output filters."""

    from .output_filters import verify_filters

    project_path, _ = _resolve_project_context(Path.cwd())
    report = verify_filters(project_path, filter_name=filter_name, require_all=require_all)
    if json_output:
        console.print(json.dumps(report, indent=2))
        return
    status = "[green]passed[/green]" if report["passed"] else "[red]failed[/red]"
    console.print(f"Filter verification {status} ({report['filter_count']} filter(s))")
    for warning in report.get("warnings", []):
        console.print(f"[yellow]WARN[/yellow] {warning}")


@filters_group.command(name="trust")
@click.option("--json", "json_output", is_flag=True, help="Emit structured filter output")
def filters_trust(json_output: bool) -> None:
    """Trust current project-local `.muscle/filters.yaml` content."""

    from .output_filters import trust_project_filters

    project_path, _ = _resolve_project_context(Path.cwd())
    report = trust_project_filters(project_path)
    if json_output:
        console.print(json.dumps(report, indent=2))
        return
    if report.get("trusted"):
        console.print(f"[green]Trusted project filters[/green] {report.get('filters_sha256')}")
    else:
        console.print(f"[yellow]Project filters not trusted:[/yellow] {report.get('reason')}")


@filters_group.command(name="untrust")
@click.option("--json", "json_output", is_flag=True, help="Emit structured filter output")
def filters_untrust(json_output: bool) -> None:
    """Remove project-local filter trust."""

    from .output_filters import untrust_project_filters

    project_path, _ = _resolve_project_context(Path.cwd())
    report = untrust_project_filters(project_path)
    if json_output:
        console.print(json.dumps(report, indent=2))
        return
    console.print("[green]Project filter trust removed.[/green]")


@cli.command(name="_host-hook", hidden=True)
@click.option(
    "--platform",
    type=click.Choice(["claude-code", "codex"]),
    required=True,
    help="Host platform invoking the lifecycle hook",
)
@click.option(
    "--event",
    type=click.Choice(["session_start", "user_prompt_submit", "post_write", "stop"]),
    required=True,
    help="Lifecycle event to process",
)
@click.option("--project-path", type=click.Path(path_type=Path), default=None)
@click.option("--tool-name", default=None, help="Optional host tool name for post_write hooks")
def host_hook(platform: str, event: str, project_path: Path | None, tool_name: str | None) -> None:
    """Internal lifecycle hook bridge used by Claude/Codex plugin hook files."""

    resolved_project = project_path.resolve() if project_path else Path.cwd().resolve()
    result = run_host_hook(
        platform=platform,
        event=event,
        project_path=str(resolved_project),
        tool_name=tool_name,
    )
    if result.message:
        console.print(result.message)


@cli.command()
def tui() -> None:
    """Start the MUSCLE Terminal User Interface.

    Provides dashboard, reviews, history, settings, and project switching.
    """
    try:
        import importlib.util

        if importlib.util.find_spec("readchar") is None:
            raise ImportError("readchar not installed")
    except ImportError:
        console.print("[red]readchar required for TUI: pip install readchar[/red]")
        return

    from .tui.project_manager import ProjectManager
    from .tui.views import TUI

    manager = ProjectManager()
    project = manager.detect_project()

    tui = TUI()
    if project:
        tui.state.current_project = project.name
        console.print(f"[dim]Project: {project.name}[/dim]")

    console.print("[dim]MUSCLE TUI - Press q to quit, arrows to navigate[/dim]")
    console.print()

    try:
        tui.run()
    except KeyboardInterrupt:
        pass
    console.print("\n[dim]Goodbye![/dim]")


@cli.command()
@click.option("--task", "-t", required=True, help="Task description")
@click.option(
    "--language", "-l", default=None, help="Programming language (auto-detected if not specified)"
)
@click.option("--output", "-o", default=".", help="Output directory")
@click.option("--max-iterations", "-n", default=20, help="Maximum iterations")
@click.option("--timeout", default="60m", help="Timeout (e.g., 30m, 2h)")
@click.option("--budget", default="unlimited", help="Budget: unlimited, auto, or token count")
@click.option(
    "--eval-mode",
    default="all",
    type=click.Choice(["all", "sequential", "parallel"]),
    help="Evaluation mode",
)
@click.option("--allow-warnings", is_flag=True, help="Pass even if linter warnings exist")
@click.option(
    "--interactive/--no-interactive", default=True, help="Enable/disable interactive mode"
)
@click.option("--git/--no-git", default=None, help="Enable/disable git auto-commit")
@click.option("--git-repo", default=".", help="Git repository path")
@click.option("--git-push", is_flag=True, help="Auto-push to remote after commit")
@click.option(
    "--format",
    "-f",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Output format",
)
@click.option("--output-file", "-O", default=None, help="Write report to file")
@click.option(
    "--webhook-url", default=None, help="Webhook URL for notifications (or set MUSCLE_WEBHOOK_URL)"
)
@click.option("--kb/--no-kb", default=True, help="Enable/disable knowledge base")
@click.option("--kb-path", default=None, help="Knowledge base path")
@click.option(
    "--template/--no-template",
    default=None,
    help="Generate project scaffolding (auto-detect language if not specified)",
)
@click.option("--estimate-cost", is_flag=True, help="Show cost estimate without running")
def run(
    task: str,
    language: str | None,
    output: str,
    max_iterations: int,
    timeout: str,
    budget: str,
    eval_mode: str,
    allow_warnings: bool,
    interactive: bool,
    git: bool | None,
    git_repo: str,
    git_push: bool,
    format: str,
    output_file: str | None,
    webhook_url: str | None,
    kb: bool,
    kb_path: str | None,
    template: bool | None,
    estimate_cost: bool,
) -> None:
    """Start a new MUSCLE session"""

    if not task or not task.strip():
        console.print("[red]Error: Task cannot be empty[/red]")
        sys.exit(1)

    cost_optimizer = CostOptimizer()
    cost_estimate = cost_optimizer.estimate_cost(task)

    console.print(
        f"[bold]MUSCLE Session[/bold] - Task: {_truncate(task, MAX_TASK_PREVIEW_LENGTH)}..."
    )
    console.print(f"Config: iterations={max_iterations}, timeout={timeout}, budget={budget}")
    console.print(
        f"[cyan]Cost Estimate:[/cyan] Tier={cost_estimate['tier']}, "
        f"Max tokens={cost_estimate['max_tokens']}, "
        f"Est. cost=${cost_estimate['estimated_cost_usd']}"
    )

    if estimate_cost:
        console.print(f"\n[yellow]Recommendation:[/yellow] {cost_estimate['recommendation']}")
        console.print(
            "\n[green]Cost estimate complete. Run without --estimate-cost to proceed.[/green]"
        )
        return

    timeout_seconds = _parse_timeout(timeout)

    budget_mode, budget_tokens = _parse_budget(budget)

    try:
        config = RunConfig(
            task=task,
            language=language,
            output_dir=output,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            budget_tokens=budget_tokens,
            budget_mode=budget_mode,
            eval_mode={
                "all": EvalMode.ALL,
                "sequential": EvalMode.SEQUENTIAL,
                "parallel": EvalMode.PARALLEL,
            }.get(eval_mode, EvalMode.ALL),
            allow_warnings=allow_warnings,
            interactive=interactive,
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)

    if template is None:
        template = language is not None

    if template:
        effective_language = language or ProjectBuilder.detect_language_from_task(task)
        if effective_language:
            project_builder = ProjectBuilder(
                language=effective_language,
                project_name=Path(output).name or "project",
            )
            generated = project_builder.build(output)
            console.print(f"[cyan]Generated project scaffolding ({len(generated)} files)[/cyan]")
        else:
            console.print("[yellow]Could not auto-detect language for template generation[/yellow]")

    m27_client = _create_m27_client()
    budget_manager = BudgetManager(mode=budget_mode, fixed_limit=budget_tokens)
    resolved_run_project_path, _ = _resolve_project_context(Path(output).resolve())
    project_path = str(resolved_run_project_path)

    if not m27_client.api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    pm, _, context_budgeter, telemetry_recorder, lesson_resolver, _, _ = (
        _attach_optimization_runtime(
            project_path,
            m27_client,
        )
    )

    code_gen = CodeGenerator(
        m27_client,
        cost_optimizer=cost_optimizer,
        context_budgeter=context_budgeter,
        project_path=project_path,
        lesson_resolver=lesson_resolver,
    )
    evolver = Evolver(
        m27_client,
        use_kb=kb,
        kb_path=kb_path,
        context_budgeter=context_budgeter,
        project_path=project_path,
        lesson_resolver=lesson_resolver,
    )

    def evaluator(output_dir: str) -> Any:
        from .evaluator_registry import EvaluatorRegistry

        registry = EvaluatorRegistry()
        return registry.evaluate(output_dir, config.language, config.eval_mode)

    def code_gen_wrapper(
        task: str,
        strategy: str | None,
        output_dir: str | None,
        session_id: str | None = None,
    ) -> tuple[str, Any]:
        return code_gen.generate(
            task,
            strategy or "",
            output_dir or ".",
            session_id=session_id,
            language=config.language,
        )

    code_gen_wrapper.generate_streaming = code_gen.generate_streaming  # type: ignore[attr-defined]

    git_enabled = git if git is not None else interactive
    git_repo_path = git_repo if git_enabled else None

    from .session_manager import SessionManager

    session_manager = SessionManager()

    webhook_notifier = WebhookNotifier(webhook_url or os.environ.get("MUSCLE_WEBHOOK_URL"))

    interactive_handler = InteractiveHandler(enabled=interactive)
    stream_state, event_handler = _create_event_handler()

    controller = LoopController(
        config=config,
        code_generator=code_gen_wrapper,
        evaluator=evaluator,
        evolver=evolver.evolve,
        budget_manager=budget_manager.check_budget,
        event_callback=event_handler,
        webhook_notifier=webhook_notifier,
        git_repo_path=git_repo_path,
        git_auto_push=git_push if git_enabled else False,
        interactive=interactive_handler,
        session_manager=session_manager,
        project_memory=pm,
        m27_client=m27_client,
    )

    try:
        streaming_display = Text("")
        live = None

        def streaming_callback(chunk: str) -> None:
            nonlocal streaming_display, live
            full_text = "".join(stream_state.chunks) + chunk
            if len(full_text) > 2000:
                full_text = "..." + full_text[-1997:]
            streaming_display = Text(full_text, style="cyan")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Running MUSCLE...", total=None)

            live = Live(
                streaming_display,
                console=console,
                refresh_per_second=10,
                vertical_overflow="ellipsis",
            )

            try:
                live.start()
                ctx = controller.run(streaming_callback=streaming_callback)
            finally:
                if live:
                    live.stop()

        # Structured DB ingestion for task run
        try:
            pm = ProjectMemory(project_path)
            ingestor = LearningIngestor(pm)
            duration_ms = int(ctx.stats.total_duration_seconds * 1000)
            status_map = {
                SessionStatus.SUCCESS: TaskStatus.SUCCESS,
                SessionStatus.FAILED: TaskStatus.FAILED,
                SessionStatus.ABORTED: TaskStatus.SKIPPED,
                SessionStatus.BUDGET_EXCEEDED: TaskStatus.FAILED,
            }
            task_status = status_map.get(ctx.stats.status, TaskStatus.FAILED)
            outcome_msg = (
                None if ctx.stats.status == SessionStatus.SUCCESS else ctx.stats.status.value
            )
            ingestor.write_task_run(
                project_path=project_path,
                title=task[:100] if task else "untitled",
                description=task,
                status=task_status,
                outcome=outcome_msg,
                token_cost=ctx.stats.total_tokens,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning(f"LearningIngestor task ingestion failed: {e}")

        if format == "json":
            report = controller.get_session_report()
            if report:
                report_data = _session_report_to_dict(report)
                json_output = _serialize_json(report_data)
                if output_file:
                    try:
                        Path(output_file).write_text(json_output, encoding="utf-8")
                    except OSError as e:
                        console.print(f"[red]Failed to write output file: {e}[/red]")
                else:
                    console.print(json_output)
            return

        console.print(f"\n[bold]Session {ctx.session_id}[/bold]")
        console.print(f"Status: {ctx.stats.status.value}")
        console.print(f"Iterations: {ctx.stats.total_iterations}")
        console.print(f"Tokens used: {ctx.stats.total_tokens}")

    except KeyboardInterrupt:
        controller.request_abort()
        console.print("\n[yellow]Aborted by user[/yellow]")
        sys.exit(130)
    finally:
        if telemetry_recorder is not None:
            telemetry_recorder.close()


@cli.command()
def history() -> None:
    """List all MUSCLE sessions"""
    session_manager = SessionManager()
    sessions = session_manager.list_sessions()

    if not sessions:
        console.print("[yellow]No sessions found[/yellow]")
        return

    table = Table(title="MUSCLE Sessions")
    table.add_column("Session ID")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Iterations")
    table.add_column("Created")

    for s in sessions:
        table.add_row(
            s.get("session_id", ""),
            _truncate(s.get("task", ""), 40),
            s.get("status", ""),
            str(s.get("total_iterations", "-")),
            s.get("created_at", "")[:19] if s.get("created_at") else "",
        )

    console.print(table)


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


@cli.command()
@click.argument("session_id")
def resume(session_id: str) -> None:
    """Resume a failed or incomplete session"""
    session_manager = SessionManager()
    session = session_manager.load_session(session_id)

    if not session:
        console.print(f"[red]Session {session_id} not found[/red]")
        sys.exit(1)

    status = session.get("status", SessionStatus.RUNNING.value)
    if status == SessionStatus.SUCCESS.value:
        console.print(f"[yellow]Session {session_id} already completed successfully[/yellow]")
        sys.exit(1)

    pid_file = Path.home() / ".muscle" / f"{session_id}.pid"
    pid = _read_session_pid(pid_file)
    if status == SessionStatus.RUNNING.value and pid is not None and _is_process_alive(pid):
        console.print(f"[yellow]Session {session_id} is still running in process {pid}[/yellow]")
        console.print("Use 'muscle abort <session-id>' first, or wait for it to finish.")
        sys.exit(1)
    if pid is not None and not _is_process_alive(pid):
        pid_file.unlink(missing_ok=True)

    resume_ctx = session_manager.load_resume_context(session_id)
    if resume_ctx is None:
        console.print(f"[red]Session {session_id} cannot be resumed[/red]")
        sys.exit(1)

    if (
        resume_ctx.config.budget_mode == BudgetMode.FIXED
        and resume_ctx.config.budget_tokens > 0
        and resume_ctx.stats.total_tokens >= resume_ctx.config.budget_tokens
    ):
        console.print(f"[red]Session {session_id} exhausted its fixed token budget[/red]")
        sys.exit(1)

    console.print(f"[bold]Resuming session {session_id}[/bold]")
    console.print(f"Task: {session.get('task', 'Unknown')}")
    console.print(
        "Previous evolved strategy: "
        f"{_truncate(resume_ctx.evolved_strategy, 100) if resume_ctx.evolved_strategy else 'None'}..."
    )
    console.print(f"Completed iterations: {resume_ctx.current_iteration}")
    console.print(f"Continuing up to iteration {resume_ctx.config.max_iterations}")

    m27_client = _create_m27_client()
    if not m27_client.api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    resolved_resume_project_path, _ = _resolve_project_context(
        Path(resume_ctx.config.output_dir).resolve()
    )
    project_path = str(resolved_resume_project_path)
    pm, _, context_budgeter, telemetry_recorder, lesson_resolver, _, _ = (
        _attach_optimization_runtime(
            project_path,
            m27_client,
        )
    )

    code_gen = CodeGenerator(
        m27_client,
        context_budgeter=context_budgeter,
        project_path=project_path,
        lesson_resolver=lesson_resolver,
    )
    evolver = Evolver(
        m27_client,
        use_kb=True,
        kb_path=resume_ctx.config.kb_path,
        context_budgeter=context_budgeter,
        project_path=project_path,
        lesson_resolver=lesson_resolver,
    )
    budget_manager = BudgetManager(
        mode=resume_ctx.config.budget_mode,
        fixed_limit=resume_ctx.config.budget_tokens,
        consumed_tokens=resume_ctx.stats.total_tokens
        if resume_ctx.config.budget_mode == BudgetMode.FIXED
        else 0,
    )

    def evaluator(output_dir: str) -> Any:
        from .evaluator_registry import EvaluatorRegistry

        registry = EvaluatorRegistry()
        return registry.evaluate(
            output_dir, resume_ctx.config.language, resume_ctx.config.eval_mode
        )

    def code_gen_wrapper(
        task: str,
        strategy: str | None,
        output_dir: str | None,
        session_id: str | None = None,
    ) -> tuple[str, Any]:
        return code_gen.generate(
            task,
            strategy or "",
            output_dir or ".",
            session_id=session_id,
        )

    code_gen_wrapper.generate_streaming = code_gen.generate_streaming  # type: ignore[attr-defined]

    stream_state, event_handler = _create_event_handler()
    controller = LoopController(
        config=resume_ctx.config,
        code_generator=code_gen_wrapper,
        evaluator=evaluator,
        evolver=evolver.evolve,
        budget_manager=budget_manager.check_budget,
        event_callback=event_handler,
        interactive=InteractiveHandler(enabled=resume_ctx.config.interactive),
        session_manager=session_manager,
        project_memory=pm,
        m27_client=m27_client,
    )

    try:
        streaming_display = Text("")
        live = None

        def streaming_callback(chunk: str) -> None:
            nonlocal streaming_display, live
            full_text = "".join(stream_state.chunks) + chunk
            if len(full_text) > 2000:
                full_text = "..." + full_text[-1997:]
            streaming_display = Text(full_text, style="cyan")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Resuming MUSCLE...", total=None)

            live = Live(
                streaming_display,
                console=console,
                refresh_per_second=10,
                vertical_overflow="ellipsis",
            )

            try:
                live.start()
                ctx = controller.run(
                    streaming_callback=streaming_callback,
                    resume_context=resume_ctx,
                )
            finally:
                if live:
                    live.stop()

        console.print(f"\n[bold]Session {ctx.session_id}[/bold]")
        console.print(f"Status: {ctx.stats.status.value}")
        console.print(f"Iterations: {ctx.stats.total_iterations}")
        console.print(f"Tokens used: {ctx.stats.total_tokens}")
    except KeyboardInterrupt:
        controller.request_abort()
        console.print("\n[yellow]Aborted by user[/yellow]")
        sys.exit(130)
    finally:
        if telemetry_recorder is not None:
            telemetry_recorder.close()


@cli.command()
@click.argument("session_id")
def abort(session_id: str) -> None:
    """Abort a running session.

    Sends SIGTERM to the running MUSCLE process and marks the session as aborted.

    Examples:

        muscle abort 20260331_ab12345
    """
    from pathlib import Path

    pid_file = Path.home() / ".muscle" / f"{session_id}.pid"

    if not pid_file.exists():
        console.print(f"[yellow]No running session found with ID: {session_id}[/yellow]")
        console.print("Run 'muscle history' to see active sessions.")
        sys.exit(1)

    try:
        pid_str = pid_file.read_text(encoding="utf-8").strip()
        pid = int(pid_str)
    except (ValueError, OSError) as e:
        console.print(f"[red]Failed to read PID file: {e}[/red]")
        sys.exit(1)

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        console.print(f"[yellow]Process {pid} not found (may have already exited)[/yellow]")
        pid_file.unlink(missing_ok=True)
        console.print("[green]Cleaned up stale PID file.[/green]")
        sys.exit(0)
    except PermissionError:
        console.print(f"[red]Permission denied sending SIGTERM to process {pid}[/red]")
        sys.exit(1)

    console.print(f"[cyan]Sent SIGTERM to process {pid}[/cyan]")
    console.print(f"[green]Session {session_id} marked for abort.[/green]")
    console.print("(The session will exit cleanly at the next iteration boundary.)")


@cli.command()
@click.option("--target", "-t", required=True, help="Target path to validate (file or directory)")
@click.option(
    "--language", "-l", default=None, help="Programming language (auto-detected if not specified)"
)
@click.option(
    "--format", "-f", default="text", type=click.Choice(["text", "json"]), help="Output format"
)
def check(target: str, language: str | None, format: str) -> None:
    """Run a single-shot validation against a file or directory.

    Runs compiler, linter, and test checks once without any iteration loop.
    Returns exit code 0 if all checks pass, non-zero otherwise.

    Examples:

        muscle check --target ./src

        muscle check --target ./src/utils.py

        muscle check --target ./src --language python --format json

        muscle check --target ./tests --format text
    """
    from .evaluator_registry import LANGUAGE_EVALUATORS, EvaluatorRegistry

    target_path = Path(target)
    if not target_path.exists():
        console.print(f"[red]Error: Target does not exist: {target}[/red]")
        sys.exit(1)

    if target_path.is_file():
        if not language:
            language = target_path.suffix if target_path.suffix in LANGUAGE_EVALUATORS else None
        eval_target = str(target_path)
    else:
        eval_target = str(target_path)

    registry = EvaluatorRegistry()
    result = registry.evaluate(eval_target, language=language)

    if format == "json":
        output = {
            "passed": result.passed,
            "compiler_errors": result.compiler_errors,
            "test_failures": result.test_failures,
            "linter_warnings": result.linter_warnings,
            "assertion_failures": result.assertion_failures,
        }
        console.print(json.dumps(output, indent=2))
    else:
        if result.passed:
            console.print("[green]All checks passed[/green]")
        else:
            console.print("[red]Checks failed:[/red]")

        if result.compiler_errors:
            console.print(f"\n[red]Compiler Errors ({len(result.compiler_errors)}):[/red]")
            for err in result.compiler_errors:
                console.print(f"  • {err}")

        if result.test_failures:
            console.print(f"\n[red]Test Failures ({len(result.test_failures)}):[/red]")
            for err in result.test_failures:
                console.print(f"  • {err}")

        if result.assertion_failures:
            console.print(f"\n[red]Assertion Failures ({len(result.assertion_failures)}):[/red]")
            for err in result.assertion_failures:
                console.print(f"  • {err}")

        if result.linter_warnings:
            console.print(f"\n[yellow]Linter Warnings ({len(result.linter_warnings)}):[/yellow]")
            for err in result.linter_warnings:
                console.print(f"  • {err}")

    sys.exit(0 if result.passed else 1)


@cli.group(name="kb")
def kb_group() -> None:
    """Knowledge base management commands"""
    pass


@kb_group.command(name="stats")
@click.option("--path", default=None, help="Knowledge base path")
def kb_stats(path: str | None) -> None:
    """Show knowledge base statistics"""
    try:
        gkb = GlobalKnowledgeBase(path)
        stats = gkb.strategy_kb.get_statistics()

        table = Table(title="Knowledge Base Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Strategies", str(stats["total_strategies"]))
        table.add_row("Total Usage", str(stats["total_usage"]))
        table.add_row("Average Success Rate", f"{stats['average_success_rate']:.2%}")

        console.print(table)
    except Exception as e:
        console.print(f"[red]Failed to get KB stats: {e}[/red]")


@kb_group.command(name="knowledge-add")
@click.option("--pattern", "-p", required=True, help="Error pattern (what went wrong)")
@click.option("--solution", "-s", required=True, help="Solution strategy (how to fix it)")
@click.option("--root-cause", "-r", default=None, help="Root cause analysis (optional)")
@click.option("--language", "-l", default=None, help="Programming language (optional)")
@click.option("--path", default=None, help="Knowledge base path (optional)")
def kb_knowledge_add(
    pattern: str, solution: str, root_cause: str | None, language: str | None, path: str | None
) -> None:
    """Add a strategy to the global knowledge base.

    This allows manual contribution of patterns and solutions that MUSCLE
    learns from.

    Examples:

        muscle kb knowledge-add --pattern "Auth token expired" --solution "Refresh token and retry"

        muscle kb knowledge-add -p "NullPointer in getUser" -s "Add null check" -l python
    """
    from .strategy_kb import GlobalKnowledgeBase

    try:
        gkb = GlobalKnowledgeBase(path)
        root = root_cause or f"Pattern: {pattern}"
        strategy_id = gkb.add_solution(
            error_pattern=pattern,
            root_cause=root,
            solution=solution,
            language=language,
        )
        if strategy_id > 0:
            console.print(f"[green]Added strategy #{strategy_id}: {pattern[:50]}[/green]")
        else:
            console.print("[red]Failed to add strategy[/red]")
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]Failed to add strategy: {e}[/red]")
        sys.exit(1)


@kb_group.command(name="export")
@click.argument("file", type=click.Path())
@click.option("--path", default=None, help="Knowledge base path")
def kb_export(file: str, path: str | None) -> None:
    """Export knowledge base to JSON file"""
    try:
        gkb = GlobalKnowledgeBase(path)
        gkb.strategy_kb.export_to_json(file)
        console.print(f"[green]Exported to {file}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to export KB: {e}[/red]")


@kb_group.command(name="import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--path", default=None, help="Knowledge base path")
def kb_import(file: str, path: str | None) -> None:
    """Import knowledge base from JSON file"""
    try:
        gkb = GlobalKnowledgeBase(path)
        count = gkb.strategy_kb.import_from_json(file)
        console.print(f"[green]Imported {count} strategies from {file}[/green]")
    except Exception as e:
        console.print(f"[red]Failed to import KB: {e}[/red]")


@kb_group.command(name="clear")
@click.option("--path", default=None, help="Knowledge base path")
@click.option("--force", is_flag=True, help="Skip confirmation")
def kb_clear(path: str | None, force: bool) -> None:
    """Clear all strategies from knowledge base"""
    if not force:
        if not click.confirm("Are you sure you want to clear all strategies?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    try:
        gkb = GlobalKnowledgeBase(path)
        gkb.strategy_kb.clear()
        console.print("[green]Knowledge base cleared[/green]")
    except Exception as e:
        console.print(f"[red]Failed to clear KB: {e}[/red]")


@cli.group(name="cost")
def cost_group() -> None:
    """Cost optimization and cache management commands"""
    pass


@cost_group.command(name="stats")
@click.option("--path", default=None, help="Cache directory path")
def cost_stats(path: str | None) -> None:
    """Show cost optimizer cache statistics"""
    cost_optimizer = CostOptimizer(cache_dir=path)
    stats = cost_optimizer.get_cache_stats()

    table = Table(title="Cost Optimizer Cache Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Cached Items", str(stats["cached_items"]))
    table.add_row("Total Size (bytes)", str(stats["total_size_bytes"]))
    table.add_row("Total Size (MB)", str(stats["total_size_mb"]))

    console.print(table)


@cost_group.command(name="clear")
@click.option("--path", default=None, help="Cache directory path")
@click.option("--force", is_flag=True, help="Skip confirmation")
def cost_clear(path: str | None, force: bool) -> None:
    """Clear cost optimizer cache"""
    if not force:
        if not click.confirm("Are you sure you want to clear the cost optimizer cache?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    cost_optimizer = CostOptimizer(cache_dir=path)
    count = cost_optimizer.clear_cache()
    console.print(f"[green]Cleared {count} cached items[/green]")


def _parse_since(since_str: str) -> timedelta:
    """Parse a human-friendly duration like '7d', '14d', '30d'."""
    unit = since_str[-1].lower()
    value = int(since_str[:-1])
    if unit == "d":
        return timedelta(days=value)
    if unit == "h":
        return timedelta(hours=value)
    raise click.BadParameter(f"Unsupported duration unit '{unit}'. Use 'd' (days) or 'h' (hours).")


@cost_group.command(name="delegation-report")
@click.option("--since", "since_str", default="7d", help="Lookback window (e.g. 7d, 14d, 30d)")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option(
    "--host-model", default="claude-opus-4-7", help="Host model for token-avoidance estimate"
)
def cost_delegation_report(since_str: str, fmt: str, host_model: str) -> None:
    """Show cost-delegation observability report."""
    from .delegation_metrics import DelegationMetrics

    since_td = _parse_since(since_str)
    metrics = DelegationMetrics(Path.cwd())
    rpt = metrics.report(since=since_td, host_model=host_model)

    if fmt == "json":
        click.echo(metrics.format_json(rpt))
    else:
        click.echo(metrics.format_text(rpt))


@cli.group(name="improve")
def improve_group() -> None:
    """Self-improvement and analysis commands"""
    pass


@improve_group.command(name="report")
def improve_report() -> None:
    """Run self-review and show improvement report"""
    improver = SelfImprover()
    report = improver.run_self_review()
    console.print(report)


@improve_group.command(name="export")
@click.argument("file", type=click.Path())
def improve_export(file: str) -> None:
    """Export improvement data to JSON file"""
    improver = SelfImprover()
    improver.export_data(file)
    console.print(f"[green]Exported improvement data to {file}[/green]")


@improve_group.command(name="import")
@click.argument("file", type=click.Path(exists=True))
def improve_import(file: str) -> None:
    """Import improvement data from JSON file"""
    improver = SelfImprover()
    count = improver.import_data(file)
    console.print(f"[green]Imported {count} session outcomes from {file}[/green]")


@improve_group.command(name="clear")
@click.option("--force", is_flag=True, help="Skip confirmation")
def improve_clear(force: bool) -> None:
    """Clear all logged improvement data"""
    if not force:
        if not click.confirm("Are you sure you want to clear all improvement data?"):
            console.print("[yellow]Aborted[/yellow]")
            return

    improver = SelfImprover()
    improver.clear_log()
    console.print("[green]Improvement data cleared[/green]")


@improve_group.command(name="prompt")
def improve_prompt() -> None:
    """Generate improved system prompt based on analysis"""
    improver = SelfImprover()
    prompt = improver.generate_improved_system_prompt()
    console.print(prompt)


@cli.group(name="notes")
def notes_group() -> None:
    """Project note management commands"""
    pass


@notes_group.command(name="add")
@click.option(
    "--category",
    "-c",
    required=True,
    type=click.Choice(["architecture", "workflow", "gotcha", "dependency", "integration"]),
    help="Note category",
)
@click.option("--title", "-t", required=True, help="Note title")
@click.option("--content", "-m", default="", help="Note content (multi-line supported)")
@click.option("--file", "-f", type=click.Path(exists=True), help="Read content from file")
def notes_add(category: str, title: str, content: str, file: str | None) -> None:
    """Add a new project note.

    Examples:

        muscle notes add -c architecture -t "Event-driven architecture" -m "Use pub/sub for decoupling"

        muscle notes add -c gotcha -t "Auth token expiry" -f /tmp/note.txt
    """
    from .project_memory import ProjectMemory
    from .project_notes import ProjectNotes

    note_content = content
    if file:
        note_content = Path(file).read_text(encoding="utf-8").strip()

    project_path = str(Path.cwd())
    memory = ProjectMemory(project_path)
    notes = ProjectNotes(memory, project_path)
    note_id = notes.add_note(category=category, title=title, content=note_content)
    console.print(f"[green]Added note #{note_id}: [{category}] {title}[/green]")


@notes_group.command(name="list")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice(["architecture", "workflow", "gotcha", "dependency", "integration"]),
    help="Filter by category",
)
@click.option("--limit", "-l", default=50, help="Maximum notes to show")
def notes_list(category: str | None, limit: int) -> None:
    """List project notes, optionally filtered by category."""
    from .project_memory import ProjectMemory
    from .project_notes import ProjectNotes

    project_path = str(Path.cwd())
    memory = ProjectMemory(project_path)
    notes = ProjectNotes(memory, project_path)

    entries = notes.get_notes(category=category, limit=limit)
    if not entries:
        console.print("[yellow]No notes found[/yellow]")
        return

    table = Table(title="Project Notes")
    table.add_column("ID", style="dim", width=4)
    table.add_column("Category", style="cyan", width=14)
    table.add_column("Title", style="white")
    table.add_column("Updated", style="dim")

    for entry in entries:
        table.add_row(
            str(entry.id),
            entry.category,
            entry.title[:60],
            entry.updated_at[:10],
        )
    console.print(table)


@notes_group.command(name="show")
@click.argument("note_id", type=int)
def notes_show(note_id: int) -> None:
    """Show full content of a note."""
    from .project_memory import ProjectMemory
    from .project_notes import ProjectNotes

    project_path = str(Path.cwd())
    memory = ProjectMemory(project_path)
    notes = ProjectNotes(memory, project_path)

    entries = notes.get_notes(limit=1000)
    entry = next((e for e in entries if e.id == note_id), None)
    if entry is None:
        console.print(f"[red]Note #{note_id} not found[/red]")
        sys.exit(1)

    console.print(
        Panel(
            entry.content or "(no content)",
            title=f"[bold][{entry.category}] {entry.title}[/bold]",
            subtitle=f"ID: {entry.id}  Updated: {entry.updated_at[:10]}",
        )
    )


@notes_group.command(name="update")
@click.argument("note_id", type=int)
@click.option("--title", "-t", default=None, help="New title")
@click.option("--content", "-m", default=None, help="New content")
@click.option(
    "--category",
    "-c",
    default=None,
    type=click.Choice(["architecture", "workflow", "gotcha", "dependency", "integration"]),
    help="New category",
)
def notes_update(
    note_id: int, title: str | None, content: str | None, category: str | None
) -> None:
    """Update an existing note's title, content, or category."""
    from .project_memory import ProjectMemory
    from .project_notes import ProjectNotes

    if not any([title, content, category]):
        console.print(
            "[yellow]No updates specified (use --title, --content, or --category)[/yellow]"
        )
        sys.exit(1)

    project_path = str(Path.cwd())
    memory = ProjectMemory(project_path)
    notes = ProjectNotes(memory, project_path)

    if notes.update_note(note_id, title=title, content=content, category=category):
        console.print(f"[green]Updated note #{note_id}[/green]")
    else:
        console.print(f"[red]Note #{note_id} not found[/red]")
        sys.exit(1)


@notes_group.command(name="dedupe")
@click.option(
    "--threshold",
    "-t",
    default=0.85,
    type=float,
    help="Similarity threshold 0.0-1.0 (default: 0.85)",
)
def notes_dedupe(threshold: float) -> None:
    """Detect and merge duplicate notes based on title similarity."""
    from .project_memory import ProjectMemory
    from .project_notes import ProjectNotes

    if not (0.0 <= threshold <= 1.0):
        console.print("[red]Threshold must be between 0.0 and 1.0[/red]")
        sys.exit(1)

    project_path = str(Path.cwd())
    memory = ProjectMemory(project_path)
    notes = ProjectNotes(memory, project_path)

    merged = notes.dedupe_notes(similarity_threshold=threshold)
    console.print(f"[green]Merged {merged} duplicate pair(s)[/green]")


def _session_report_to_dict(report: SessionReport) -> dict:
    from .types import BudgetInfo, CodeArtifact, IterationReport

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


@cli.command(name="review")
@click.option(
    "--target",
    "-t",
    required=True,
    help="Target path to review (file or directory)",
)
@click.option(
    "--language",
    "-l",
    default=None,
    help="Programming language (auto-detected if not specified)",
)
@click.option(
    "--mode",
    "-m",
    default="review",
    type=click.Choice(["review", "auto-fix", "plan", "hybrid", "pressure"]),
    help="Review mode",
)
@click.option(
    "--severity",
    "-s",
    default="low",
    type=click.Choice(["critical", "high", "medium", "low", "info"]),
    help="Minimum severity to report",
)
@click.option(
    "--max-fixes",
    "-n",
    default=5,
    help="Maximum auto-fixes per round",
)
@click.option(
    "--output",
    "-o",
    default=None,
    help="Output file for handoff plan (markdown)",
)
@click.option(
    "--format",
    "-f",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Output format",
)
@click.option(
    "--shadow",
    is_flag=True,
    default=False,
    help="Run in shadow (background) mode",
)
@click.option(
    "--intensity",
    "-i",
    default="moderate",
    type=click.Choice(["minimal", "moderate", "intensive", "exhaustive"]),
    help="Review intensity/thoroughness",
)
@click.option(
    "--failsafe",
    is_flag=True,
    default=False,
    help="Enable failsafe - stop on critical issues",
)
@click.option(
    "--focus",
    "-F",
    default=None,
    help="Pressure focus: design,failure,race,auth,data,rollback,reliability (comma-separated)",
)
@click.option(
    "--challenge",
    default=None,
    type=click.Choice(["fragility"]),
    help="Pressure challenge mode (pressure reviews only)",
)
@click.option(
    "--workflow",
    default=None,
    type=click.Choice(
        ["review-smart", "review-comprehensive", "review-fix-verify", "pressure-review"]
    ),
    help="Override the built-in review workflow",
)
@click.option(
    "--execution",
    default=None,
    type=click.Choice(["local", "worktree"]),
    help="Override review execution mode for this run",
)
@click.option(
    "--fetch-sources",
    is_flag=True,
    default=False,
    help="Fetch third-party JS/TS package sources via opensrc for enriched review context",
)
@click.option(
    "--source-package",
    multiple=True,
    default=(),
    help="Explicit package(s) to fetch (repeatable); overrides import-based discovery",
)
def review(
    target: str,
    language: str | None,
    mode: str,
    severity: str,
    max_fixes: int,
    output: str | None,
    format: str,
    shadow: bool,
    intensity: str,
    failsafe: bool,
    focus: str | None,
    challenge: str | None,
    workflow: str | None,
    execution: str | None,
    fetch_sources: bool,
    source_package: tuple[str, ...],
) -> None:
    """Review code for issues, auto-fix where possible, and generate handoff plans.

    Examples:

        muscle review --target ./src --language python

        muscle review --target ./src --mode hybrid --severity high

        muscle review --target ./src --mode plan --output handoff.md

        muscle review --target ./src --mode pressure --intensity intensive

        muscle review --target ./src --shadow  # Run in background

        muscle review --target ./src --mode pressure --focus design,failure,race
    """
    from .code_review import (
        Intensity,
        PressureFocus,
        ReviewConfig,
        ReviewController,
        ReviewEvent,
        ReviewMode,
        Severity,
    )

    severity_map = {
        "critical": Severity.CRITICAL,
        "high": Severity.HIGH,
        "medium": Severity.MEDIUM,
        "low": Severity.LOW,
        "info": Severity.INFO,
    }

    mode_map = {
        "review": ReviewMode.REVIEW,
        "auto-fix": ReviewMode.AUTO_FIX,
        "plan": ReviewMode.PLAN,
        "hybrid": ReviewMode.HYBRID,
        "pressure": ReviewMode.PRESSURE,
    }

    intensity_map = {
        "minimal": Intensity.MINIMAL,
        "moderate": Intensity.MODERATE,
        "intensive": Intensity.INTENSIVE,
        "exhaustive": Intensity.EXHAUSTIVE,
    }

    resolved_target = Path(target).resolve()
    execution_mode, resolved_project_path, _ = _resolve_review_execution_mode(
        resolved_target,
        execution,
    )
    project_path = str(resolved_project_path)
    configured_workflow = workflow
    try:
        optimization_memory = ProjectMemory(project_path)
        optimization_settings = WorkflowOptimizer(
            optimization_memory,
            project_path,
        ).get_applied_settings()
        if configured_workflow is None:
            configured_workflow = optimization_settings.get("optimize.default_workflow")
    except Exception as exc:
        logger.warning("Could not resolve optimization defaults for %s: %s", project_path, exc)

    if challenge and mode != "pressure":
        raise click.UsageError("--challenge is only supported with --mode pressure.")

    if fetch_sources and shadow:
        raise click.UsageError(
            "--fetch-sources is not supported with --shadow. "
            "Run a foreground review to use dependency context enrichment."
        )

    pressure_focus: PressureFocus | None = None
    if focus:
        selected_focus = {item.strip().lower() for item in focus.split(",") if item.strip()}
        pressure_focus = PressureFocus(
            design_tradeoffs="design" in selected_focus,
            failure_modes="failure" in selected_focus,
            race_conditions="race" in selected_focus,
            auth_security="auth" in selected_focus,
            data_loss="data" in selected_focus,
            rollback="rollback" in selected_focus,
            reliability="reliability" in selected_focus,
            custom_focus=",".join(
                item
                for item in sorted(selected_focus)
                if item
                not in {
                    "auth",
                    "data",
                    "design",
                    "failure",
                    "race",
                    "reliability",
                    "rollback",
                }
            )
            or None,
        )

    json_output = format == "json"

    if shadow:
        from .code_review.shadow_worker import WorkerManager

        worker_manager = WorkerManager(project_path=project_path)
        job_id = worker_manager.submit_shadow_job(
            target_path=str(resolved_target),
            mode=mode_map.get(mode, ReviewMode.REVIEW),
            intensity=intensity_map.get(intensity, Intensity.MODERATE),
            execution_mode=execution_mode,
            workflow_name=configured_workflow,
            detached=True,
        )
        console.print(f"[cyan]Shadow job created: {job_id}[/cyan]")
        console.print("Check status with: muscle probe")
        console.print("Get results with: muscle diagnosis")
        console.print("[dim]Detached worker launched in background...[/dim]")
        return

    def event_handler(event: ReviewEvent, data: dict) -> None:
        if event == ReviewEvent.REVIEW_START:
            console.print(f"\n[cyan]Starting code review session: {data['session']}[/cyan]")
        elif event == ReviewEvent.STATIC_ANALYSIS_COMPLETE:
            console.print(f"[cyan]Static analysis complete ({data['tools']} tools run)[/cyan]")
        elif event == ReviewEvent.SEMANTIC_REVIEW_COMPLETE:
            console.print(f"[cyan]Semantic review complete: {data['issues']} issues found[/cyan]")
        elif event == ReviewEvent.FIX_APPLIED:
            console.print(f"[green]Fixed: {data['file']}:{data['line']}[/green]")
        elif event == ReviewEvent.FIX_VERIFIED:
            console.print(
                f"[green]Verification complete, {data['remaining_issues']} issues remaining[/green]"
            )
        elif event == ReviewEvent.HANDOFF_GENERATED:
            console.print(
                f"[yellow]Handoff plan generated ({data['count']} complex issues)[/yellow]"
            )
        elif event == ReviewEvent.REVIEW_COMPLETE:
            stats = data.get("stats", {})
            console.print("\n[bold]Review Complete[/bold]")
            if stats.get("critical"):
                console.print(f"[red]Critical: {stats['critical']}[/red]")
            if stats.get("high"):
                console.print(f"[red]High: {stats['high']}[/red]")
            if stats.get("medium"):
                console.print(f"[yellow]Medium: {stats['medium']}[/yellow]")
            if stats.get("low"):
                console.print(f"Low: {stats['low']}")
            if stats.get("info"):
                console.print(f"Info: {stats['info']}")
            if data.get("artifact_dir"):
                console.print(f"[dim]Artifacts: {data['artifact_dir']}[/dim]")

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        if json_output:
            _emit_json(
                {
                    "error": "MINIMAX_API_KEY not set",
                    "required_env": ["MINIMAX_API_KEY", "ANTHROPIC_API_KEY"],
                }
            )
        else:
            console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
            console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    from .m27_client import M27Client

    m27_client = M27Client(api_key=api_key)
    pm, optimizer, context_budgeter, telemetry_recorder, lesson_resolver, _, _ = (
        _attach_optimization_runtime(
            project_path,
            m27_client,
        )
    )

    config = ReviewConfig(
        target_path=str(resolved_target),
        language=language,
        mode=mode_map.get(mode, ReviewMode.REVIEW),
        intensity=intensity_map.get(intensity, Intensity.MODERATE),
        severity_threshold=severity_map.get(severity, Severity.LOW),
        max_fixes_per_round=max_fixes,
        pressure_focus=pressure_focus,
        pressure_challenge=challenge,
        workflow_name=configured_workflow,
        review_profile=(
            "comprehensive" if configured_workflow == "review-comprehensive" else "smart"
        ),
        execution_mode=execution_mode,
        worktree_enabled=execution_mode == "worktree",
        fetch_sources=fetch_sources,
        fetch_source_packages=list(source_package) if source_package else None,
    )

    # Initialize ProjectMemory and LearningIngestor early for correction signal callback
    try:
        if pm is None:
            pm = ProjectMemory(project_path)
        ingestor = LearningIngestor(pm)
    except Exception as e:
        logger.warning(f"ProjectMemory init failed: {e}")
        pm = None
        ingestor = None

    # Correction signal callback for verification failures (MUS-023)
    def on_correction_signal(
        correction_type: str,
        severity: str | None = None,
        file_path: str | None = None,
        line_number: int | None = None,
        rule_id: str | None = None,
        description: str | None = None,
        **kwargs: object,
    ) -> None:
        if ingestor:
            try:
                ingestor.write_correction_signal(
                    project_path=project_path,
                    correction_type=correction_type,
                    source_table="review_findings",
                    source_id=0,  # Link to finding ID after ingest; 0 for immediate signal
                    severity=severity,
                    file_path=file_path,
                    line_number=line_number,
                    rule_id=rule_id,
                    description=description,
                )
            except Exception as e:
                logger.warning(f"Correction signal failed: {e}")

    controller = ReviewController(
        config=config,
        m27_client=m27_client,
        event_callback=None if json_output else event_handler,
        correction_signal_callback=on_correction_signal,
        project_path=project_path,
        context_budgeter=context_budgeter,
        lesson_resolver=lesson_resolver,
    )

    try:
        output_context = redirect_stdout(sys.stderr) if json_output else nullcontext()
        with output_context:
            result = controller.run()
            review_result = controller.get_review_result()
            savings_estimate = None
            if optimizer is not None and review_result is not None:
                stage_totals = _resolve_stage_totals(pm, project_path, review_result.session_id)
                target_type = "file" if resolved_target.is_file() else "directory"
                try:
                    savings_estimate = optimizer.record_review_outcome(
                        session_id=review_result.session_id,
                        workflow_name=review_result.workflow_name
                        or configured_workflow
                        or "legacy",
                        language=language,
                        complexity=str(
                            (review_result.scope_summary or {}).get("complexity", "unknown")
                        ),
                        target_type=target_type,
                        total_tokens=result.stats.tokens_used,
                        duration_ms=int(result.stats.duration_seconds * 1000),
                        valid_findings=len(review_result.issues),
                        verified_fixes=len(review_result.fixed_issues),
                        one_shot_verified_fixes=len(review_result.fixed_issues),
                        high_critical_findings=(
                            review_result.critical_count + review_result.high_count
                        ),
                        validation_success=result.stats.failed_fixes == 0,
                        success=True,
                        stage_totals=stage_totals,
                    )
                except Exception as exc:
                    logger.warning("Failed to record optimization outcome: %s", exc)

            # Self-learning: update CLAUDE.md, MEMORY.md, and skills
            if review_result:
                learn_result: dict[str, Any] = {}
                try:
                    duration_ms = int(result.stats.duration_seconds * 1000)
                    pipeline = LearningPipeline(
                        project_path=project_path,
                        m27_client=m27_client,
                    )
                    learn_result = pipeline.learn_from_review(
                        review_result,
                        review_mode=config.mode.value,
                        token_cost=result.stats.tokens_used,
                        duration_ms=duration_ms,
                    )
                    if not json_output and learn_result.get("rules_added"):
                        console.print(
                            f"[cyan]Learned {learn_result['rules_added']} new rules[/cyan]"
                        )
                    if not json_output and learn_result.get("skills_generated"):
                        console.print(
                            f"[cyan]Generated {learn_result['skills_generated']} new skills[/cyan]"
                        )
                except Exception as e:
                    logger.warning(f"Learning pipeline failed: {e}")

                # Record change events after review (MUS-021)
                if pm:
                    try:
                        from .change_capture import ChangeCapture

                        cc = ChangeCapture(project_path)
                        capture_result = cc.capture_and_store(pm, learn_result.get("review_run_id"))
                        if capture_result.get("changed_files_count", 0) > 0:
                            logger.debug(
                                f"Captured {capture_result['changed_files_count']} changed files "
                                f"as learning evidence"
                            )
                    except Exception as e:
                        logger.warning(f"ChangeCapture failed: {e}")

        if json_output and review_result:
            output_data = {
                "session_id": review_result.session_id,
                "target_path": review_result.target_path,
                "issues": [
                    {
                        "file": i.file_path,
                        "line": i.line_number,
                        "severity": i.severity.name,
                        "category": i.category.value,
                        "title": i.title,
                        "auto_fixable": i.auto_fixable,
                    }
                    for i in review_result.issues
                ],
                "summary": {
                    "critical": review_result.critical_count,
                    "high": review_result.high_count,
                    "medium": review_result.medium_count,
                    "low": review_result.low_count,
                    "info": review_result.info_count,
                },
                "workflow_name": review_result.workflow_name,
                "execution_mode": review_result.execution_mode,
                "duration_seconds": result.stats.duration_seconds,
                "tokens_used": result.stats.tokens_used,
            }
            _emit_json(output_data)
        else:
            if review_result:
                console.print("\n[bold]Review Summary[/bold]")
                console.print(f"Target: {review_result.target_path}")
                console.print(f"Execution: {review_result.execution_mode}")
                console.print(f"Issues found: {len(review_result.issues)}")
                if review_result.critical_count:
                    console.print(f"[red]Critical: {review_result.critical_count}[/red]")
                if review_result.high_count:
                    console.print(f"[red]High: {review_result.high_count}[/red]")
                if review_result.medium_count:
                    console.print(f"[yellow]Medium: {review_result.medium_count}[/yellow]")
                if review_result.low_count:
                    console.print(f"Low: {review_result.low_count}")
                if review_result.info_count:
                    console.print(f"Info: {review_result.info_count}")
                if savings_estimate and savings_estimate.baseline_tokens is not None:
                    delta_label = "saved" if savings_estimate.delta_tokens >= 0 else "overspend"
                    console.print(
                        f"Optimization {delta_label}: {abs(savings_estimate.delta_tokens):,} tokens "
                        f"({savings_estimate.estimation_type}, confidence {savings_estimate.confidence:.0%})"
                    )
                if optimizer is not None:
                    status = optimizer.get_status()
                    hotspots = status.get("hotspots", [])
                    recommendations = status.get("recommendations", [])
                    if hotspots:
                        hotspot = hotspots[0]
                        console.print(
                            "Top token hotspot: "
                            f"{hotspot.get('stage', 'unknown')} "
                            f"({int(hotspot.get('total_tokens', 0) or 0):,} tokens)"
                        )
                    if recommendations:
                        recommendation = recommendations[0]
                        console.print(
                            "Optimization suggestion: "
                            f"{recommendation.get('decision_scope')} -> "
                            f"{recommendation.get('recommended_value')} "
                            f"({recommendation.get('reason', '')})"
                        )

        if output and result.handoff_plan:
            Path(output).write_text(result.handoff_plan.markdown, encoding="utf-8")
            if not json_output:
                console.print(f"\n[green]Handoff plan written to {output}[/green]")

        _refresh_active_review_safe(project_path, reason="review-complete")

    except KeyboardInterrupt:
        console.print("\n[yellow]Review interrupted by user[/yellow]")
        sys.exit(130)
    finally:
        if telemetry_recorder is not None:
            telemetry_recorder.close()


@cli.group(name="optimize")
def optimize_group() -> None:
    """Project-local optimization and token-efficiency commands."""


@optimize_group.command(name="status")
def optimize_status() -> None:
    """Show optimization status for the current project."""
    project_root, _ = _resolve_project_context(Path.cwd())
    project_path = str(project_root)
    pm = ProjectMemory(project_path)
    optimizer = WorkflowOptimizer(pm, project_path)
    status = optimizer.get_status()
    savings = status["savings"]

    summary = Table(title="Optimization Status")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="white")
    summary.add_row("Project", project_path)
    summary.add_row("Net Tokens Saved", f"{int(savings.get('net_tokens_saved', 0) or 0):,}")
    summary.add_row("Gross Tokens Saved", f"{int(savings.get('gross_tokens_saved', 0) or 0):,}")
    summary.add_row("Overspend Tokens", f"{int(savings.get('overspend_tokens', 0) or 0):,}")
    summary.add_row("Confidence", f"{float(savings.get('confidence', 0.0) or 0.0):.0%}")
    console.print(summary)

    hotspots_table = Table(title="Top Token Hotspots")
    hotspots_table.add_column("Stage", style="magenta")
    hotspots_table.add_column("Calls", justify="right")
    hotspots_table.add_column("Tokens", justify="right")
    hotspots_table.add_column("Avg Context", justify="right")
    hotspots = status.get("hotspots", [])
    if hotspots:
        for hotspot in hotspots:
            hotspots_table.add_row(
                str(hotspot.get("stage", "unknown")),
                str(hotspot.get("call_count", 0)),
                f"{int(hotspot.get('total_tokens', 0) or 0):,}",
                str(int(float(hotspot.get("avg_context_chars", 0) or 0))),
            )
    else:
        hotspots_table.add_row("No telemetry yet", "0", "0", "0")
    console.print(hotspots_table)


@optimize_group.command(name="recommendations")
def optimize_recommendations() -> None:
    """Show safe optimization recommendations for the current project."""
    project_root, _ = _resolve_project_context(Path.cwd())
    project_path = str(project_root)
    pm = ProjectMemory(project_path)
    optimizer = WorkflowOptimizer(pm, project_path)
    recommendations = optimizer.build_recommendations()

    table = Table(title="Optimization Recommendations")
    table.add_column("Type", style="cyan")
    table.add_column("Scope", style="magenta")
    table.add_column("Current", style="white")
    table.add_column("Recommended", style="green")
    table.add_column("Confidence", justify="right")
    table.add_column("Reason", style="dim")

    if not recommendations:
        console.print("[yellow]No safe recommendations yet[/yellow]")
        table.add_row("none", "—", "—", "—", "0%", "No safe recommendations yet")
    else:
        for recommendation in recommendations:
            table.add_row(
                recommendation.decision_type,
                recommendation.decision_scope,
                recommendation.current_value,
                recommendation.recommended_value,
                f"{recommendation.confidence:.0%}",
                recommendation.reason[:80],
            )
    console.print(table)


@optimize_group.command(name="apply")
@click.option(
    "--safe-only/--no-safe-only", default=True, help="Apply only safe runtime optimizations"
)
def optimize_apply(safe_only: bool) -> None:
    """Apply safe project-local optimization recommendations."""
    project_root, _ = _resolve_project_context(Path.cwd())
    project_path = str(project_root)
    pm = ProjectMemory(project_path)
    optimizer = WorkflowOptimizer(pm, project_path)
    applied = optimizer.apply_recommendations(safe_only=safe_only)
    if not applied:
        console.print("[yellow]No recommendations were applied[/yellow]")
        return

    table = Table(title="Applied Optimizations")
    table.add_column("Type", style="cyan")
    table.add_column("Scope", style="magenta")
    table.add_column("Value", style="green")
    for recommendation in applied:
        table.add_row(
            recommendation.decision_type,
            recommendation.decision_scope,
            recommendation.recommended_value,
        )
    console.print(table)


@optimize_group.command(name="history")
def optimize_history() -> None:
    """Show persisted optimization decisions for the current project."""
    project_root, _ = _resolve_project_context(Path.cwd())
    project_path = str(project_root)
    pm = ProjectMemory(project_path)
    decisions = pm.list_optimization_decisions(project_path, limit=50)

    table = Table(title="Optimization History")
    table.add_column("When", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Scope", style="magenta")
    table.add_column("Applied", style="green")
    table.add_column("Confidence", justify="right")

    if not decisions:
        table.add_row("—", "none", "—", "no", "0%")
    else:
        for decision in decisions:
            table.add_row(
                str(decision.get("created_at", ""))[:16],
                str(decision.get("decision_type", "")),
                str(decision.get("decision_scope", "")),
                "yes" if int(decision.get("applied", 0) or 0) else "no",
                f"{float(decision.get('confidence', 0.0) or 0.0):.0%}",
            )
    console.print(table)


@optimize_group.command(name="import")
@click.option(
    "--provider",
    default="all",
    type=click.Choice(["claude", "codex", "all"]),
    help="External transcript provider to import",
)
@click.option(
    "--since", "since_days", default=30, type=int, help="Import sessions from the last N days"
)
def optimize_import(provider: str, since_days: int) -> None:
    """Import external Claude/Codex benchmark sessions for the current project."""
    project_root, _ = _resolve_project_context(Path.cwd())
    project_path = str(project_root)
    pm = ProjectMemory(project_path)
    importer = ExternalBenchmarkImporter(pm, project_path)
    summary = importer.import_sessions(provider=provider, since_days=since_days)

    table = Table(title="Imported Benchmark Sessions")
    table.add_column("Provider", style="cyan")
    table.add_column("Sessions", justify="right")
    table.add_column("Turns", justify="right")
    for provider_name, provider_summary in summary.items():
        table.add_row(
            provider_name,
            str(provider_summary.get("sessions_imported", 0)),
            str(provider_summary.get("turns_imported", 0)),
        )
    console.print(table)
    _refresh_active_review_safe(project_root, reason="optimize-import")


@cli.command(name="lifeline")
@click.option("--target", "-t", required=True, help="Target directory or file to investigate")
@click.option("--prompt", "-p", required=True, help="Task or question to investigate")
@click.option("--model", "-m", default=None, help="Model to use (optional)")
@click.option(
    "--history/--no-history",
    default=False,
    help="Attach targeted git history forensics to the investigation",
)
@click.option(
    "--bisect-cmd",
    default=None,
    help="Optional deterministic command to run via temporary git bisect",
)
@click.option(
    "--intensity",
    "-i",
    type=click.Choice(["minimal", "moderate", "intensive", "exhaustive"]),
    default="moderate",
    help="Investigation intensity",
)
def lifeline(
    target: str,
    prompt: str,
    model: str | None,
    history: bool,
    bisect_cmd: str | None,
    intensity: str,
) -> None:
    """Throw a lifeline to M2.7 to investigate issues, propose fixes, or debug problems.

    Unlike review which focuses on finding issues, lifeline is for:
    - Investigating a specific bug or error
    - Proposing and validating fixes
    - Debugging failing tests
    - Continuing previous investigation threads

    Examples:

        muscle lifeline --target ./src --prompt "investigate why auth is failing"

        muscle lifeline --target ./tests --prompt "debug the flaky integration test"

        muscle lifeline --target ./src/auth.py --prompt "suggest improvements to error handling"
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    from .m27_client import M27Client

    m27_client = M27Client(api_key=api_key)
    history_requested = history or bisect_cmd is not None
    history_summary = ""
    history_artifact = ""
    if history_requested:
        from .git_history_forensics import GitHistoryForensics

        project_path, _ = _resolve_project_context(Path(target).resolve())
        report = GitHistoryForensics(str(project_path)).analyze(target, bisect_cmd=bisect_cmd)
        if report.get("available"):
            history_summary = str(report.get("summary") or "")
            report_paths = report.get("report_paths") or {}
            if isinstance(report_paths, dict):
                history_artifact = str(report_paths.get("json") or "")
        else:
            logger.info(
                "Git history forensics unavailable for %s: %s", target, report.get("reason")
            )

    system_prompt = f"""You are a debugging and investigation assistant. Your task is to:
1. Investigate the reported issue thoroughly
2. Trace through the code to understand root causes
3. Propose concrete fixes
4. Validate that your fixes work

Be methodical. Check edge cases. Verify your assumptions.

Investigation intensity: {intensity.capitalize()}"""

    user_prompt = f"""Target: {target}
Task: {prompt}

Please investigate this thoroughly and provide your findings and proposed solutions."""
    if history_summary:
        user_prompt += (
            "\n\nUse this git history evidence first before requesting broader source context:\n"
            f"{history_summary}"
        )

    try:
        console.print("[cyan]Throwing lifeline to M2.7...[/cyan]")
        console.print(f"[dim]Target: {target}[/dim]")
        console.print(f"[dim]Intensity: {intensity}[/dim]")
        if history_artifact:
            console.print(f"[dim]History artifact: {history_artifact}[/dim]")

        response, usage = m27_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        console.print("\n[bold green]Lifeline Response:[/bold green]\n")
        console.print(response)

        console.print(f"\n[dim]Tokens used: {usage.total}[/dim]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Lifeline cancelled by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command(name="probe")
@click.option("--job-id", "-j", default=None, help="Specific job ID to check")
def probe(job_id: str | None) -> None:
    """Check the status of shadow (background) review jobs.

    Without --job-id, shows all active and recent jobs.
    With --job-id, shows detailed status of that specific job.

    Examples:

        muscle probe                    # Show all recent jobs

        muscle probe --job-id abc12345  # Show specific job status
    """
    from .code_review.shadow_broker import ShadowBroker

    broker = ShadowBroker(project_path=str(Path.cwd()))

    if job_id:
        job = broker.get_job(job_id)
        if not job:
            console.print(f"[red]Job {job_id} not found[/red]")
            sys.exit(1)

        console.print(f"[bold]Shadow Job: {job_id}[/bold]")
        console.print(f"Status: [{_get_status_color(job['status'])}]{job['status']}[/]")
        console.print(f"Target: {job['target_path']}")
        console.print(f"Mode: {job['mode']}")
        console.print(f"Intensity: {job['intensity']}")
        console.print(f"Created: {job['created_at']}")
        if job.get("started_at"):
            console.print(f"Started: {job['started_at']}")
        if job.get("completed_at"):
            console.print(f"Completed: {job['completed_at']}")
        if job.get("error_message"):
            console.print(f"[red]Error: {job['error_message']}[/red]")
    else:
        active_jobs = broker.get_active_jobs()
        recent_jobs = broker.get_recent_jobs(limit=10)

        if not recent_jobs:
            console.print("[yellow]No shadow jobs found[/yellow]")
            console.print("Run 'muscle review --shadow' to start a background review")
            return

        console.print("[bold]Shadow Jobs:[/bold]\n")

        if active_jobs:
            console.print("[bold cyan]Active:[/bold cyan]")
            for job in active_jobs:
                console.print(f"  [{job['job_id']}] {job['status']} - {job['target_path']}")

        console.print("\n[bold]Recent:[/bold]")
        for job in recent_jobs:
            status_color = _get_status_color(job["status"])
            console.print(
                f"  [{job['job_id']}] [{status_color}]{job['status']}[/] - {job['target_path']} ({job['created_at']})"
            )


@cli.command(name="diagnosis")
@click.option("--job-id", "-j", default=None, help="Specific job ID to get diagnosis")
def diagnosis(job_id: str | None) -> None:
    """Get the final diagnosis/results from a completed shadow job.

    Without --job-id, shows the most recent completed job's results.

    Examples:

        muscle diagnosis                    # Show most recent results

        muscle diagnosis --job-id abc12345  # Show specific job results
    """
    from .code_review.shadow_broker import ShadowBroker

    broker = ShadowBroker(project_path=str(Path.cwd()))

    if job_id:
        job = broker.get_job(job_id)
        if not job:
            console.print(f"[red]Job {job_id} not found[/red]")
            sys.exit(1)
    else:
        recent_completed = [
            item for item in broker.get_recent_jobs(limit=20) if item.get("status") == "completed"
        ]
        if not recent_completed:
            console.print("[yellow]No completed jobs found[/yellow]")
            sys.exit(1)
        job = recent_completed[0]
        job_id = job["job_id"]

    if job["status"] != "completed":
        console.print(f"[yellow]Job {job_id} is not completed yet: {job['status']}[/yellow]")
        if job["status"] == "running":
            console.print(f"Use 'muscle probe --job-id {job_id}' to check progress")
        return

    result = job.get("result")
    if not result:
        console.print(f"[yellow]No results available for job {job_id}[/yellow]")
        return

    console.print(f"[bold green]Diagnosis for Job {job_id}:[/bold green]\n")

    if isinstance(result, dict) and "issues" in result:
        issues = result["issues"]
        console.print(f"Issues found: {len(issues)}")

        critical = sum(1 for i in issues if i.get("severity") == "CRITICAL")
        high = sum(1 for i in issues if i.get("severity") == "HIGH")
        medium = sum(1 for i in issues if i.get("severity") == "MEDIUM")

        if critical:
            console.print(f"[red]Critical: {critical}[/red]")
        if high:
            console.print(f"[red]High: {high}[/red]")
        if medium:
            console.print(f"[yellow]Medium: {medium}[/yellow]")

        console.print("\n[bold]Top Issues:[/bold]")
        for issue in issues[:10]:
            sev = issue.get("severity", "MEDIUM")
            color = "red" if sev in ("CRITICAL", "HIGH") else "yellow"
            console.print(f"  [{color}]{sev}[/] {issue.get('title', 'Unknown')}")

    elif isinstance(result, dict) and "pressure_findings" in result:
        findings = result.get("pressure_findings", [])
        console.print(f"Pressure findings: {len(findings)}")
        for finding in findings[:10]:
            sev = finding.get("severity", "MEDIUM")
            color = "red" if sev in ("CRITICAL", "HIGH") else "yellow"
            console.print(f"  [{color}]{sev}[/] {finding.get('title', 'Unknown')}")

    else:
        console.print(result)

    _refresh_active_review_safe(Path.cwd(), reason="diagnosis")


@cli.group(name="long-eval")
def long_eval_group() -> None:
    """Manual deep evaluation and report management."""
    pass


@long_eval_group.command(name="run")
@click.option("--target", "-t", default=None, help="Target path to review")
def long_eval_run(target: str | None) -> None:
    """Run a deep evaluation pass on the project (manual).

    This runs a thorough review across target paths, generates a report,
    and triggers the learning pipeline.

    Examples:

        muscle long-eval run                    # Evaluate current directory

        muscle long-eval run --target ./src     # Evaluate ./src directory
    """
    from .code_review.long_eval_runner import LongEvalConfig, LongEvalRunner

    project_path = target or str(Path.cwd())
    config = LongEvalConfig(target_paths=[project_path] if target else None)
    runner = LongEvalRunner(project_path, config)
    console.print(f"[cyan]Running long evaluation on {project_path}...[/cyan]")

    result = runner.run_long_eval()
    if result:
        console.print(f"[green]Completed: {result.get('total_issues', 0)} issues found[/green]")
        console.print(f"Duration: {result.get('duration_seconds', 0):.1f}s")
        critical = len(result.get("critical_issues", []))
        high = len(result.get("high_issues", []))
        if critical:
            console.print(f"[red]Critical: {critical}[/red]")
        if high:
            console.print(f"[red]High: {high}[/red]")
    else:
        console.print("[yellow]No report generated.[/yellow]")


@long_eval_group.command(name="mutate")
@click.option("--target", "-t", required=True, help="Python file or directory to mutate")
@click.option(
    "--test-command",
    default=None,
    help="Command used to evaluate each mutant (defaults to project pytest command)",
)
@click.option("--limit", default=12, help="Maximum number of mutants to run")
@click.option("--timeout", default=300, help="Timeout per mutant in seconds")
def long_eval_mutate(
    target: str,
    test_command: str | None,
    limit: int,
    timeout: int,
) -> None:
    """Run deterministic Python mutation testing in disposable workspaces."""
    from .code_review.mutation_runner import MutationRunner

    resolved_target = Path(target).resolve()
    project_root, _ = _resolve_project_context(resolved_target)
    runner = MutationRunner(str(project_root))
    console.print(f"[cyan]Running mutation evaluation on {resolved_target}...[/cyan]")
    report = runner.run(
        str(resolved_target),
        test_command=test_command,
        limit=limit,
        timeout_seconds=timeout,
    )
    console.print(
        f"[green]Mutation run complete:[/green] "
        f"killed={report['killed']} survived={report['survived']} timeouts={report['timeouts']}"
    )
    report_paths = report.get("report_paths", {})
    if isinstance(report_paths, dict) and report_paths.get("json"):
        console.print(f"[dim]Report: {report_paths['json']}[/dim]")


@long_eval_group.command(name="reports")
@click.option("--limit", "-n", default=7, help="Number of reports to show")
def long_eval_reports(limit: int) -> None:
    """List recent long evaluation reports."""
    from .code_review.long_eval_runner import LongEvalRunner

    runner = LongEvalRunner(str(Path.cwd()))
    reports = runner.list_reports(limit=limit)

    if not reports:
        console.print("[yellow]No long evaluation reports found.[/yellow]")
        console.print("Run 'muscle long-eval run' to generate the first report.")
        return

    table = Table(title=f"Recent Long Evaluation Reports (last {len(reports)})")
    table.add_column("Date", style="cyan")
    table.add_column("Total Issues", style="yellow")
    table.add_column("Critical", style="red")
    table.add_column("High", style="red")

    for report in reports:
        table.add_row(
            report.get("date", "unknown"),
            str(report.get("total_issues", 0)),
            str(report.get("critical_count", 0)),
            str(report.get("high_count", 0)),
        )

    console.print(table)


@long_eval_group.command(name="cleanup")
@click.option("--days", "-d", default=30, help="Keep reports for N days")
@click.option("--force", is_flag=True, help="Skip confirmation")
def long_eval_cleanup(days: int, force: bool) -> None:
    """Clean up old long evaluation reports."""
    from .code_review.long_eval_runner import LongEvalRunner

    runner = LongEvalRunner(str(Path.cwd()))
    if not force:
        if not click.confirm(f"Remove reports older than {days} days?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    removed = runner.cleanup_old_reports(days_to_keep=days)
    console.print(f"[green]Removed {removed} old reports.[/green]")


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


@long_eval_group.command(name="benchmark")
@click.option(
    "--baseline",
    default="legacy",
    type=click.Choice(["legacy", "review-smart", "review-comprehensive"]),
    help="Baseline review path to compare against",
)
@click.option(
    "--candidate",
    default="review-smart",
    type=click.Choice(["review-smart", "review-comprehensive", "review-fix-verify"]),
    help="Candidate workflow to benchmark",
)
@click.option(
    "--history/--no-history",
    default=True,
    help="Include review_runs/review_findings history replay trends",
)
@click.option(
    "--suite",
    default="all",
    type=click.Choice(
        [
            "all",
            "core-review",
            "neutral-baseline",
            "related-project",
            "unrelated-project",
            "model-pack",
        ]
    ),
    help="Benchmark fixture suite to run",
)
@click.option(
    "--enforce-gates/--no-enforce-gates",
    default=False,
    help="Evaluate release gates, save release evidence, and exit non-zero on failures",
)
def long_eval_benchmark(
    baseline: str,
    candidate: str,
    history: bool,
    suite: str,
    enforce_gates: bool,
) -> None:
    """Run the manual review benchmark harness."""
    from .code_review.review_benchmark import ReviewBenchmarkRunner

    if enforce_gates and suite != "all":
        raise click.ClickException(
            "Release gate enforcement requires running the full benchmark suite."
        )

    console.print(
        f"[cyan]Running benchmark: baseline={baseline}, candidate={candidate}, suite={suite}[/cyan]"
    )
    runner = ReviewBenchmarkRunner(str(Path.cwd()))
    report = runner.run_benchmark(
        baseline=baseline,
        candidate=candidate,
        include_history=history,
        suite=suite,
    )
    aggregate = report["aggregate"]
    thresholds = report["thresholds"]
    benchmark_gates = dict(report.get("benchmark_gates", {}))
    meta_harness = dict(report.get("meta_harness", {}))
    console.print("[bold]Benchmark Complete[/bold]")
    console.print(
        f"High/Critical recall: {aggregate['baseline']['high_critical_recall']:.2%} -> "
        f"{aggregate['candidate']['high_critical_recall']:.2%}"
    )
    console.print(
        f"False positive rate: {aggregate['baseline']['false_positive_rate']:.2%} -> "
        f"{aggregate['candidate']['false_positive_rate']:.2%}"
    )
    console.print(
        f"Token cost: {aggregate['baseline']['tokens_used']} -> "
        f"{aggregate['candidate']['tokens_used']}"
    )
    console.print(f"Reports: {report['report_paths']['json']}")
    console.print(
        "Thresholds: "
        f"recall+20%={thresholds['high_critical_recall_up_20pct']}, "
        f"fp_not_worse={thresholds['false_positive_rate_not_worse']}, "
        f"token-30%={thresholds['token_cost_down_30pct']}"
    )
    if benchmark_gates:
        console.print(f"Benchmark gates overall: {benchmark_gates.get('overall_passed', False)}")
    if meta_harness:
        host_memory = dict(meta_harness.get("host_memory", {}))
        routing = dict(meta_harness.get("routing", {}))
        if host_memory:
            console.print(
                "Host-memory chars: "
                f"{host_memory.get('baseline_chars', 0)} -> "
                f"{host_memory.get('candidate_chars', 0)}"
            )
        if routing:
            console.print(
                "Routing quality matches: "
                f"{routing.get('baseline_quality', 0)} -> "
                f"{routing.get('candidate_quality', 0)}"
            )
        if meta_harness.get("promotion_rule"):
            console.print(f"Promotion rule: {meta_harness['promotion_rule']}")

    if enforce_gates:
        console.print("[cyan]Running focused release invariant checks...[/cyan]")
        release_evidence = runner.build_release_evidence(
            report,
            operational_invariants={"offline_guardrails": _run_benchmark_release_invariants()},
        )
        evidence_paths = runner.write_release_evidence(release_evidence)
        console.print(f"Release evidence: {evidence_paths['json']}")
        failed_gates = [
            gate_name
            for gate_name, gate in release_evidence["release_gates"]["gates"].items()
            if not gate["passed"]
        ]
        if failed_gates:
            raise click.ClickException("Release gates failed: " + ", ".join(sorted(failed_gates)))
        console.print("[green]Release gates passed[/green]")


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


@cli.group(name="memory")
def memory_group() -> None:
    """Inspect memory database, rules, and decisions."""
    pass


@memory_group.command(name="status")
def memory_status() -> None:
    """Show memory database statistics (rules, reviews, decisions)."""
    resolved_project_path, _ = _resolve_project_context(Path.cwd())
    project_path = str(resolved_project_path)
    try:
        pm = ProjectMemory(project_path)
        stats = pm.get_statistics(project_path)
        recommendations = pm.list_transferred_lesson_recommendations(
            project_path=project_path,
            only_candidates=True,
            limit=500,
        )
        promotion_candidates = sum(1 for row in recommendations if row["promotion_candidate"])
        archive_candidates = sum(1 for row in recommendations if row["archive_candidate"])

        db_path = pm._db_path
        schema_version = pm.get_schema_version()

        table = Table(title="Memory Status")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Database", str(db_path))
        table.add_row("Schema Version", schema_version or "unknown")
        table.add_row("Learned Rules", str(stats.get("total_learned_rules", 0)))
        table.add_row("Review Runs", str(stats.get("total_reviews", 0)))
        table.add_row("Total Findings", str(stats.get("total_findings", 0)))
        table.add_row("Skills", str(stats.get("total_skills", 0)))
        table.add_row("Agents", str(stats.get("total_agents", 0)))
        table.add_row("Related Projects", str(stats.get("related_projects", 0)))
        table.add_row("Transferred Lessons", str(stats.get("transferred_lessons", 0)))
        table.add_row(
            "Validated Transferred Lessons",
            str(stats.get("validated_transferred_lessons", 0)),
        )
        table.add_row(
            "Promoted Transferred Lessons",
            str(stats.get("promoted_transferred_lessons", 0)),
        )
        table.add_row(
            "Archived Transferred Lessons",
            str(stats.get("archived_transferred_lessons", 0)),
        )
        table.add_row("Promotion Candidates", str(promotion_candidates))
        table.add_row("Archive Candidates", str(archive_candidates))
        avg_rate = stats.get("avg_rule_success_rate")
        avg_rate_str = f"{avg_rate:.1%}" if avg_rate is not None else "N/A"
        table.add_row("Avg Rule Success Rate", avg_rate_str)

        console.print(table)

        external_lessons = pm.list_transferred_lesson_recommendations(
            project_path=project_path,
            include_inactive=True,
            limit=5,
        )
        if external_lessons:
            console.print()
            lesson_table = Table(title="Transferred Lesson Snapshot")
            lesson_table.add_column("ID", style="cyan", justify="right")
            lesson_table.add_column("Source", style="blue")
            lesson_table.add_column("Status", style="magenta")
            lesson_table.add_column("Recommendation", style="green")
            lesson_table.add_column("Why", style="white")
            for lesson in external_lessons:
                lesson_table.add_row(
                    str(int(lesson.get("id", 0) or 0)),
                    _source_project_name(str(lesson.get("source_project_path", "") or "")),
                    str(lesson.get("validation_status", "")),
                    str(lesson.get("recommendation", "")),
                    _truncate(str(lesson.get("status_explanation", "")), 64),
                )
            console.print(lesson_table)
    except Exception as e:
        console.print(f"[red]Failed to get memory status: {e}[/red]")


@memory_group.command(name="history")
@click.option("--limit", "-n", default=10, help="Number of entries to show")
def memory_history(limit: int) -> None:
    """Show recent review sessions and memory decisions."""
    resolved_project_path, _ = _resolve_project_context(Path.cwd())
    project_path = str(resolved_project_path)
    try:
        pm = ProjectMemory(project_path)

        runs = pm.list_review_runs(project_path=project_path, limit=limit)
        decisions = pm.list_decisions(project_path=project_path, limit=limit)
        transferred = pm.list_transferred_lesson_recommendations(
            project_path=project_path,
            include_inactive=True,
            limit=limit,
        )
        transfer_audit = pm.list_action_logs(
            project_path=project_path,
            action_types=TRANSFER_AUDIT_ACTIONS,
            limit=limit,
        )

        console.print("[bold cyan]Recent Review Runs[/bold cyan]")
        if not runs:
            console.print("[yellow]No review runs recorded.[/yellow]")
        else:
            runs_table = Table()
            runs_table.add_column("ID", style="cyan", width=4)
            runs_table.add_column("Mode", style="magenta")
            runs_table.add_column("Findings", style="yellow", justify="right")
            runs_table.add_column("Tokens", style="dim", justify="right")
            runs_table.add_column("Created", style="green")
            for r in runs:
                runs_table.add_row(
                    str(r["id"]),
                    r.get("review_mode", "unknown"),
                    str(r.get("findings_count", 0)),
                    str(r.get("token_cost", 0)),
                    r.get("created_at", "")[:19],
                )
            console.print(runs_table)

        console.print()
        console.print("[bold cyan]Recent Memory Decisions[/bold cyan]")
        if not decisions:
            console.print("[yellow]No memory decisions recorded.[/yellow]")
        else:
            dec_table = Table()
            dec_table.add_column("ID", style="cyan", width=4)
            dec_table.add_column("Type", style="magenta")
            dec_table.add_column("Source", style="yellow")
            dec_table.add_column("Reasoning", style="green")
            for d in decisions:
                source_label = str(d.get("source_table", "") or "")
                if source_label == "transferred_lessons":
                    try:
                        evidence = json.loads(str(d.get("evidence_json", "{}") or "{}"))
                    except (TypeError, ValueError):
                        evidence = {}
                    source_label = f"transferred:{_source_project_name(str(evidence.get('source_project_path', '') or ''))}"
                reasoning = _truncate(d.get("reasoning", ""), 50)
                dec_table.add_row(
                    str(d["id"]),
                    d.get("decision_type", "unknown"),
                    source_label,
                    reasoning,
                )
            console.print(dec_table)

        console.print()
        console.print("[bold cyan]Transferred Lesson Lifecycle[/bold cyan]")
        if not transferred:
            console.print("[yellow]No transferred lessons recorded.[/yellow]")
        else:
            lesson_table = Table()
            lesson_table.add_column("ID", style="cyan", width=4)
            lesson_table.add_column("Source", style="blue")
            lesson_table.add_column("Status", style="magenta")
            lesson_table.add_column("Evidence", style="yellow")
            lesson_table.add_column("Why", style="green")
            for row in transferred:
                evidence = (
                    f"{int(row.get('success_count', 0) or 0)}/"
                    f"{int(row.get('validation_count', 0) or 0)} "
                    f"({float(row.get('success_rate', 0.0) or 0.0):.0%})"
                )
                lesson_table.add_row(
                    str(int(row.get("id", 0) or 0)),
                    _source_project_name(str(row.get("source_project_path", "") or "")),
                    str(row.get("validation_status", "")),
                    evidence,
                    _truncate(
                        str(row.get("status_explanation") or row.get("recommendation_reason", "")),
                        70,
                    ),
                )
            console.print(lesson_table)

        console.print()
        console.print("[bold cyan]Transferred Lesson Audit[/bold cyan]")
        if not transfer_audit:
            console.print("[yellow]No transferred-lesson audit entries recorded.[/yellow]")
        else:
            audit_table = Table()
            audit_table.add_column("When", style="dim", width=16)
            audit_table.add_column("Action", style="cyan")
            audit_table.add_column("Entity", style="yellow")
            audit_table.add_column("Details", style="white")
            for entry in transfer_audit:
                formatted = format_action_log_entry(entry)
                audit_table.add_row(
                    formatted["when"],
                    formatted["action"],
                    formatted["entity"],
                    _truncate(formatted["details"], 72),
                )
            console.print(audit_table)

        usage_events = pm.list_lesson_usage_events(project_path=project_path, limit=limit)
        console.print()
        console.print("[bold cyan]Lesson Usage Events[/bold cyan]")
        if not usage_events:
            console.print("[yellow]No lesson-usage events recorded.[/yellow]")
        else:
            usage_table = Table()
            usage_table.add_column("When", style="dim", width=16)
            usage_table.add_column("Stage", style="cyan")
            usage_table.add_column("Source", style="magenta")
            usage_table.add_column("Lesson", style="yellow")
            usage_table.add_column("Outcome", style="green")
            usage_table.add_column("Details", style="white")
            for row in usage_events:
                metadata = _parse_json_dict(row.get("metadata_json"))
                details = (
                    str(metadata.get("reason") or "")
                    or str(metadata.get("applied_from") or "")
                    or str(metadata.get("validation_note") or "")
                )
                usage_table.add_row(
                    str(row.get("created_at", ""))[:16],
                    str(row.get("stage") or "—"),
                    _truncate(_lesson_usage_source_label(row), 24),
                    _truncate(str(row.get("lesson_key") or "—"), 24),
                    str(row.get("outcome") or "pending"),
                    _truncate(details, 40) if details else "—",
                )
            console.print(usage_table)
    except Exception as e:
        console.print(f"[red]Failed to get memory history: {e}[/red]")


@memory_group.command(name="related")
@click.option(
    "--refresh/--no-refresh",
    default=True,
    show_default=True,
    help="Refresh the current project fingerprint before suggesting overlaps",
)
@click.option(
    "--prune-stale/--no-prune-stale",
    default=False,
    show_default=True,
    help="Prune missing or stale project registrations before suggesting overlaps",
)
@click.option(
    "--stale-days",
    default=90,
    show_default=True,
    help="Treat projects not refreshed within this many days as stale",
)
@click.option(
    "--include-stale/--hide-stale",
    default=False,
    show_default=True,
    help="Include stale registrations in the suggestion table",
)
def memory_related(refresh: bool, prune_stale: bool, stale_days: int, include_stale: bool) -> None:
    """Suggest the most related registered MUSCLE projects."""
    project_path, project = _resolve_project_context(Path.cwd())
    from .tui.project_manager import ProjectManager

    if refresh:
        ProjectManager(base_path=project_path).register_project(project_path)

    if prune_stale:
        pruned = SystemDatabase().prune_registered_projects(
            stale_after_days=stale_days,
            keep_paths=[str(project_path.resolve())],
        )
        if pruned["removed"]:
            console.print(
                f"[cyan]Pruned[/cyan] {pruned['removed']} stale registrations "
                f"({pruned['missing_removed']} missing, {pruned['stale_removed']} stale)."
            )

    suggestions = _suggest_related_projects(
        project_path,
        project,
        refresh_current=False,
        stale_days=stale_days,
        include_stale=include_stale,
    )
    if not suggestions:
        console.print(
            "[yellow]No related MUSCLE projects found above the overlap threshold.[/yellow]"
        )
        return

    table = Table(title="Related Projects")
    table.add_column("Project", style="cyan")
    table.add_column("Score", style="green")
    table.add_column("Languages", style="magenta")
    table.add_column("Frameworks", style="yellow")
    table.add_column("Why", style="white")
    table.add_column("State", style="blue")
    table.add_column("Path", style="dim")
    for suggestion in suggestions:
        table.add_row(
            str(suggestion["display_name"]),
            f"{float(suggestion['score']):.2f}",
            ", ".join(suggestion.get("languages", [])) or "-",
            ", ".join(suggestion.get("frameworks", [])) or "-",
            str(suggestion.get("why", "")),
            (
                f"stale ({suggestion['age_days']}d)"
                if suggestion.get("stale")
                else f"fresh ({suggestion['age_days']}d)"
                if suggestion.get("age_days") is not None
                else "fresh"
            ),
            str(suggestion["project_path"]),
        )
    console.print(table)


@memory_group.command(name="refresh-catalog")
@click.option(
    "--project",
    "project_arg",
    default=".",
    show_default=True,
    help="Project path to refresh in the global catalog",
)
@click.option(
    "--prune-stale/--no-prune-stale",
    default=False,
    show_default=True,
    help="Prune missing or stale registrations after refreshing the selected project",
)
@click.option(
    "--stale-days",
    default=90,
    show_default=True,
    help="Treat projects not refreshed within this many days as stale",
)
@click.option(
    "--missing-only/--all-stale",
    default=False,
    show_default=True,
    help="Only prune missing paths instead of all stale registrations",
)
def memory_refresh_catalog(
    project_arg: str,
    prune_stale: bool,
    stale_days: int,
    missing_only: bool,
) -> None:
    """Refresh the global registered-project catalog for one MUSCLE project."""
    from .tui.project_manager import ProjectManager

    target_path = Path(project_arg).expanduser().resolve()
    manager = ProjectManager(base_path=target_path)
    muscle_dir = manager.get_muscle_dir(target_path)
    if not muscle_dir:
        console.print("[red]Target project is not MUSCLE-initialized.[/red]")
        return

    manager.register_project(target_path)
    console.print(f"[green]Refreshed[/green] project fingerprint for {target_path}")

    if prune_stale:
        pruned = SystemDatabase().prune_registered_projects(
            stale_after_days=stale_days,
            missing_only=missing_only,
            keep_paths=[str(target_path)],
        )
        console.print(
            f"[cyan]Pruned[/cyan] {pruned['removed']} registrations "
            f"({pruned['missing_removed']} missing, {pruned['stale_removed']} stale)."
        )


@memory_group.command(name="import-project")
@click.option("--project", "source_project", required=True, help="Source project path")
@click.option(
    "--mode",
    type=click.Choice(["snapshot", "attach"]),
    default="snapshot",
    show_default=True,
    help="Transfer mode",
)
def memory_import_project(source_project: str, mode: str) -> None:
    """Import or attach lessons from a related MUSCLE project."""
    project_path, project = _resolve_project_context(Path.cwd())
    source_path = Path(source_project).expanduser().resolve()
    from .tui.project_manager import ProjectManager

    if not (source_path / ".muscle").exists():
        console.print("[red]Source project is not MUSCLE-initialized.[/red]")
        return

    current_manager = ProjectManager(base_path=project_path)
    current_manager.register_project(project_path)
    ProjectManager(base_path=source_path).register_project(source_path)

    suggestions = _suggest_related_projects(
        project_path,
        project,
        limit=20,
        threshold=0.0,
        refresh_current=False,
    )
    score = 0.0
    for suggestion in suggestions:
        if str(source_path) == str(Path(str(suggestion["project_path"])).resolve()):
            score = float(suggestion["score"])
            break

    pm = ProjectMemory(str(project_path))
    result = pm.import_project_lessons(
        project_path=str(project_path),
        source_project_path=str(source_path),
        link_mode=mode,
        relatedness_score=score,
    )
    if mode == "attach":
        console.print(f"[green]Attached[/green] related project: {source_path}")
    else:
        console.print(
            f"[green]Imported[/green] {result['imported']} provisional lessons from {source_path}"
        )
    if score > 0.0:
        matched = next(
            (
                suggestion
                for suggestion in suggestions
                if str(source_path) == str(Path(str(suggestion["project_path"])).resolve())
            ),
            None,
        )
        if matched is not None:
            console.print(f"[dim]Overlap:[/dim] {matched['why']}")


@memory_group.command(name="linked")
def memory_linked() -> None:
    """Show related projects currently attached or imported into this project."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    links = pm.list_related_project_links(project_path=str(project_path))
    if not links:
        console.print("[yellow]No related projects are currently linked.[/yellow]")
        return

    table = Table(title="Linked Projects")
    table.add_column("Mode", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Score", style="yellow")
    table.add_column("Source", style="magenta")
    for link in links:
        table.add_row(
            str(link.get("link_mode", "")),
            str(link.get("status", "")),
            f"{float(link.get('relatedness_score', 0.0) or 0.0):.2f}",
            str(link.get("source_project_path", "")),
        )
    console.print(table)


@memory_group.command(name="unlink")
@click.option("--project", "source_project", required=True, help="Source project path to unlink")
def memory_unlink(source_project: str) -> None:
    """Remove a related-project link from this project."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    pm.unlink_related_project(str(project_path), str(Path(source_project).expanduser().resolve()))
    console.print("[green]Related project unlinked.[/green]")


@memory_group.command(name="lesson-feedback")
@click.option("--lesson-key", required=True, help="Transferred lesson key to confirm or reject")
@click.option(
    "--accept/--reject",
    "accepted",
    default=True,
    show_default=True,
    help="Record positive confirmation or negative rejection for the lesson",
)
@click.option("--note", default="", help="Optional note to record alongside the feedback")
def memory_lesson_feedback(lesson_key: str, accepted: bool, note: str) -> None:
    """Record explicit user feedback for a transferred lesson."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    if not pm.record_manual_transferred_lesson_feedback(
        lesson_key,
        success=accepted,
        note=note or None,
    ):
        console.print("[red]Transferred lesson not found for this project.[/red]")
        return

    action = "confirmed" if accepted else "rejected"
    console.print(f"[green]Lesson {action}.[/green] {lesson_key}")


@memory_group.command(name="promotion-candidates")
@click.option(
    "--all/--candidates-only",
    "include_all",
    default=False,
    show_default=True,
    help="Show all active transferred lessons instead of only promotion or archive candidates",
)
@click.option(
    "--limit", default=20, show_default=True, help="Maximum number of transferred lessons to show"
)
def memory_promotion_candidates(include_all: bool, limit: int) -> None:
    """Review transferred lessons and MUSCLE's promote/archive recommendations."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    recommendations = pm.list_transferred_lesson_recommendations(
        project_path=str(project_path),
        include_inactive=include_all,
        only_candidates=not include_all,
        limit=limit,
    )
    if not recommendations:
        console.print(
            "[yellow]No transferred-lesson promotion or archive candidates are pending.[/yellow]"
        )
        return

    table = Table(title="Transferred Lesson Recommendations")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Recommendation", style="green")
    table.add_column("Status", style="magenta")
    table.add_column("Evidence", style="yellow")
    table.add_column("Source", style="blue")
    table.add_column("Why", style="white")
    for row in recommendations:
        source_path = str(row.get("source_project_path", "") or "")
        source_label = Path(source_path).name if source_path else "-"
        evidence = (
            f"{int(row.get('success_count', 0) or 0)}/"
            f"{int(row.get('validation_count', 0) or 0)} "
            f"({float(row.get('success_rate', 0.0) or 0.0):.0%})"
        )
        table.add_row(
            str(int(row.get("id", 0) or 0)),
            str(row.get("recommendation", "observe")),
            str(row.get("validation_status", "")),
            evidence,
            source_label,
            _truncate(str(row.get("recommendation_reason", "")), 72),
        )
    console.print(table)


@memory_group.command(name="promote-lesson")
@click.option(
    "--lesson-id",
    type=int,
    required=True,
    help="Transferred lesson ID to promote into local memory",
)
@click.option(
    "--force/--no-force",
    default=False,
    show_default=True,
    help="Bypass recommendation checks and promote based on explicit user confirmation",
)
def memory_promote_lesson(lesson_id: int, force: bool) -> None:
    """Promote one transferred lesson into project-local learned rules."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    recommendation = pm.get_transferred_lesson_recommendation(lesson_id)
    if recommendation is None:
        console.print("[red]Transferred lesson not found for this project.[/red]")
        return

    local_rule_id = pm.promote_transferred_lesson(lesson_id, force=force)
    if not local_rule_id:
        console.print(
            "[red]Lesson is not ready for promotion.[/red] "
            f"{recommendation['recommendation_reason']}"
        )
        return

    console.print(
        "[green]Promoted[/green] transferred lesson "
        f"{lesson_id} into local learned rule {local_rule_id}."
    )


@memory_group.command(name="archive-lesson")
@click.option("--lesson-id", type=int, required=True, help="Transferred lesson ID to archive")
@click.option(
    "--reason",
    default="Archived after insufficient current-project evidence.",
    show_default=True,
    help="Why this external lesson should be archived",
)
@click.option(
    "--force/--no-force",
    default=False,
    show_default=True,
    help="Allow manual archive even when MUSCLE would normally keep observing the lesson",
)
def memory_archive_lesson(lesson_id: int, reason: str, force: bool) -> None:
    """Archive one transferred lesson so it no longer participates in prompt context."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    recommendation = pm.get_transferred_lesson_recommendation(lesson_id)
    if recommendation is None:
        console.print("[red]Transferred lesson not found for this project.[/red]")
        return

    archived = pm.archive_transferred_lesson(lesson_id, reason=reason, force=force)
    if not archived:
        console.print(
            f"[red]Lesson is not ready to archive.[/red] {recommendation['recommendation_reason']}"
        )
        return

    console.print(f"[green]Archived[/green] transferred lesson {lesson_id}.")


# ---------------------------------------------------------------------------
# Model identity and model packs
# ---------------------------------------------------------------------------


@cli.group(name="model")
def model_group() -> None:
    """Inspect and configure model identity plus model-pack overlays."""
    pass


@model_group.command(name="status")
def model_status() -> None:
    """Show resolved model identity and installed pack state."""
    project_path, project = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    identity = _resolve_model_identity(str(project_path), project, project_memory=pm)
    packs = SystemDatabase().list_model_packs()
    active_packs = [
        pack
        for pack in packs
        if pack.get("canonical_model_key") == identity.get("canonical_model_key")
    ]

    table = Table(title="Model Status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Requested Label", str(identity.get("requested_label") or "Unknown"))
    table.add_row("Provider Endpoint", str(identity.get("provider_endpoint") or "Unknown"))
    table.add_row("Canonical Model", str(identity.get("canonical_model_key") or "Unresolved"))
    table.add_row("Identity Source", str(identity.get("identity_source") or "unresolved"))
    table.add_row("Confidence", f"{float(identity.get('confidence', 0.0) or 0.0):.2f}")
    table.add_row(
        "Manual Override",
        str(getattr(project, "model_manual_override", None) or "None"),
    )
    table.add_row("Pack Mode", str(getattr(project, "model_pack_mode", "suggest")))
    table.add_row("Active Pack Count", str(len(active_packs)))
    console.print(table)


@model_group.command(name="history")
@click.option("--limit", "-n", default=10, help="Number of identity events to show")
def model_history(limit: int) -> None:
    """Show recent model identity resolution history for this project."""
    project_path, _ = _resolve_project_context(Path.cwd())
    pm = ProjectMemory(str(project_path))
    history = pm.list_model_identity_history(project_path=str(project_path), limit=limit)

    if not history:
        console.print("[yellow]No model identity history recorded yet.[/yellow]")
        return

    table = Table(title="Model Identity History")
    table.add_column("When", style="dim", width=16)
    table.add_column("Requested", style="cyan")
    table.add_column("Canonical", style="green")
    table.add_column("Source", style="magenta")
    table.add_column("Conf", style="yellow", justify="right")
    table.add_column("Manual", style="white")
    table.add_column("Endpoint", style="dim")

    for row in history:
        table.add_row(
            str(row.get("created_at", ""))[:16],
            _truncate(str(row.get("requested_label") or "—"), 22),
            _truncate(str(row.get("canonical_model_key") or "Unresolved"), 24),
            _truncate(str(row.get("identity_source") or "unresolved"), 18),
            f"{float(row.get('confidence', 0.0) or 0.0):.2f}",
            "yes" if bool(row.get("manual_override")) else "no",
            _truncate(str(row.get("provider_endpoint") or "—"), 28),
        )

    console.print(table)


@model_group.command(name="select")
@click.option(
    "--canonical-model",
    type=str,
    help="Canonical model key (for example minimax/m2.7@1)",
)
@click.option("--clear", is_flag=True, help="Clear the current manual override")
@click.option(
    "--pack-mode",
    type=click.Choice(["off", "suggest", "auto"]),
    default=None,
    help="Project-level model-pack mode",
)
def model_select(canonical_model: str | None, clear: bool, pack_mode: str | None) -> None:
    """Select or clear the canonical model for this project."""
    from .tui.project_manager import ProjectManager

    project_path, project = _resolve_project_context(Path.cwd())
    manager = ProjectManager()

    update_kwargs: dict[str, Any] = {}
    if clear:
        update_kwargs["model_manual_override"] = ""
        update_kwargs["canonical_model_key"] = ""
        update_kwargs["model_identity_source"] = "unresolved"
    elif canonical_model:
        update_kwargs["model_manual_override"] = canonical_model
        update_kwargs["canonical_model_key"] = canonical_model
        update_kwargs["model_identity_source"] = "manual_override"

    if pack_mode:
        update_kwargs["model_pack_mode"] = pack_mode

    if not update_kwargs:
        console.print("Use --canonical-model, --clear, or --pack-mode to update model settings.")
        return

    manager.update_muscle_config(project_path, **update_kwargs)
    identity = _resolve_model_identity(str(project_path), project)
    console.print(
        f"[green]Model settings updated.[/green] Effective canonical model: "
        f"{identity.get('canonical_model_key') or 'Unresolved'}"
    )


@model_group.group(name="packs")
def model_packs_group() -> None:
    """Manage model-pack overlays."""
    pass


@model_packs_group.command(name="list")
def model_packs_list() -> None:
    """List installed model packs."""
    packs = SystemDatabase().list_model_packs()
    if not packs:
        console.print("[yellow]No model packs installed.[/yellow]")
        return

    table = Table(title="Installed Model Packs")
    table.add_column("Canonical Model", style="cyan")
    table.add_column("Version", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Path", style="dim")
    for pack in packs:
        table.add_row(
            str(pack.get("canonical_model_key", "")),
            str(pack.get("version", "")),
            str(pack.get("install_status", "")),
            str(pack.get("pack_path", "") or "-"),
        )
    console.print(table)


@model_packs_group.command(name="install")
@click.option("--bundle-path", default=None, help="Path to an exported model-pack bundle")
@click.option("--canonical-model", default=None, help="Canonical model key to fetch from repo")
@click.option("--repo", default=DEFAULT_MODEL_PACK_REPO, show_default=True, help="Source repo")
@click.option("--ref", default=DEFAULT_MODEL_PACK_REF, show_default=True, help="Source ref")
def model_packs_install(
    bundle_path: str | None,
    canonical_model: str | None,
    repo: str,
    ref: str,
) -> None:
    """Install a model pack from a local bundle or the community repo."""
    project_path, project = _resolve_project_context(Path.cwd())
    expected_canonical_model_key = getattr(project, "canonical_model_key", None) or None
    if bool(bundle_path) == bool(canonical_model):
        raise click.ClickException(
            "Provide exactly one of --bundle-path or --canonical-model for model pack install."
        )
    manager = ModelPackManager(str(project_path))
    try:
        if bundle_path:
            metadata = manager.install_bundle(
                bundle_path,
                expected_canonical_model_key=expected_canonical_model_key,
            )
        else:
            metadata = manager.install_remote_bundle(
                canonical_model_key=str(canonical_model),
                repo=repo,
                ref=ref,
                expected_canonical_model_key=expected_canonical_model_key,
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        f"[green]Installed[/green] model pack {metadata.canonical_model_key} "
        f"version {metadata.version}"
    )


@model_packs_group.command(name="update")
@click.option("--canonical-model", required=True, help="Canonical model key to refresh")
@click.option("--bundle-path", default=None, help="Optional explicit bundle path")
@click.option("--repo", default=None, help="Optional explicit source repo override")
@click.option("--ref", default=None, help="Optional explicit source ref override")
def model_packs_update(
    canonical_model: str,
    bundle_path: str | None,
    repo: str | None,
    ref: str | None,
) -> None:
    """Refresh an installed model pack."""
    project_path, _ = _resolve_project_context(Path.cwd())
    try:
        metadata = ModelPackManager(str(project_path)).update_bundle(
            canonical_model,
            bundle_path,
            repo=repo,
            ref=ref,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        f"[green]Updated[/green] model pack {metadata.canonical_model_key} "
        f"to version {metadata.version}"
    )


@model_packs_group.command(name="export-candidate")
@click.option("--canonical-model", default=None, help="Canonical model key to export for")
@click.option("--output", default=None, help="Output directory for the candidate bundle")
@click.option("--rule-id", "rule_ids", multiple=True, type=int, help="Specific learned rule IDs")
def model_packs_export_candidate(
    canonical_model: str | None,
    output: str | None,
    rule_ids: tuple[int, ...],
) -> None:
    """Export a deterministic model-pack candidate bundle from local lessons."""
    project_path, project = _resolve_project_context(Path.cwd())
    effective_model = canonical_model or getattr(project, "canonical_model_key", None)
    if not effective_model:
        console.print("[red]No canonical model selected. Use `muscle model select` first.[/red]")
        return

    manager = ModelPackManager(str(project_path))
    result = manager.export_candidate_bundle(
        canonical_model_key=effective_model,
        output_dir=output,
        rule_ids=list(rule_ids) or None,
    )
    console.print(
        f"[green]Exported[/green] {result.lesson_count} lessons to {result.bundle_dir} "
        f"(export id: {result.export_id})"
    )
    if result.skipped_rule_ids:
        console.print(
            f"[yellow]Skipped rule IDs:[/yellow] {', '.join(map(str, result.skipped_rule_ids))}"
        )


@model_packs_group.command(name="scaffold-repo")
@click.option("--output-dir", required=True, help="Directory for the model-pack repo scaffold")
def model_packs_scaffold_repo(output_dir: str) -> None:
    """Scaffold the public model-pack repository standard locally."""
    project_path, _ = _resolve_project_context(Path.cwd())
    result = ModelPackManager(str(project_path)).scaffold_repository_standard(output_dir)
    console.print(f"[green]Scaffolded[/green] model-pack repository standard at {result.root_dir}")
    console.print(f"Wrote {len(result.files_written)} files.")


@model_packs_group.command(name="submit")
@click.option("--bundle-path", required=True, help="Path to an exported model-pack bundle")
@click.option("--repo", default=DEFAULT_MODEL_PACK_REPO, show_default=True, help="Target repo")
@click.option("--base-branch", default="main", show_default=True, help="Base branch")
@click.option("--draft/--no-draft", default=True, help="Open the PR as draft")
def model_packs_submit(
    bundle_path: str,
    repo: str,
    base_branch: str,
    draft: bool,
) -> None:
    """Submit an exported model-pack bundle to the community repo as a draft PR."""
    if not draft:
        console.print("[red]Only draft PR submission is supported for model packs.[/red]")
        return

    project_path, _ = _resolve_project_context(Path.cwd())
    try:
        result = ModelPackManager(str(project_path)).submit_draft_pr(
            bundle_path=bundle_path,
            repo=repo,
            base_branch=base_branch,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if result.get("status") == "duplicate_existing":
        console.print(
            "[yellow]Reused existing draft submission.[/yellow] "
            f"{result.get('pr_url') or 'No PR URL returned'}"
        )
        return
    console.print(
        f"[green]Draft submission prepared.[/green] {result.get('pr_url') or 'No PR URL returned'}"
    )


# ---------------------------------------------------------------------------
# Skills inspection
# ---------------------------------------------------------------------------


@cli.group(name="skills")
def skills_group() -> None:
    """List available project skills (alias: muscle skills list)."""
    pass


@skills_group.command(name="list")
@click.option("--path", default=None, help="Skills directory path")
def skills_list(path: str | None) -> None:
    """List skills from .muscle/skills/ directory."""
    project_path = Path.cwd()
    skills_dir = Path(path) if path else (project_path / ".muscle" / "skills")

    if not skills_dir.exists():
        console.print(f"[yellow]Skills directory not found: {skills_dir}[/yellow]")
        return

    skills_files: list[Path] = []
    if skills_dir.is_dir():
        skills_files = (
            sorted(skills_dir.rglob("*.md"))
            + sorted(skills_dir.rglob("*.yaml"))
            + sorted(skills_dir.rglob("*.json"))
        )
    else:
        skills_files = [skills_dir]

    if not skills_files:
        console.print("[yellow]No skills found.[/yellow]")
        return

    table = Table(title=f"Skills ({skills_dir})")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="green")
    for sf in skills_files:
        name = sf.stem
        try:
            rel_path = str(sf.relative_to(project_path))
        except ValueError:
            rel_path = str(sf)
        table.add_row(name, rel_path)
    console.print(table)


# ---------------------------------------------------------------------------
# Agents inspection
# ---------------------------------------------------------------------------


@cli.group(name="agents")
def agents_group() -> None:
    """List available project agents (alias: muscle agents list)."""
    pass


@agents_group.command(name="list")
@click.option("--path", default=None, help="Agents directory path")
def agents_list(path: str | None) -> None:
    """List agents from .muscle/agents/ directory."""
    project_path = Path.cwd()
    agents_dir = Path(path) if path else (project_path / ".muscle" / "agents")

    if not agents_dir.exists():
        console.print(f"[yellow]Agents directory not found: {agents_dir}[/yellow]")
        return

    agents_files: list[Path] = []
    if agents_dir.is_dir():
        agents_files = (
            sorted(agents_dir.rglob("*.md"))
            + sorted(agents_dir.rglob("*.yaml"))
            + sorted(agents_dir.rglob("*.json"))
        )
    else:
        agents_files = [agents_dir]

    if not agents_files:
        console.print("[yellow]No agents found.[/yellow]")
        return

    table = Table(title=f"Agents ({agents_dir})")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="green")
    for af in agents_files:
        name = af.stem
        try:
            rel_path = str(af.relative_to(project_path))
        except ValueError:
            rel_path = str(af)
        table.add_row(name, rel_path)
    console.print(table)


# ---------------------------------------------------------------------------
# Backups management
# ---------------------------------------------------------------------------


@cli.group(name="backups")
def backups_group() -> None:
    """Backup list, inspect, and restore management."""
    pass


@backups_group.command(name="list")
@click.option(
    "--type",
    "backup_type",
    default=None,
    help="Filter by backup type (full, claude_md, config, memory)",
)
@click.option("--limit", "-n", default=20, help="Maximum number of backups to list")
def backups_list(backup_type: str | None, limit: int) -> None:
    """List all available backups with timestamps, types, and sizes."""

    project_path = str(Path.cwd())
    try:
        pm = ProjectMemory(project_path)
        bm = BackupManager(pm, project_path)

        valid_types: set[str] = {"full", "claude_md", "config", "memory"}
        if backup_type and backup_type not in valid_types:
            console.print(f"[red]Invalid backup type: {backup_type}[/red]")
            console.print(f"Valid types: {', '.join(sorted(valid_types))}")
            return

        backups = bm.list_backups(backup_type=backup_type if backup_type else None, limit=limit)  # type: ignore[arg-type]

        if not backups:
            console.print("[yellow]No backups found.[/yellow]")
            _print_backup_scope_note(bm)
            return

        table = Table(title="Backups")
        table.add_column("ID", style="cyan", width=4)
        table.add_column("Type", style="magenta")
        table.add_column("Created At", style="green")
        table.add_column("Size", style="yellow", justify="right")
        table.add_column("Retention", style="dim")

        for b in backups:
            size_str = _format_size(b.size_bytes)
            table.add_row(str(b.id), b.backup_type, b.created_at, size_str, f"{b.retention_days}d")

        console.print(table)
        _print_backup_scope_note(bm)
    except Exception as e:
        console.print(f"[red]Failed to list backups: {e}[/red]")


@backups_group.command(name="show")
@click.argument("backup_id", type=int)
def backups_show(backup_id: int) -> None:
    """Show backup metadata and contents preview."""
    project_path = str(Path.cwd())
    try:
        pm = ProjectMemory(project_path)
        bm = BackupManager(pm, project_path)

        info = bm.inspect_backup(backup_id)
        if not info:
            console.print(f"[red]Backup #{backup_id} not found.[/red]")
            _print_backup_scope_note(bm)
            return

        table = Table(title=f"Backup #{backup_id}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Type", info["backup_type"])
        table.add_row("Created", info["created_at"])
        table.add_row("Size", _format_size(info["size_bytes"]))
        table.add_row("Checksum", info["checksum"] or "N/A")
        table.add_row("Archive", info["file_path"])
        table.add_row("Retention", f"{info['retention_days']} days")

        console.print(table)

        if info.get("contents"):
            contents_table = Table(title="Contents")
            contents_table.add_column("Name", style="cyan")
            contents_table.add_column("Size", style="yellow", justify="right")
            contents_table.add_column("Type", style="dim")
            for item in info["contents"]:
                size_str = _format_size(item["size"]) if not item["isdir"] else "<dir>"
                kind = "dir" if item["isdir"] else "file"
                contents_table.add_row(item["name"], size_str, kind)
            console.print(contents_table)
        else:
            console.print("[yellow]No contents info available.[/yellow]")
        _print_backup_scope_note(bm)

    except Exception as e:
        console.print(f"[red]Failed to show backup: {e}[/red]")


@backups_group.command(name="restore")
@click.argument("backup_id", type=int)
@click.option("--dry-run", is_flag=True, help="Preview restore without making changes")
def backups_restore(backup_id: int, dry_run: bool) -> None:
    """Restore .muscle/ files from a backup snapshot.

    By default performs the restoration. Use --dry-run to preview
    what would be changed without modifying any files.
    """
    project_path = str(Path.cwd())
    try:
        pm = ProjectMemory(project_path)
        bm = BackupManager(pm, project_path)

        result = bm.restore_backup(backup_id, dry_run=dry_run)
        if not result:
            console.print(f"[red]Backup #{backup_id} not found.[/red]")
            _print_backup_scope_note(bm)
            return

        if "error" in result:
            console.print(f"[red]Restore failed: {result['error']}[/red]")
            _print_backup_scope_note(bm)
            return

        console.print(f"[cyan]{result['message']}[/cyan]")

        if result.get("files"):
            table = Table(title="Files" + (" (dry-run)" if dry_run else ""))
            table.add_column("Source", style="cyan")
            table.add_column("Destination", style="green")
            table.add_column("Size", style="yellow", justify="right")
            for f in result["files"]:
                table.add_row(f["name"], f["destination"], _format_size(f["size"]))
            console.print(table)
        _print_backup_scope_note(bm)

    except Exception as e:
        console.print(f"[red]Failed to restore backup: {e}[/red]")


@cli.group(name="audit")
def audit_group() -> None:
    """Audit trail: show recent publish, backup, skill, and agent actions."""
    pass


@audit_group.command(name="list")
@click.option("--limit", "-n", default=30, help="Maximum number of entries to show")
@click.option(
    "--action",
    "-a",
    type=click.Choice(
        [
            "publish",
            "backup",
            "restore",
            "skill_create",
            "skill_revise",
            "skill_archive",
            "agent_create",
            "agent_archive",
            "related_project_imported",
            "related_project_attached",
            "related_project_unlinked",
            "related_import_scrub",
            "transferred_lesson_validated",
            "transferred_lesson_promoted",
            "transferred_lesson_archived",
        ]
    ),
    default=None,
    help="Filter by action type",
)
def audit_list(limit: int, action: str | None) -> None:
    """Show recent audit log entries (publish, backup, restore, skill/agent lifecycle)."""
    resolved_project_path, _ = _resolve_project_context(Path.cwd())
    project_path = str(resolved_project_path)
    try:
        pm = ProjectMemory(project_path)
        entries = pm.list_action_logs(
            project_path=project_path,
            action_type=action,
            limit=limit,
        )

        table = Table(title=f"Recent Actions (last {len(entries)})")
        table.add_column("When", style="dim", width=16)
        table.add_column("Action", style="cyan", width=28)
        table.add_column("Entity", style="yellow", width=28)
        table.add_column("Details", style="white")

        if not entries:
            console.print("[dim]No audit entries yet.[/dim]")
            return

        for entry in entries:
            formatted = format_action_log_entry(entry)
            table.add_row(
                formatted["when"],
                formatted["action"],
                formatted["entity"],
                formatted["details"][:60],
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Failed to list audit entries: {e}[/red]")


@cli.group(name="settings")
def settings_group() -> None:
    """MUSCLE settings and configuration management."""
    pass


@settings_group.command(name="show")
def settings_show() -> None:
    """Show current MUSCLE settings."""
    project_path, project = _resolve_project_context(Path.cwd())

    table = Table(title="MUSCLE Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    if project:
        table.add_row("Project", project.name)
        table.add_row("Platform", project.platform)
        table.add_row("API Key Source", project.api_key_source)
        table.add_row("Hooks Enabled", str(project.hooks_enabled))
        table.add_row("CLI Path", project.cli_path or "Not set")
        table.add_row("Review Gate", project.review_gate)
        table.add_row("Review Execution", project.review_execution)
        table.add_row("Automation Level", project.automation_level)
        table.add_row("Related Project Mode", project.related_project_mode)
        table.add_row("Model Pack Mode", project.model_pack_mode)
        table.add_row("Manual Model Override", project.model_manual_override or "None")
        table.add_row("Canonical Model", project.canonical_model_key or "Unresolved")
        table.add_row("Model Identity Source", project.model_identity_source)

        try:
            pm = ProjectMemory(str(project_path))
            stats = pm.get_statistics(str(project_path))
            table.add_row("Attached Projects", str(stats.get("attached_projects", 0)))
            table.add_row("Imported Lessons", str(stats.get("transferred_lessons", 0)))
        except Exception:
            table.add_row("Imported Lessons", "N/A")
    else:
        table.add_row("Project", "Not initialized")
        table.add_row("Run 'muscle init'", "to initialize")

    api_key_status = "Set" if os.environ.get("MINIMAX_API_KEY") else "Not set"
    table.add_row("MINIMAX_API_KEY", api_key_status)

    console.print(table)


@settings_group.command(name="api-key")
@click.option("--key", "-k", help="API key to set")
@click.option("--source", type=click.Choice(["env", "opencode", "ask"]), help="API key source")
def settings_api_key(key: str | None, source: str | None) -> None:
    """Set or configure API key for MUSCLE.

    Examples:

        muscle settings api-key --key sk-xxxxx

        muscle settings api-key --source opencode
    """
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path, _ = _resolve_project_context(Path.cwd())

    if key:
        os.environ["MINIMAX_API_KEY"] = key
        console.print("[green]API key set (stored in environment)[/green]")

    if source:
        manager.update_muscle_config(project_path, api_key_source=source)
        console.print(f"[green]API key source set to: {source}[/green]")
    if key or source:
        _refresh_active_review_safe(project_path, reason="settings-api-key")

    if not key and not source:
        current_key = os.environ.get("MINIMAX_API_KEY", "")
        console.print(
            f"Current API key: {current_key[:10]}..." if current_key else "No API key set"
        )
        new_key = console.input("Enter new API key (or press Enter to keep current): ").strip()
        if new_key:
            os.environ["MINIMAX_API_KEY"] = new_key
            console.print("[green]API key updated[/green]")


@settings_group.command(name="hooks")
@click.option("--enable/--disable", default=None, help="Enable or disable hooks")
@click.option(
    "--gate",
    type=click.Choice(["block+fix", "block-all", "warn", "disabled"]),
    help="Review gate mode",
)
def settings_hooks(enable: bool | None, gate: str | None) -> None:
    """Configure post-task review hooks.

    Examples:

        muscle settings hooks --enable

        muscle settings hooks --gate warn
    """
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path, _ = _resolve_project_context(Path.cwd())

    updated = False
    if enable is not None:
        manager.update_muscle_config(project_path, hooks_enabled=enable)
        console.print(f"[green]Hooks {'enabled' if enable else 'disabled'}[/green]")
        updated = True

    if gate:
        manager.update_muscle_config(project_path, review_gate=gate)
        console.print(f"[green]Review gate set to: {gate}[/green]")
        updated = True

    if not updated:
        console.print("No changes made. Use --enable/--disable or --gate to make changes.")
        return

    _refresh_active_review_safe(project_path, reason="settings-hooks")


@settings_group.command(name="review")
@click.option(
    "--execution",
    type=click.Choice(["local", "worktree"]),
    help="Review execution mode",
)
def settings_review(execution: str | None) -> None:
    """Configure review execution settings."""
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path, project = _resolve_project_context(Path.cwd())

    if execution:
        if not manager.update_muscle_config(project_path, review_execution=execution):
            console.print("[red]Failed to update review execution mode.[/red]")
            return
        console.print(f"[green]Review execution set to: {execution}[/green]")
        _refresh_active_review_safe(project_path, reason="settings-review")
        return

    current = project.review_execution if project is not None else "local"
    console.print(f"Current review execution: {current}")
    console.print("Use --execution local|worktree to change it.")


@settings_group.command(name="platform")
@click.option(
    "--platform",
    type=click.Choice(["opencode", "claude-code", "codex", "auto"]),
    help="Target platform",
)
@click.option("--cli-path", help="Path to muscle CLI")
def settings_platform(platform: str | None, cli_path: str | None) -> None:
    """Configure platform and CLI settings.

    Examples:

        muscle settings platform --platform opencode

        muscle settings platform --cli-path /usr/local/bin/muscle
    """
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path, _ = _resolve_project_context(Path.cwd())

    updated = False
    if platform:
        manager.update_muscle_config(project_path, platform=platform)
        console.print(f"[green]Platform set to: {platform}[/green]")
        updated = True

    if cli_path:
        manager.update_muscle_config(project_path, cli_path=cli_path)
        console.print(f"[green]CLI path set to: {cli_path}[/green]")
        updated = True

    if not updated:
        current_platform = manager.detect_platform()
        detected_cli = manager.detect_cli_location()
        console.print(f"Current platform: {current_platform}")
        console.print(f"Detected CLI: {detected_cli or 'Not found'}")
        console.print()
        console.print("Use --platform or --cli-path to configure.")
        return

    _refresh_active_review_safe(project_path, reason="settings-platform")


@settings_group.command(name="model")
@click.option("--canonical-model", default=None, help="Canonical model key override")
@click.option("--clear", is_flag=True, help="Clear the manual model override")
@click.option(
    "--pack-mode",
    type=click.Choice(["off", "suggest", "auto"]),
    default=None,
    help="Project-level model-pack mode",
)
@click.option(
    "--related-mode",
    type=click.Choice(["off", "suggest"]),
    default=None,
    help="Project-level related-project suggestion mode",
)
def settings_model(
    canonical_model: str | None,
    clear: bool,
    pack_mode: str | None,
    related_mode: str | None,
) -> None:
    """Configure model identity and overlay settings for the current project."""
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path, project = _resolve_project_context(Path.cwd())

    updates: dict[str, Any] = {}
    if clear:
        updates["model_manual_override"] = ""
        updates["canonical_model_key"] = ""
        updates["model_identity_source"] = "unresolved"
    elif canonical_model:
        updates["model_manual_override"] = canonical_model
        updates["canonical_model_key"] = canonical_model
        updates["model_identity_source"] = "manual_override"

    if pack_mode:
        updates["model_pack_mode"] = pack_mode
    if related_mode:
        updates["related_project_mode"] = related_mode

    if not updates:
        current = _resolve_model_identity(str(project_path), project)
        console.print(
            f"Current canonical model: {current.get('canonical_model_key') or 'Unresolved'}"
        )
        console.print(
            f"Pack mode: {getattr(project, 'model_pack_mode', 'suggest') if project else 'suggest'}"
        )
        console.print(
            f"Related-project mode: {getattr(project, 'related_project_mode', 'suggest') if project else 'suggest'}"
        )
        return

    manager.update_muscle_config(project_path, **updates)
    console.print("[green]Model settings updated.[/green]")
    _refresh_active_review_safe(project_path, reason="settings-model")


@settings_group.command(name="reset")
@click.option("--force", is_flag=True, help="Skip confirmation prompts")
@click.option("--keep-data", is_flag=True, help="Keep .muscle/ project data")
@click.option("--keep-config", is_flag=True, help="Keep ~/.muscle/ global config")
def settings_reset(force: bool, keep_data: bool, keep_config: bool) -> None:
    """Reset MUSCLE settings to defaults.

    This will reset platform, hooks, and automation settings but
    will NOT remove the knowledge base or memory files.
    """
    from .tui.project_manager import ProjectManager

    if not force:
        if not click.confirm("Reset all MUSCLE settings to defaults?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    manager = ProjectManager()
    project_path, _ = _resolve_project_context(Path.cwd())

    manager.update_muscle_config(
        project_path,
        hooks_enabled=True,
        review_gate="block+fix",
        review_execution="local",
        platform="auto",
        api_key_source="env",
        related_project_mode="suggest",
        model_pack_mode="suggest",
        canonical_model_key="",
        model_identity_source="unresolved",
        model_manual_override="",
    )
    _refresh_active_review_safe(project_path, reason="settings-reset")
    console.print("[green]Settings reset to defaults.[/green]")


@cli.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompts")
@click.option("--keep-data", is_flag=True, help="Keep .muscle/ project data")
@click.option("--keep-config", is_flag=True, help="Keep ~/.muscle/ global config")
def uninstall(force: bool, keep_data: bool, keep_config: bool) -> None:
    """Uninstall MUSCLE from the current project.

    Removes .muscle/ directory, OpenCode integration files, and optionally
    the global config. Does NOT uninstall the CLI binary itself (use pip/uv for that).

    Examples:

        muscle uninstall
        muscle uninstall --force --keep-data
    """
    import shutil

    project_path = Path.cwd()
    muscle_dir = project_path / ".muscle"
    opencode_dir = project_path / ".opencode"

    if not muscle_dir.exists() and not opencode_dir.exists():
        console.print("[yellow]No MUSCLE installation found in current directory.[/yellow]")
        return

    if not force:
        console.print("[bold red]This will remove MUSCLE from this project.[/bold red]")
        console.print()
        if muscle_dir.exists():
            console.print(f"  [red]Delete[/red] {muscle_dir}/")
        if opencode_dir.exists():
            console.print(f"  [red]Delete[/red] {opencode_dir}/")
        console.print()
        if not click.confirm("Proceed with uninstall?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    # Remove project .muscle/ directory
    if not keep_data and muscle_dir.exists():
        try:
            shutil.rmtree(muscle_dir)
            console.print(f"[green]Removed[/green] {muscle_dir}/")
        except OSError as e:
            console.print(f"[red]Failed to remove {muscle_dir}: {e}[/red]")
    elif keep_data and muscle_dir.exists():
        console.print(f"[dim]Kept {muscle_dir}/ (--keep-data)[/dim]")

    # Remove .opencode/ directory
    if opencode_dir.exists():
        try:
            shutil.rmtree(opencode_dir)
            console.print(f"[green]Removed[/green] {opencode_dir}/")
        except OSError as e:
            console.print(f"[red]Failed to remove {opencode_dir}: {e}[/red]")

    # Remove OpenCode skill
    skill_dir = Path.home() / ".claude" / "skills" / "muscle-review"
    if skill_dir.exists():
        try:
            shutil.rmtree(skill_dir)
            console.print("[green]Removed[/green] OpenCode skill (~/.claude/skills/muscle-review/)")
        except OSError as e:
            console.print(f"[red]Failed to remove skill: {e}[/red]")

    # Remove global config
    if not keep_config:
        global_dir = Path.home() / ".muscle"
        if global_dir.exists():
            if not force:
                if not click.confirm("Also remove global config (~/.muscle/)?"):
                    console.print("[dim]Kept ~/.muscle/[/dim]")
                    global_dir = None  # type: ignore[assignment]

            if global_dir and global_dir.exists():
                try:
                    shutil.rmtree(global_dir)
                    console.print("[green]Removed[/green] ~/.muscle/")
                except OSError as e:
                    console.print(f"[red]Failed to remove ~/.muscle/: {e}[/red]")

    console.print()
    console.print("[bold green]MUSCLE uninstalled from this project.[/bold green]")
    console.print()
    console.print(
        "[dim]To fully remove the CLI: pip uninstall muscle  (or: uv pip uninstall muscle)[/dim]"
    )


@cli.group(name="cache")
def cache_group() -> None:
    """Manage MUSCLE response cache."""
    pass


@cache_group.command(name="clear")
@click.option(
    "--older-than", default=None, help="Only clear entries older than this (e.g. '7d', '30d')"
)
def cache_clear_cmd(older_than: str | None) -> None:
    """Clear cached M2.7 responses."""
    from .response_cache import ResponseCache

    cache = ResponseCache()
    td = _parse_since(older_than) if older_than else None
    count = cache.clear(older_than=td)
    click.echo(f"Cleared {count} cached entries")


@cli.group(name="pack", invoke_without_command=True)
@click.option("--task", default=None, help="Task description (required when building).")
@click.option(
    "--scope",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Scope file or directory to include in the pack.",
)
@click.option("--acceptance", default="", help="Acceptance criteria from host planner.")
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional path to copy the rendered pack markdown to.",
)
@click.pass_context
def pack_group(
    ctx: click.Context,
    task: str | None,
    scope: Path | None,
    acceptance: str,
    out: Path | None,
) -> None:
    """Build a content-addressed context pack for reuse across MUSCLE subtasks."""
    if ctx.invoked_subcommand is not None:
        return
    if not task or scope is None:
        click.echo("Error: --task and --scope are required to build a pack.", err=True)
        click.echo(
            "Run `muscle pack list` or `muscle pack gc --older-than <dur>` otherwise.", err=True
        )
        ctx.exit(2)
        return  # pragma: no cover - ctx.exit raises

    from .packs import PackBuilder

    budgeter = _build_context_budgeter({})
    builder = PackBuilder(Path.cwd(), budgeter)
    pack = builder.build(task=task, scope=scope, acceptance=acceptance)
    click.echo(f"Pack id: {pack.id}")
    click.echo(f"Pack path: {pack.path}")
    click.echo(f"Content sha: {pack.content_sha}")
    if out is not None:
        Path(out).write_text(pack.path.read_text(encoding="utf-8"), encoding="utf-8")
        click.echo(f"Copied to: {out}")


@pack_group.command(name="list")
def pack_list_cmd() -> None:
    """List packs stored under ``.muscle/packs/``."""
    from .packs import PackStore

    store = PackStore(Path.cwd())
    packs = store.list()
    if not packs:
        click.echo("No packs found.")
        return

    table = Table(title="Context Packs")
    table.add_column("ID", style="cyan")
    table.add_column("Task", style="green")
    table.add_column("Created", style="dim")
    table.add_column("Path", style="magenta")
    for p in packs:
        task_preview = (p.task[:60] + "...") if len(p.task) > 60 else p.task
        table.add_row(p.id, task_preview, p.created_at.isoformat(), str(p.path))
    console.print(table)


@pack_group.command(name="gc")
@click.option(
    "--older-than",
    required=True,
    help="Remove packs older than this (e.g. '7d', '30d', '1h').",
)
def pack_gc_cmd(older_than: str) -> None:
    """Remove packs older than the given duration."""
    from .packs import PackStore

    store = PackStore(Path.cwd())
    td = _parse_since(older_than)
    removed = store.gc(older_than=td)
    click.echo(f"Removed {removed} pack(s) older than {older_than}.")


@cli.command(name="route")
@click.option("--task", required=True, help="Task description to classify.")
@click.option("--scope", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def route_cmd(task: str, scope: Path | None, as_json: bool) -> None:
    """Classify a task and decide where it should run (M2.7 vs host)."""
    from .routing import TaskRouter

    client = M27Client(api_key=os.environ.get("MINIMAX_API_KEY", ""))
    router = TaskRouter(client)
    decision = router.route(task, scope=scope)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "tier": decision.tier.value,
                    "recommended": decision.recommended.value,
                    "confidence": decision.confidence,
                    "rationale": decision.rationale,
                    "from_cache": decision.from_cache,
                }
            )
        )
    else:
        click.echo(f"Tier:        {decision.tier.value}")
        click.echo(f"Recommended: {decision.recommended.value}")
        click.echo(f"Confidence:  {decision.confidence:.2f}")
        click.echo(f"Rationale:   {decision.rationale}")


@cli.group(name="escalation")
def escalation_group() -> None:
    """Manage MUSCLE escalation records."""
    pass


@escalation_group.command(name="list")
def escalation_list_cmd() -> None:
    """List unresolved escalation records."""
    from .escalation import EscalationRecorder

    unresolved = EscalationRecorder.list_unresolved(Path.cwd())
    if not unresolved:
        click.echo("No unresolved escalations.")
        return

    table = Table(title="Unresolved Escalations")
    table.add_column("ID", style="cyan")
    table.add_column("Session", style="green")
    table.add_column("Reason", style="yellow")
    table.add_column("Source", style="magenta")
    table.add_column("Attempts", justify="right")
    table.add_column("Created", style="dim")

    for row in unresolved:
        table.add_row(
            str(row["id"]),
            row["session_id"],
            row["reason"],
            row["source_module"],
            str(row["attempt_count"]),
            row["created_at"],
        )
    console.print(table)


@escalation_group.command(name="resolve")
@click.argument("escalation_id", type=int)
def escalation_resolve_cmd(escalation_id: int) -> None:
    """Mark an escalation as resolved."""
    from .escalation import EscalationRecorder

    resolved = EscalationRecorder.resolve(Path.cwd(), escalation_id)
    if resolved:
        click.echo(f"Escalation {escalation_id} resolved.")
    else:
        click.echo(f"Escalation {escalation_id} not found.", err=True)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
