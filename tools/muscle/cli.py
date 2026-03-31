"""
CLI - Command-line interface for MUSCLE.

Provides commands for running, resuming, and managing self-improvement loops.
"""

from __future__ import annotations

import json
import logging
import os
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
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from .budget_manager import BudgetManager
from .code_generator import CodeGenerator
from .cost_optimizer import CostOptimizer
from .evolver import Evolver
from .interactive import InteractiveHandler
from .loop_controller import LoopController, LoopEvent
from .m27_client import M27Client
from .project_builder import ProjectBuilder
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
def init(non_interactive: bool) -> None:
    """Initialize MUSCLE for the current project.

    Creates .muscle/ directory with configuration, knowledge base,
    and memory files. Run this once per project.
    """
    from .tui.project_manager import ProjectConfig, ProjectManager

    console.print("[bold cyan]MUSCLE Initialization[/bold cyan]")
    console.print("=" * 50)

    manager = ProjectManager()
    detected = manager.detect_project()

    if not detected:
        console.print("[yellow]No project detected. Creating default project...[/yellow]")
        project = ProjectConfig(
            name="my-project",
            path=Path.cwd(),
            languages=[],
        )
    else:
        project = detected

    console.print(f"Project: [cyan]{project.name}[/cyan]")
    console.print(f"Path: [cyan]{project.path}[/cyan]")
    if project.languages:
        console.print(f"Languages: [cyan]{', '.join(project.languages)}[/cyan]")
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

    console.print()
    console.print("[bold]Initializing...[/bold]")

    if manager.init_project(project):
        console.print("[green]✓[/green] Created .muscle/ directory")
        console.print("[green]✓[/green] Created config.yaml")
        console.print("[green]✓[/green] Created CLAUDE.md, AGENT.md, MEMORY.md")
        console.print("[green]✓[/green] Initialized knowledge base")
        console.print()
        console.print("[bold green]MUSCLE initialized successfully![/bold green]")
        console.print()
        console.print("Run 'muscle tui' to start the TUI")
        console.print("Run 'muscle review --target ./src' to run a review")
    else:
        console.print("[red]Failed to initialize project[/red]")


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

    console.print(
        f"[bold]MUSCLE Session[/bold] - Task: {_truncate(task, MAX_TASK_PREVIEW_LENGTH)}..."
    )
    console.print(f"Config: iterations={max_iterations}, timeout={timeout}, budget={budget}")

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


@cli.command()
@click.argument("session_id")
def resume(session_id: str) -> None:
    """Resume a failed or incomplete session"""
    session_manager = SessionManager()
    session = session_manager.load_session(session_id)

    if not session:
        console.print(f"[red]Session {session_id} not found[/red]")
        sys.exit(1)

    evolved_strategy = session_manager.load_evolved_strategy(session_id)

    console.print(f"[bold]Resuming session {session_id}[/bold]")
    console.print(f"Task: {session.get('task', 'Unknown')}")
    console.print(
        f"Previous evolved strategy: {_truncate(evolved_strategy, 100) if evolved_strategy else 'None'}..."
    )

    # TODO: Implement full resume logic
    console.print("[yellow]Resume not yet fully implemented[/yellow]")


@cli.command()
@click.argument("session_id")
def abort(session_id: str) -> None:
    """Abort a running session"""
    console.print(f"[yellow]Abort not yet implemented for session {session_id}[/yellow]")


@cli.command()
def check() -> None:
    """Single-shot validation (no loop)"""
    console.print("[yellow]Check command not yet implemented[/yellow]")


@cli.command()
@click.option("--pattern", "-p", required=True, help="Error pattern")
@click.option("--solution", "-s", required=True, help="Solution strategy")
def knowledge_add(pattern: str, solution: str) -> None:
    """Add a global knowledge base entry"""
    console.print("[yellow]Knowledge add not yet implemented[/yellow]")
    console.print(f"Pattern: {pattern}")
    console.print(f"Solution: {solution}")


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


def _parse_timeout(timeout_str: str) -> int:
    if not timeout_str:
        return 3600
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = timeout_str[-1].lower()
    if unit in multipliers:
        try:
            value = int(timeout_str[:-1])
            seconds = value * multipliers[unit]
            return min(seconds, MAX_TIMEOUT_SECONDS)
        except ValueError:
            return 3600
    try:
        seconds = int(timeout_str)
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

        scle review --target ./src --language python

        scle review --target ./src --mode hybrid --severity high

        scle review --target ./src --mode plan --output handoff.md

        scle review --target ./src --mode pressure --intensity intensive

        scle review --target ./src --shadow  # Run in background

        scle review --target ./src --mode pressure --focus design,failure,race
    """
    from .code_review import (
        Intensity,
        ReviewConfig,
        ReviewController,
        ReviewEvent,
        ReviewMode,
        Severity,
    )
    from .code_review.shadow_broker import ShadowBroker

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

        broker = ShadowBroker()
        job_id = broker.create_job(
            target_path=target,
            mode=mode_map.get(mode, ReviewMode.REVIEW),
            intensity=intensity_map.get(intensity, Intensity.MODERATE),
        )
        worker_manager = WorkerManager(broker)
        worker_manager.submit_shadow_job(
            job_id=job_id,
            target_path=target,
            mode=mode_map.get(mode, ReviewMode.REVIEW),
            intensity=intensity_map.get(intensity, Intensity.MODERATE),
        )
        console.print(f"[cyan]Shadow job created: {job_id}[/cyan]")
        console.print("Check status with: scle probe")
        console.print("Get results with: scle diagnosis")
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

    controller = ReviewController(
        config=config,
        m27_client=m27_client,
        event_callback=event_handler,
    )

    try:
        result = controller.run()
        review_result = controller.get_review_result()

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

        scle lifeline --target ./src --prompt "investigate why auth is failing"

        scle lifeline --target ./tests --prompt "debug the flaky integration test"

        scle lifeline --target ./src/auth.py --prompt "suggest improvements to error handling"
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        sys.exit(1)

    from .m27_client import M27Client

    intensity_map = {
        "minimal": "quick scan, surface-level analysis",
        "moderate": "thorough investigation with multiple hypotheses",
        "intensive": "deep dive with code tracing and extensive testing",
        "exhaustive": "comprehensive analysis including edge cases, performance, and security",
    }

    m27_client = M27Client(api_key=api_key)

    system_prompt = f"""You are a debugging and investigation assistant. Your task is to:
1. Investigate the reported issue thoroughly
2. Trace through the code to understand root causes
3. Propose concrete fixes
4. Validate that your fixes work

Be methodical. Check edge cases. Verify your assumptions.

Investigation intensity: {intensity_map.get(intensity, intensity_map["moderate"])}"""

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

        scle probe                    # Show all recent jobs

        scle probe --job-id abc12345  # Show specific job status
    """
    from .code_review.shadow_broker import ShadowBroker

    broker = ShadowBroker()

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
            console.print("Run 'scle review --shadow' to start a background review")
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

        scle diagnosis                    # Show most recent results

        scle diagnosis --job-id abc12345  # Show specific job results
    """
    from .code_review.shadow_broker import ShadowBroker

    broker = ShadowBroker()

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
            console.print(f"Use 'scle probe --job-id {job_id}' to check progress")
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


def _get_status_color(status: str) -> str:
    color_map = {
        "pending": "yellow",
        "running": "cyan",
        "completed": "green",
        "failed": "red",
        "cancelled": "dim",
    }
    return color_map.get(status, "white")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
