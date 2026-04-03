"""
CLI - Command-line interface for MUSCLE.

Provides commands for running, resuming, and managing self-improvement loops.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

try:
    import orjson

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

from .backup_manager import BackupManager
from .budget_manager import BudgetManager
from .code_generator import CodeGenerator
from .code_review.learning_pipeline import LearningPipeline
from .cost_optimizer import CostOptimizer
from .evolver import Evolver
from .interactive import InteractiveHandler
from .learning_ingestor import LearningIngestor
from .loop_controller import LoopController, LoopEvent
from .m27_client import M27Client
from .project_builder import ProjectBuilder
from .project_memory import ProjectMemory
from .project_memory_types import TaskStatus
from .self_improver import SelfImprover
from .session_manager import SessionManager
from .strategy_kb import GlobalKnowledgeBase
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


def _create_m27_client() -> M27Client:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    return M27Client(api_key=api_key)


_streaming_text: list[str] = []


def _event_handler(event: LoopEvent, data: dict) -> None:
    global _streaming_text
    if event == LoopEvent.ITERATION_START:
        _streaming_text = []
        console.print(f"\n[cyan]Iteration {data['iteration']}[/cyan]")
    elif event == LoopEvent.GENERATION_STREAM:
        chunk = data.get("chunk", "")
        if chunk:
            _streaming_text.append(chunk)
    elif event == LoopEvent.GENERATION_END:
        _streaming_text = []
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


@click.group()
@click.version_option(version="0.1.0")
def cli() -> None:
    """MUSCLE - MiniMax Unified Self-Correcting Learning Engine

    Autonomous code generation and improvement using MiniMax M2.7.
    """
    pass


@cli.command()
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
@click.option(
    "--platform",
    type=click.Choice(["auto", "opencode", "claude-code"]),
    default="auto",
    help="Target platform",
)
@click.option("--api-key", help="MINIMAX/M2.7 API key (or set MINIMAX_API_KEY env var)")
@click.option("--hooks/--no-hooks", default=True, help="Enable/disable post-task review hooks")
@click.option("--cli-path", help="Path to muscle CLI (auto-detected if not specified)")
def init(
    non_interactive: bool,
    platform: str,
    api_key: str | None,
    hooks: bool,
    cli_path: str | None,
) -> None:
    """Initialize MUSCLE for the current project.

    Creates .muscle/ directory with configuration, knowledge base,
    and memory files. Run this once per project.

    For OpenCode integration, run with --platform opencode.
    For Claude Code integration, run with --platform claude-code.
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
        project.triggers = ["review-gate", "manual"]
        project.github_enabled = False
        project.memory_location = ".muscle"
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
                console.print("  muscle_init, muscle_nightly, muscle_improve, muscle_cost_*")
                console.print("  muscle_tui, muscle_run, muscle_abort")
                console.print()
                console.print("[dim]MUSCLE automatically calls muscle_review on session idle[/dim]")
            else:
                console.print("[yellow]⚠[/yellow] OpenCode setup skipped (may already exist)")

        # Store project enablement state in project_memory.db
        manager.set_project_enabled(project.path, True)
        console.print("[green]✓[/green] Project enabled in database")

        console.print()
        console.print("[bold green]MUSCLE initialized successfully![/bold green]")
        console.print()
        console.print("Run 'muscle tui' to start the TUI")
        console.print("Run 'muscle review --target ./src' to run a review")
        console.print("Run 'muscle status' to check project status")
        if effective_platform in ("opencode", "auto"):
            console.print()
            console.print("[dim]For OpenCode, use the muscle_* tools directly[/dim]")
    else:
        console.print("[red]Failed to initialize project[/red]")


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
        console.print("[green]MUSCLE disabled for this project.[/green]")
    else:
        console.print("[red]Failed to disable MUSCLE.[/red]")


@cli.command()
def status() -> None:
    """Show MUSCLE status for the current project.

    Displays whether MUSCLE is enabled/disabled, project info,
    database path, and review counts.

    Examples:

        muscle status
    """
    from .project_memory import ProjectMemory
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path = Path.cwd()
    project = manager.get_current_project()

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
    else:
        table.add_row("Project", project_path.name)

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
        table.add_row("Learned Rules", str(stats.get("total_learned_rules", 0)))
        table.add_row("Skills", str(stats.get("total_skills", 0)))
    except Exception:
        table.add_row("Reviews", "N/A")

    console.print(table)


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

    if max_iterations < 1 or max_iterations > 100:
        console.print(
            f"[red]Error: max_iterations must be between 1 and 100, got {max_iterations}[/red]"
        )
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

    if not m27_client.api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    code_gen = CodeGenerator(m27_client)
    evolver = Evolver(m27_client, use_kb=kb, kb_path=kb_path)

    def evaluator(output_dir: str) -> Any:
        from .evaluator_registry import EvaluatorRegistry

        registry = EvaluatorRegistry()
        return registry.evaluate(output_dir, config.language, config.eval_mode)

    def code_gen_wrapper(
        task: str, strategy: str | None, output_dir: str | None
    ) -> tuple[str, Any]:
        return code_gen.generate(task, strategy or "", output_dir or ".")

    git_enabled = git if git is not None else interactive
    git_repo_path = git_repo if git_enabled else None

    from .session_manager import SessionManager

    session_manager = SessionManager()

    webhook_notifier = WebhookNotifier(webhook_url or os.environ.get("MUSCLE_WEBHOOK_URL"))

    interactive_handler = InteractiveHandler(enabled=interactive)

    controller = LoopController(
        config=config,
        code_generator=code_gen_wrapper,
        evaluator=evaluator,
        evolver=evolver.evolve,
        budget_manager=budget_manager.check_budget,
        event_callback=_event_handler,
        webhook_notifier=webhook_notifier,
        git_repo_path=git_repo_path,
        git_auto_push=git_push if git_enabled else False,
        interactive=interactive_handler,
        session_manager=session_manager,
    )

    try:
        streaming_display = Text("")
        live = None

        def streaming_callback(chunk: str) -> None:
            nonlocal streaming_display, live
            full_text = "".join(_streaming_text) + chunk
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
            project_path = str(Path.cwd())
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

    code_gen = CodeGenerator(m27_client)
    evolver = Evolver(m27_client, use_kb=True, kb_path=resume_ctx.config.kb_path)
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
        task: str, strategy: str | None, output_dir: str | None
    ) -> tuple[str, Any]:
        return code_gen.generate(task, strategy or "", output_dir or ".")

    controller = LoopController(
        config=resume_ctx.config,
        code_generator=code_gen_wrapper,
        evaluator=evaluator,
        evolver=evolver.evolve,
        budget_manager=budget_manager.check_budget,
        event_callback=_event_handler,
        interactive=InteractiveHandler(enabled=resume_ctx.config.interactive),
        session_manager=session_manager,
    )

    try:
        streaming_display = Text("")
        live = None

        def streaming_callback(chunk: str) -> None:
            nonlocal streaming_display, live
            full_text = "".join(_streaming_text) + chunk
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

        muscle check --target ./src --language python --format json

        muscle check --target ./tests --format text
    """
    from .evaluator_registry import EvaluatorRegistry

    target_path = Path(target)
    if not target_path.exists():
        console.print(f"[red]Error: Target does not exist: {target}[/red]")
        sys.exit(1)

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
        return orjson.dumps(data, option=orjson.OPT_INDENT_2).decode()
    return json.dumps(data, indent=2)


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


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

    if shadow:
        from .code_review.shadow_worker import WorkerManager

        worker_manager = WorkerManager(project_path=str(Path.cwd()))
        job_id = worker_manager.submit_shadow_job(
            target_path=target,
            mode=mode_map.get(mode, ReviewMode.REVIEW),
            intensity=intensity_map.get(intensity, Intensity.MODERATE),
        )
        console.print(f"[cyan]Shadow job created: {job_id}[/cyan]")
        console.print("Check status with: muscle probe")
        console.print("Get results with: muscle diagnosis")
        console.print("[dim]Worker started in background...[/dim]")
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

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    from .m27_client import M27Client

    m27_client = M27Client(api_key=api_key)

    config = ReviewConfig(
        target_path=target,
        language=language,
        mode=mode_map.get(mode, ReviewMode.REVIEW),
        severity_threshold=severity_map.get(severity, Severity.LOW),
        max_fixes_per_round=max_fixes,
    )

    # Project path resolved before controller creation for callback closure
    project_path = str(Path(target).resolve().parent) if Path(target).is_file() else target

    # Initialize ProjectMemory and LearningIngestor early for correction signal callback
    try:
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
        event_callback=event_handler,
        correction_signal_callback=on_correction_signal,
    )

    try:
        result = controller.run()
        review_result = controller.get_review_result()

        # Self-learning: update CLAUDE.md, MEMORY.md, and skills
        if review_result:
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
                if learn_result.get("rules_added"):
                    console.print(f"[cyan]Learned {learn_result['rules_added']} new rules[/cyan]")
                if learn_result.get("skills_generated"):
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

        if format == "json" and review_result:
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
            }
            console.print(json.dumps(output_data, indent=2))
        else:
            if review_result:
                console.print("\n[bold]Review Summary[/bold]")
                console.print(f"Target: {review_result.target_path}")
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

        if output and result.handoff_plan:
            Path(output).write_text(result.handoff_plan.markdown, encoding="utf-8")
            console.print(f"\n[green]Handoff plan written to {output}[/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Review interrupted by user[/yellow]")
        sys.exit(130)


@cli.command(name="lifeline")
@click.option("--target", "-t", required=True, help="Target directory or file to investigate")
@click.option("--prompt", "-p", required=True, help="Task or question to investigate")
@click.option("--model", "-m", default=None, help="Model to use (optional)")
@click.option(
    "--intensity",
    "-i",
    type=click.Choice(["minimal", "moderate", "intensive", "exhaustive"]),
    default="moderate",
    help="Investigation intensity",
)
def lifeline(target: str, prompt: str, model: str | None, intensity: str) -> None:
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

    try:
        console.print("[cyan]Throwing lifeline to M2.7...[/cyan]")
        console.print(f"[dim]Target: {target}[/dim]")
        console.print(f"[dim]Intensity: {intensity}[/dim]")

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
        recent = broker.get_recent_jobs(limit=1)
        if not recent:
            console.print("[yellow]No completed jobs found[/yellow]")
            sys.exit(1)
        job = recent[0]
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

    if "issues" in result:
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

    elif "pressure_findings" in result:
        findings = result.get("pressure_findings", [])
        console.print(f"Pressure findings: {len(findings)}")
        for finding in findings[:10]:
            sev = finding.get("severity", "MEDIUM")
            color = "red" if sev in ("CRITICAL", "HIGH") else "yellow"
            console.print(f"  [{color}]{sev}[/] {finding.get('title', 'Unknown')}")

    else:
        console.print(result)


@cli.group(name="nightly")
def nightly_group() -> None:
    """Nightly cron and report management."""
    pass


@nightly_group.command(name="enable")
@click.option("--time", "-t", default="03:00", help="Run time in HH:MM format (default: 03:00)")
@click.option("--target", default=None, help="Target path to review (default: current directory)")
def nightly_enable(time: str, target: str | None) -> None:
    """Enable nightly review at a scheduled time.

    Examples:

        muscle nightly enable                  # Enable at 03:00 AM

        muscle nightly enable --time 02:30      # Enable at 02:30 AM

        muscle nightly enable --target ./src    # Review ./src directory
    """
    from .code_review.nightly_runner import NightlyConfig, NightlyRunner, ScheduleManager

    project_path = target or str(Path.cwd())
    schedule_mgr = ScheduleManager(project_path)
    schedule_mgr.enable_nightly(run_time=time)
    console.print(f"[green]Nightly review enabled at {time}[/green]")
    console.print(f"Project: {project_path}")

    runner = NightlyRunner(project_path, NightlyConfig(enabled=True, run_time=time))
    report = runner.run_nightly()
    if report:
        console.print(
            f"[cyan]Immediate run completed: {report.get('total_issues', 0)} issues found[/cyan]"
        )
    else:
        console.print("[yellow]Nightly scheduled but no report generated yet.[/yellow]")


@nightly_group.command(name="disable")
def nightly_disable() -> None:
    """Disable nightly review schedule."""
    from .code_review.nightly_runner import ScheduleManager

    schedule_mgr = ScheduleManager(str(Path.cwd()))
    schedule_mgr.disable_nightly()
    console.print("[green]Nightly review disabled.[/green]")


@nightly_group.command(name="status")
def nightly_status() -> None:
    """Show nightly schedule status."""
    from .code_review.nightly_runner import ScheduleManager

    schedule_mgr = ScheduleManager(str(Path.cwd()))
    schedule = schedule_mgr.get_schedule()

    table = Table(title="Nightly Schedule Status")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    nightly = schedule.get("nightly", {})
    enabled = nightly.get("enabled", False)
    table.add_row("Enabled", f"[{'green' if enabled else 'red'}]" + ("Yes" if enabled else "No"))
    table.add_row("Run Time", nightly.get("run_time", "Not set"))
    table.add_row("Next Run", nightly.get("next_run", "Not scheduled"))

    console.print(table)


@nightly_group.command(name="run")
@click.option("--target", "-t", default=None, help="Target path to review")
def nightly_run(target: str | None) -> None:
    """Run nightly review immediately (one-shot)."""
    from .code_review.nightly_runner import NightlyConfig, NightlyRunner

    project_path = target or str(Path.cwd())
    runner = NightlyRunner(project_path, NightlyConfig(enabled=True))
    console.print(f"[cyan]Running nightly review on {project_path}...[/cyan]")

    result = runner.run_nightly()
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


@nightly_group.command(name="reports")
@click.option("--limit", "-n", default=7, help="Number of reports to show")
def nightly_reports(limit: int) -> None:
    """List recent nightly reports."""
    from .code_review.nightly_runner import NightlyRunner

    runner = NightlyRunner(str(Path.cwd()))
    reports = runner.list_reports(limit=limit)

    if not reports:
        console.print("[yellow]No nightly reports found.[/yellow]")
        console.print("Run 'muscle nightly run' to generate the first report.")
        return

    table = Table(title=f"Recent Nightly Reports (last {len(reports)})")
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


@nightly_group.command(name="cleanup")
@click.option("--days", "-d", default=30, help="Keep reports for N days")
@click.option("--force", is_flag=True, help="Skip confirmation")
def nightly_cleanup(days: int, force: bool) -> None:
    """Clean up old nightly reports."""
    from .code_review.nightly_runner import NightlyRunner

    runner = NightlyRunner(str(Path.cwd()))
    if not force:
        if not click.confirm(f"Remove reports older than {days} days?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    removed = runner.cleanup_old_reports(days_to_keep=days)
    console.print(f"[green]Removed {removed} old reports.[/green]")


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
    project_path = str(Path.cwd())
    try:
        pm = ProjectMemory(project_path)
        stats = pm.get_statistics(project_path)

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
        avg_rate = stats.get("avg_rule_success_rate")
        avg_rate_str = f"{avg_rate:.1%}" if avg_rate is not None else "N/A"
        table.add_row("Avg Rule Success Rate", avg_rate_str)

        console.print(table)
    except Exception as e:
        console.print(f"[red]Failed to get memory status: {e}[/red]")


@memory_group.command(name="history")
@click.option("--limit", "-n", default=10, help="Number of entries to show")
def memory_history(limit: int) -> None:
    """Show recent review sessions and memory decisions."""
    project_path = str(Path.cwd())
    try:
        pm = ProjectMemory(project_path)

        runs = pm.list_review_runs(project_path=project_path, limit=limit)
        decisions = pm.list_decisions(project_path=project_path, limit=limit)

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
                reasoning = _truncate(d.get("reasoning", ""), 50)
                dec_table.add_row(
                    str(d["id"]),
                    d.get("decision_type", "unknown"),
                    d.get("source_table", ""),
                    reasoning,
                )
            console.print(dec_table)
    except Exception as e:
        console.print(f"[red]Failed to get memory history: {e}[/red]")


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
            return

        if "error" in result:
            console.print(f"[red]Restore failed: {result['error']}[/red]")
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
        ]
    ),
    default=None,
    help="Filter by action type",
)
def audit_list(limit: int, action: str | None) -> None:
    """Show recent audit log entries (publish, backup, restore, skill/agent lifecycle)."""
    project_path = str(Path.cwd())
    try:
        pm = ProjectMemory(project_path)
        entries = pm.list_action_logs(
            project_path=project_path,
            action_type=action,
            limit=limit,
        )

        table = Table(title=f"Recent Actions (last {len(entries)})")
        table.add_column("When", style="dim", width=16)
        table.add_column("Action", style="cyan", width=14)
        table.add_column("Entity", style="yellow", width=14)
        table.add_column("Details", style="white")

        if not entries:
            console.print("[dim]No audit entries yet.[/dim]")
            return

        for entry in entries:
            details = entry.get("details_json", "{}")
            # Parse details for display
            try:
                import json

                details_obj = json.loads(details)
                if entry.get("entity_type") == "backup":
                    details_str = details_obj.get("backup_type", "")
                    if entry.get("action_type") == "restore":
                        details_str += f", restored={details_obj.get('restored_count', '?')} files"
                elif entry.get("entity_type") == "skill":
                    details_str = (
                        details_obj.get("skill_name", "")
                        or details_obj.get("trigger_pattern", "")
                        or details_obj.get("skill_path", "")
                    )
                elif entry.get("entity_type") == "agent":
                    details_str = details_obj.get("agent_name", "") or details_obj.get(
                        "trigger_pattern", ""
                    )
                elif entry.get("entity_type") == "claude_md":
                    details_str = "CLAUDE.md published"
                else:
                    details_str = str(details_obj)
            except Exception:
                details_str = details[:50]

            entity_id_str = (
                f"{entry.get('entity_type', '')}:{entry.get('entity_id', '')}"
                if entry.get("entity_id")
                else entry.get("entity_type", "")
            )
            table.add_row(
                entry.get("created_at", "")[:16],
                entry.get("action_type", ""),
                entity_id_str,
                details_str[:60],
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
    from .tui.project_manager import ProjectManager

    manager = ProjectManager()
    project_path = Path.cwd()
    project = manager.load_config(project_path)

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
        table.add_row("Automation Level", project.automation_level)
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
    project_path = Path.cwd()

    if key:
        os.environ["MINIMAX_API_KEY"] = key
        console.print("[green]API key set (stored in environment)[/green]")

    if source:
        manager.update_muscle_config(project_path, api_key_source=source)
        console.print(f"[green]API key source set to: {source}[/green]")

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
    project_path = Path.cwd()

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


@settings_group.command(name="platform")
@click.option(
    "--platform", type=click.Choice(["opencode", "claude-code", "auto"]), help="Target platform"
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
    project_path = Path.cwd()

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
    project_path = Path.cwd()

    manager.update_muscle_config(
        project_path,
        hooks_enabled=True,
        review_gate="block+fix",
        platform="auto",
        api_key_source="env",
    )
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


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
