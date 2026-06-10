"""Review commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.review.<name>``).
"""

from __future__ import annotations

import os
import sys
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from typing import Any

import click

from ..code_review.learning_pipeline import LearningPipeline
from ..learning_ingestor import LearningIngestor
from ..m27_client import M27Client
from ..optimization import (
    WorkflowOptimizer,
)
from ..project_memory import ProjectMemory
from ..visual_devflow import VisualDevFlowBridge
from ._shared import (
    _attach_optimization_runtime,
    _emit_json,
    _refresh_active_review_safe,
    _resolve_review_execution_mode,
    _resolve_stage_totals,
    _serialize_json,
    cli,
    console,
    logger,
)


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
@click.option(
    "--visual/--no-visual",
    default=True,
    help="Emit lifecycle events to Visual DevFlow when enabled",
)
@click.option(
    "--no-db",
    is_flag=True,
    default=False,
    help="Skip ProjectMemory, learning, and optimization writes for this review",
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
    visual: bool,
    no_db: bool,
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
    from ..code_review import (
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
    if no_db:
        logger.info("Memory-only review mode active (--no-db): skipping project memory defaults")
    else:
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
        from ..code_review.shadow_worker import WorkerManager

        visual_bridge = (
            VisualDevFlowBridge.discover(
                project_path,
                review_target=str(resolved_target),
                review_mode=mode,
                review_workflow=configured_workflow,
            )
            if visual
            else None
        )
        worker_manager = WorkerManager(project_path=project_path)
        job_id = worker_manager.submit_shadow_job(
            target_path=str(resolved_target),
            mode=mode_map.get(mode, ReviewMode.REVIEW),
            intensity=intensity_map.get(intensity, Intensity.MODERATE),
            execution_mode=execution_mode,
            workflow_name=configured_workflow,
            detached=True,
        )
        if visual_bridge is not None:
            visual_bridge.emit_shadow_review_submitted(
                job_id=job_id,
                target_path=str(resolved_target),
                mode=mode,
                workflow_name=configured_workflow,
            )
        console.print(f"[cyan]Shadow job created: {job_id}[/cyan]")
        console.print("Check status with: muscle probe")
        console.print("Get results with: muscle diagnosis")
        console.print("[dim]Detached worker launched in background...[/dim]")
        return

    visual_bridge = (
        VisualDevFlowBridge.discover(
            project_path,
            review_target=str(resolved_target),
            review_mode=mode,
            review_workflow=configured_workflow,
        )
        if visual
        else None
    )

    def event_handler(event: ReviewEvent, data: dict) -> None:
        if visual_bridge is not None:
            visual_bridge.handle_review_event(event, data)
        if json_output:
            return
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
            console.print("Get a key at: https://platform.minimax.io")
        sys.exit(1)

    m27_client = M27Client(api_key=api_key)
    if no_db:
        pm = None
        optimizer = None
        context_budgeter = None
        telemetry_recorder = None
        lesson_resolver = None
    else:
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
        if no_db:
            pm = None
            ingestor = None
        elif pm is None:
            pm = ProjectMemory(project_path)
            ingestor = LearningIngestor(pm)
        else:
            ingestor = LearningIngestor(pm)
    except Exception as e:
        logger.warning("ProjectMemory init failed: %s", e)
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
        event_callback=event_handler if visual_bridge is not None or not json_output else None,
        correction_signal_callback=on_correction_signal,
        project_path=project_path,
        context_budgeter=context_budgeter,
        lesson_resolver=lesson_resolver,
    )

    try:
        output_context = redirect_stdout(sys.stderr) if json_output else nullcontext()
        output_data: dict[str, Any] | None = None
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
            if review_result and not no_db:
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
                        from ..change_capture import ChangeCapture

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

        if output:
            if json_output:
                if output_data is not None:
                    Path(output).write_text(_serialize_json(output_data), encoding="utf-8")
            elif result.handoff_plan:
                Path(output).write_text(result.handoff_plan.markdown, encoding="utf-8")
                console.print(f"\n[green]Handoff plan written to {output}[/green]")

        _refresh_active_review_safe(project_path, reason="review-complete")

    except KeyboardInterrupt:
        console.print("\n[yellow]Review interrupted by user[/yellow]")
        sys.exit(130)
    finally:
        if telemetry_recorder is not None:
            telemetry_recorder.close()
