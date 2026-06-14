"""Memory commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.memory.<name>``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from ..audit_presenter import format_action_log_entry
from ..project_memory import ProjectMemory
from ..self_improver import SelfImprover
from ..strategy_kb import GlobalKnowledgeBase
from ..system_db import SystemDatabase
from ._shared import (
    TRANSFER_AUDIT_ACTIONS,
    _lesson_usage_source_label,
    _parse_json_dict,
    _resolve_project_context,
    _source_project_name,
    _suggest_related_projects,
    _truncate,
    cli,
    console,
)


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
    from ..strategy_kb import GlobalKnowledgeBase

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
    from ..project_memory import ProjectMemory
    from ..project_notes import ProjectNotes

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
    from ..project_memory import ProjectMemory
    from ..project_notes import ProjectNotes

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
    from ..project_memory import ProjectMemory
    from ..project_notes import ProjectNotes

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
    from ..project_memory import ProjectMemory
    from ..project_notes import ProjectNotes

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
    from ..project_memory import ProjectMemory
    from ..project_notes import ProjectNotes

    if not (0.0 <= threshold <= 1.0):
        console.print("[red]Threshold must be between 0.0 and 1.0[/red]")
        sys.exit(1)

    project_path = str(Path.cwd())
    memory = ProjectMemory(project_path)
    notes = ProjectNotes(memory, project_path)

    merged = notes.dedupe_notes(similarity_threshold=threshold)
    console.print(f"[green]Merged {merged} duplicate pair(s)[/green]")


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
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
