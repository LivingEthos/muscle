"""Plumbing commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.plumbing.<name>``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
from rich.table import Table

from ..providers import create_client
from ._shared import (
    _build_context_budgeter,
    _emit_json,
    _parse_since,
    _resolve_project_context,
    cli,
    console,
)


@cli.command(name="crush")
@click.argument("file", required=False, type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--label", default="records", show_default=True, help="Label for JSON record payloads"
)
@click.option(
    "--budget-lines",
    type=int,
    default=None,
    help="Line budget for windowing (default: crusher default)",
)
@click.option("--no-store", is_flag=True, help="Do not save the original for `muscle expand`")
@click.option("--json", "json_output", is_flag=True, help="Emit a JSON envelope with metrics")
def crush(
    file: str | None,
    label: str,
    budget_lines: int | None,
    no_store: bool,
    json_output: bool,
) -> None:
    """Compress a large tool output before it enters the host model's context.

    Reads FILE or stdin. Compressed text goes to stdout (pipe-clean); metrics and
    the `ccr:` retrieval handle go to stderr. Recover the original with
    `muscle expand <handle>`.
    """
    from ..optimization.tool_output_crusher import DEFAULT_LINE_BUDGET, CcrStore, crush_text

    text = Path(file).read_text() if file else click.get_text_stream("stdin").read()
    store = None if no_store else CcrStore(Path.cwd() / ".muscle" / "ccr")
    result = crush_text(
        text,
        label=label,
        line_budget=budget_lines if budget_lines is not None else DEFAULT_LINE_BUDGET,
        store=store,
    )
    if json_output:
        click.echo(json.dumps({"text": result.text, **result.to_metadata()}))
        return
    click.echo(result.text)
    pct = (
        100.0 * (result.original_chars - result.compact_chars) / result.original_chars
        if result.original_chars
        else 0.0
    )
    footer = (
        f"[crush] strategy={result.strategy} chars {result.original_chars}->"
        f"{result.compact_chars} (-{pct:.0f}%) ~{result.estimated_tokens_saved} tokens saved"
    )
    if result.handle:
        footer += f" original={result.handle}"
    click.echo(footer, err=True)


@cli.command(name="expand")
@click.argument("handle")
def expand(handle: str) -> None:
    """Print the stored original for a `ccr:` handle produced by `muscle crush`."""
    from ..optimization.tool_output_crusher import CcrStore, CcrStoreError

    store = CcrStore(Path.cwd() / ".muscle" / "ccr")
    try:
        click.echo(store.load(handle), nl=False)
    except CcrStoreError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.group(name="filters")
def filters_group() -> None:
    """Verify and trust declarative command-output filters."""


@filters_group.command(name="verify")
@click.option("--filter", "filter_name", default=None, help="Verify one filter by name")
@click.option("--require-all", is_flag=True, help="Require inline tests for every filter")
@click.option("--json", "json_output", is_flag=True, help="Emit structured filter output")
def filters_verify(filter_name: str | None, require_all: bool, json_output: bool) -> None:
    """Verify built-in and trusted project-local output filters."""

    from ..output_filters import verify_filters

    project_path, _ = _resolve_project_context(Path.cwd())
    report = verify_filters(project_path, filter_name=filter_name, require_all=require_all)
    if json_output:
        _emit_json(report)
        return
    status = "[green]passed[/green]" if report["passed"] else "[red]failed[/red]"
    console.print(f"Filter verification {status} ({report['filter_count']} filter(s))")
    for warning in report.get("warnings", []):
        console.print(f"[yellow]WARN[/yellow] {warning}")


@filters_group.command(name="trust")
@click.option("--json", "json_output", is_flag=True, help="Emit structured filter output")
def filters_trust(json_output: bool) -> None:
    """Trust current project-local `.muscle/filters.yaml` content."""

    from ..output_filters import trust_project_filters

    project_path, _ = _resolve_project_context(Path.cwd())
    report = trust_project_filters(project_path)
    if json_output:
        _emit_json(report)
        return
    if report.get("trusted"):
        console.print(f"[green]Trusted project filters[/green] {report.get('filters_sha256')}")
    else:
        console.print(f"[yellow]Project filters not trusted:[/yellow] {report.get('reason')}")


@filters_group.command(name="untrust")
@click.option("--json", "json_output", is_flag=True, help="Emit structured filter output")
def filters_untrust(json_output: bool) -> None:
    """Remove project-local filter trust."""

    from ..output_filters import untrust_project_filters

    project_path, _ = _resolve_project_context(Path.cwd())
    report = untrust_project_filters(project_path)
    if json_output:
        _emit_json(report)
        return
    console.print("[green]Project filter trust removed.[/green]")


@cli.group(name="cache")
def cache_group() -> None:
    """Manage MUSCLE response cache."""
    pass


@cache_group.command(name="clear")
@click.option(
    "--older-than", default=None, help="Only clear entries older than this (e.g. '7d', '30d')"
)
def cache_clear_cmd(older_than: str | None) -> None:
    """Clear cached MiniMax M3 responses."""
    from ..response_cache import ResponseCache

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

    from ..packs import PackBuilder

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
    from ..packs import PackStore

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
    from ..packs import PackStore

    store = PackStore(Path.cwd())
    td = _parse_since(older_than)
    removed = store.gc(older_than=td)
    click.echo(f"Removed {removed} pack(s) older than {older_than}.")


@cli.group(name="escalation")
def escalation_group() -> None:
    """Manage MUSCLE escalation records."""
    pass


@escalation_group.command(name="list")
def escalation_list_cmd() -> None:
    """List unresolved escalation records."""
    from ..escalation import EscalationRecorder

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
    from ..escalation import EscalationRecorder

    resolved = EscalationRecorder.resolve(Path.cwd(), escalation_id)
    if resolved:
        click.echo(f"Escalation {escalation_id} resolved.")
    else:
        click.echo(f"Escalation {escalation_id} not found.", err=True)


@cli.command(name="route")
@click.option("--task", required=True, help="Task description to classify.")
@click.option("--scope", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON output.")
def route_cmd(task: str, scope: Path | None, as_json: bool) -> None:
    """Classify a task and decide where it should run (MiniMax M3 vs host).

    Falls back to a deterministic heuristic when ``MINIMAX_API_KEY`` is not set
    or the MiniMax M3 classifier is unreachable, so the slash-command always returns
    a usable decision without raising.
    """
    from ..routing import ROUTING_PROFILE_CURRENT, TaskRouter, offline_route

    api_key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    decision = None
    fallback_reason: str | None = None
    if api_key:
        try:
            client = create_client(api_key=api_key)
            router = TaskRouter(client)
            decision = router.route(task, scope=scope)
        except Exception as exc:
            fallback_reason = f"MiniMax M3 classifier unavailable: {exc}"
    else:
        fallback_reason = "MINIMAX_API_KEY not set"

    if decision is None:
        decision = offline_route(task, ROUTING_PROFILE_CURRENT)

    if as_json:
        payload = {
            "tier": decision.tier.value,
            "recommended": decision.recommended.value,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "from_cache": decision.from_cache,
        }
        if fallback_reason is not None:
            payload["fallback"] = "offline_heuristic"
            payload["fallback_reason"] = fallback_reason
        click.echo(json.dumps(payload))
    else:
        if fallback_reason is not None:
            click.echo(f"[heuristic fallback] {fallback_reason}", err=True)
        click.echo(f"Tier:        {decision.tier.value}")
        click.echo(f"Recommended: {decision.recommended.value}")
        click.echo(f"Confidence:  {decision.confidence:.2f}")
        click.echo(f"Rationale:   {decision.rationale}")
