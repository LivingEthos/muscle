"""Model commands for the MUSCLE CLI.

Split out of the former monolithic ``muscle/cli.py`` with command bodies
unchanged. Third-party classes and shared helpers are imported here so that
test patch targets resolve at the point of use (``muscle.cli.model.<name>``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import click
from rich.table import Table

from ..audit_presenter import format_action_log_entry
from ..backup_manager import BackupManager
from ..model_packs import DEFAULT_MODEL_PACK_REF, DEFAULT_MODEL_PACK_REPO, ModelPackManager
from ..project_memory import ProjectMemory
from ..system_db import SystemDatabase
from ._shared import (
    _format_size,
    _print_backup_scope_note,
    _refresh_active_review_safe,
    _resolve_model_identity,
    _resolve_project_context,
    _truncate,
    cli,
    console,
)


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
    help="Canonical model key (for example minimax/m3@1)",
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
    from ..tui.project_manager import ProjectManager

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
        table.add_row("Hooks (project setting)", str(project.hooks_enabled))
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
    from ..tui.project_manager import ProjectManager

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
        # B2: only prompt for input when stdin is an interactive TTY. When the
        # CLI is invoked from a slash-command subprocess (Claude Code / Codex)
        # there is no TTY, so prompting would abort with a confusing
        # "Aborted!" message. In that case, return after printing the status.
        if not sys.stdin.isatty():
            return
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
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
    from ..tui.project_manager import ProjectManager

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
