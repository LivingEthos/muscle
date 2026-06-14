"""Lifecycle commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.lifecycle.<name>``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.table import Table

from ..active_review import (
    load_active_review_snapshot,
)
from ..doctor import build_doctor_report, doctor_report_to_dict
from ..host_runtime import run_host_hook
from ..model_identity import SUPPORTED_CANONICAL_MODELS, ModelIdentityResolver
from ..project_memory import ProjectMemory
from ..system_db import SystemDatabase
from ..visual_devflow import enable_visual_devflow
from ._shared import (
    _emit_json,
    _format_snapshot_age,
    _provider_endpoint,
    _refresh_active_review_safe,
    _refresh_project_state_safe,
    _render_discovery_report,
    _render_doctor_report,
    _render_foresight_report,
    _render_savings_report,
    _requested_model_label,
    _resolve_project_context,
    _suggest_related_projects,
    cli,
    console,
    logger,
)


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
@click.option("--api-key", help="MiniMax API key (or set MINIMAX_API_KEY env var)")
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
    from ..tui.project_manager import ProjectConfig, ProjectManager

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
@click.option(
    "--cache-layout",
    is_flag=True,
    help="Print cache-prefix layout metadata for host-memory docs.",
)
def optimize_host_docs(
    dry_run: bool,
    yes: bool,
    only: str | None,
    skip_agents: bool,
    target: str | None,
    agents: bool,
    cache_layout: bool,
) -> None:
    """Non-destructively optimize root CLAUDE.md / AGENTS.md into the MUSCLE-preferred format."""
    from ..code_review.host_memory_optimizer import run_optimizer

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
        if cache_layout:
            _print_host_doc_cache_layout(project_root, only, effective_skip_agents)
        sys.exit(1 if any_changed else 0)

    if any_changed and not yes:
        if not click.confirm("Apply these changes?", default=False):
            click.echo("Aborted.")
            sys.exit(1)
    click.echo("Done." if any_changed else "No changes needed.")


def _print_host_doc_cache_layout(
    project_root: Path,
    only: str | None,
    skip_agents: bool,
) -> None:
    """Print cache-prefix metadata for existing host docs."""
    from ..optimization.prompt_prefix import PromptPrefixPlanner

    filenames = [only] if only else ["CLAUDE.md", *([] if skip_agents else ["AGENTS.md"])]
    planner = PromptPrefixPlanner()
    for filename in filenames:
        if filename is None:
            continue
        path = project_root / filename
        if not path.exists():
            click.echo(f"\n=== {filename} cache layout ===")
            click.echo("missing")
            continue
        plan = planner.plan_rendered_prompt(path.read_text(encoding="utf-8"))
        metadata = plan.to_metadata()
        click.echo(f"\n=== {filename} cache layout ===")
        click.echo(f"cache_prefix_chars: {metadata['cache_prefix_chars']}")
        click.echo(f"cache_prefix_digest: {metadata['cache_prefix_digest']}")
        click.echo(
            f"cache_prefix_lint_warning_count: {metadata['cache_prefix_lint_warning_count']}"
        )
        click.echo(f"estimated_cache_fresh_cost: {metadata['estimated_cache_fresh_cost']}")
        click.echo(f"estimated_cache_read_cost: {metadata['estimated_cache_read_cost']}")


@cli.command()
def enable() -> None:
    """Enable MUSCLE for the current project.

    Stores project-local enablement in the project database.
    Use after 'muscle init' if MUSCLE was previously disabled.

    Examples:

        muscle enable
    """
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
    from ..project_memory import ProjectMemory
    from ..tui.project_manager import ProjectManager

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
        from ..escalation import EscalationRecorder

        unresolved = EscalationRecorder.list_unresolved(project_path)
        if unresolved:
            table.add_row("Unresolved Escalations", str(len(unresolved)))
    except Exception:
        pass

    console.print(table)


@cli.command(name="visualize")
@click.option(
    "--project",
    "-p",
    default=None,
    help="Project path to visualize (defaults to the current MUSCLE project)",
)
@click.option("--open/--no-open", "open_dashboard", default=True, help="Open the dashboard")
@click.option(
    "--command",
    "visual_command",
    default=None,
    help="Path to the visual-devflow control command",
)
@click.option("--json", "json_output", is_flag=True, help="Emit structured command status")
def visualize(
    project: str | None,
    open_dashboard: bool,
    visual_command: str | None,
    json_output: bool,
) -> None:
    """Enable the Visual DevFlow dashboard for this MUSCLE project."""

    start_path = Path(project).resolve() if project else Path.cwd()
    project_path, _ = _resolve_project_context(start_path)
    result = enable_visual_devflow(
        project_path,
        open_dashboard=open_dashboard,
        command=visual_command,
    )
    if json_output:
        _emit_json(result)
        return

    if result.get("ok"):
        url = result.get("url")
        console.print("[green]Visual DevFlow enabled[/green]")
        if url:
            console.print(f"Dashboard: {url}")
        console.print(
            "[dim]MUSCLE run/review events will appear automatically while this dashboard is enabled.[/dim]"
        )
        return

    console.print(f"[red]Visual DevFlow unavailable:[/red] {result.get('message', 'failed')}")
    if result.get("stderr"):
        console.print(f"[dim]{result['stderr']}[/dim]")


@cli.command(name="foresight")
@click.option(
    "--task",
    "-t",
    required=True,
    help="Task or change to preflight",
)
@click.option(
    "--project",
    "-p",
    default=None,
    help="Project path (defaults to the current MUSCLE project)",
)
@click.option(
    "--target",
    default=None,
    help="Optional file or directory target for the preflight",
)
@click.option(
    "--write/--no-write",
    default=True,
    help="Persist `.muscle/MUSCLE_SHORT_TERM.md` when project state exists",
)
@click.option("--json", "json_output", is_flag=True, help="Emit structured foresight output")
def foresight(
    task: str,
    project: str | None,
    target: str | None,
    write: bool,
    json_output: bool,
) -> None:
    """Generate a bounded, opt-in project-local foresight preflight."""

    if not task.strip():
        raise click.UsageError("--task cannot be empty")

    from ..foresight import build_foresight_report

    if project:
        project_path = Path(project).resolve()
    else:
        project_path, _ = _resolve_project_context(Path.cwd())
    if target:
        target_input = Path(target)
        target_path = (
            target_input.resolve()
            if target_input.is_absolute()
            else (project_path / target_input).resolve()
        )
    else:
        target_path = project_path
    report = build_foresight_report(
        project_path,
        task,
        target_path=target_path,
        write=write,
    )
    if json_output:
        _emit_json(report)
        return
    _render_foresight_report(report)


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
        _emit_json(doctor_report_to_dict(report))
        return
    _render_doctor_report(report)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Emit structured savings output")
def savings(json_output: bool) -> None:
    """Summarize token, cache, and command-output savings evidence."""

    from ..savings import build_savings_report

    project_path, _ = _resolve_project_context(Path.cwd())
    report = build_savings_report(project_path)
    if json_output:
        _emit_json(report)
        return
    _render_savings_report(report)


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Emit structured discovery output")
@click.option("--since", "since_days", type=int, default=30, show_default=True)
def discover(json_output: bool, since_days: int) -> None:
    """Report missed MUSCLE opportunities without writing memory files."""

    from ..discovery import build_discovery_report

    project_path, _ = _resolve_project_context(Path.cwd())
    report = build_discovery_report(project_path, since_days=max(1, since_days))
    if json_output:
        _emit_json(report)
        return
    _render_discovery_report(report)


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

    from ..tui.project_manager import ProjectManager
    from ..tui.views import TUI

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


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str) -> None:
    """Print a shell-completion activation snippet for SHELL.

    Add the printed line to your shell startup file, e.g.::

        muscle completion zsh >> ~/.zshrc
    """
    if shell == "fish":
        click.echo("eval (env _MUSCLE_COMPLETE=fish_source muscle)")
    else:
        click.echo(f'eval "$(_MUSCLE_COMPLETE={shell}_source muscle)"')
