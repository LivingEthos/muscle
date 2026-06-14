"""Loop commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.loop.<name>``).
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Any

import click
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text

from ..budget_manager import BudgetManager
from ..code_generator import CodeGenerator
from ..cost_optimizer import CostOptimizer
from ..evolver import Evolver
from ..interactive import InteractiveHandler
from ..learning_ingestor import LearningIngestor
from ..loop_controller import LoopController
from ..project_builder import ProjectBuilder
from ..project_memory import ProjectMemory
from ..project_memory_types import TaskStatus
from ..session_manager import SessionManager
from ..types import BudgetMode, EvalMode, RunConfig, SessionStatus
from ..visual_devflow import VisualDevFlowBridge
from ..webhook_notifier import WebhookNotifier
from ._shared import (
    MAX_TASK_PREVIEW_LENGTH,
    _attach_optimization_runtime,
    _create_event_handler,
    _create_m27_client,
    _emit_json,
    _is_process_alive,
    _parse_budget,
    _parse_timeout,
    _read_session_pid,
    _resolve_project_context,
    _serialize_json,
    _session_report_to_dict,
    _truncate,
    cli,
    console,
    logger,
)


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
@click.option(
    "--visual/--no-visual",
    default=True,
    help="Emit lifecycle events to Visual DevFlow when enabled",
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
    visual: bool,
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
        console.print("Get a key at: https://platform.minimax.io")
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
        from ..evaluator_registry import EvaluatorRegistry

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

    from ..session_manager import SessionManager

    session_manager = SessionManager()

    webhook_notifier = WebhookNotifier(webhook_url or os.environ.get("MUSCLE_WEBHOOK_URL"))

    interactive_handler = InteractiveHandler(enabled=interactive)
    visual_bridge = (
        VisualDevFlowBridge.discover(
            project_path,
            run_task=task,
            run_output_dir=output,
            run_max_iterations=max_iterations,
        )
        if visual
        else None
    )
    stream_state, event_handler = _create_event_handler(visual_bridge)

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
        console.print("Get a key at: https://platform.minimax.io")
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
        from ..evaluator_registry import EvaluatorRegistry

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

    visual_bridge = VisualDevFlowBridge.discover(
        project_path,
        run_task=resume_ctx.config.task,
        run_output_dir=resume_ctx.config.output_dir,
        run_max_iterations=resume_ctx.config.max_iterations,
    )
    stream_state, event_handler = _create_event_handler(visual_bridge)
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
    from ..evaluator_registry import LANGUAGE_EVALUATORS, EvaluatorRegistry

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
        _emit_json(output)
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
