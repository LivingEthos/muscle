"""Cost commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.cost.<name>``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.table import Table

from ..cost_optimizer import CostOptimizer
from ..optimization import (
    ExternalBenchmarkImporter,
    WorkflowOptimizer,
)
from ..project_memory import ProjectMemory
from ..providers import ProviderError, create_client, resolve_provider
from ._shared import (
    _get_status_color,
    _parse_since,
    _refresh_active_review_safe,
    _resolve_project_context,
    _run_benchmark_release_invariants,
    cli,
    console,
    logger,
)


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


@cost_group.command(name="delegation-report")
@click.option("--since", "since_str", default="7d", help="Lookback window (e.g. 7d, 14d, 30d)")
@click.option("--format", "fmt", type=click.Choice(["text", "json"]), default="text")
@click.option(
    "--host-model",
    default="claude-fable-5",
    show_default=True,
    help="Host model for token-avoidance and dollar-savings estimates",
)
def cost_delegation_report(since_str: str, fmt: str, host_model: str) -> None:
    """Show cost-delegation observability report."""
    from ..delegation_metrics import DelegationMetrics

    since_td = _parse_since(since_str)
    metrics = DelegationMetrics(Path.cwd())
    try:
        rpt = metrics.report(since=since_td, host_model=host_model)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--host-model") from exc

    if fmt == "json":
        click.echo(metrics.format_json(rpt))
    else:
        click.echo(metrics.format_text(rpt))


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
    """Throw a lifeline to MiniMax M3 to investigate issues, propose fixes, or debug problems.

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
    # Provider-aware credential guard: only MiniMax-backed providers require a
    # MiniMax key env var. Other providers enforce their own credentials inside
    # their client constructors.
    cwd = Path.cwd()
    try:
        provider_profile, _provider_source = resolve_provider(cwd)
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    if provider_profile.kind == "minimax-http" and not api_key:
        console.print("[red]Error: MINIMAX_API_KEY not set[/red]")
        console.print("Set it with: export MINIMAX_API_KEY='your-key'")
        console.print("Get a key at: https://platform.minimax.io")
        sys.exit(1)

    try:
        m27_client = create_client(project_path=cwd)
    except (ValueError, ProviderError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)
    history_requested = history or bisect_cmd is not None
    history_summary = ""
    history_artifact = ""
    if history_requested:
        from ..git_history_forensics import GitHistoryForensics

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
        console.print("[cyan]Throwing lifeline to MiniMax M3...[/cyan]")
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
    from ..code_review.shadow_broker import ShadowBroker

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
    from ..code_review.shadow_broker import ShadowBroker

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
    from ..code_review.long_eval_runner import LongEvalConfig, LongEvalRunner

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
    from ..code_review.mutation_runner import MutationRunner

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
    from ..code_review.long_eval_runner import LongEvalRunner

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
    from ..code_review.long_eval_runner import LongEvalRunner

    runner = LongEvalRunner(str(Path.cwd()))
    if not force:
        if not click.confirm(f"Remove reports older than {days} days?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    removed = runner.cleanup_old_reports(days_to_keep=days)
    console.print(f"[green]Removed {removed} old reports.[/green]")


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
    from ..code_review.review_benchmark import ReviewBenchmarkRunner

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
