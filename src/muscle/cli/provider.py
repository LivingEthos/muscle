"""Provider selection commands for the MUSCLE CLI.

Exposes ``muscle provider show/list/use`` and the top-level ``muscle setup``
command. These let users inspect and switch MUSCLE's execution backend across
the four registered providers and report credential presence without ever
printing secret values.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click
from rich.table import Table

from ..providers import (
    PROVIDERS,
    ProviderError,
    resolve_provider,
    set_global_provider,
    set_project_provider,
)
from ._shared import cli, console


def _credential_status(name: str) -> str:
    """Describe credential presence for a provider (presence only, no secrets)."""
    profile = PROVIDERS.get(name)
    kind = profile.kind if profile is not None else name
    if kind == "minimax-http":
        if os.environ.get("MINIMAX_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
            return "present"
        return "missing — set MINIMAX_API_KEY"
    if kind == "anthropic-http":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            if key.startswith("sk-ant-"):
                return "present"
            return "present but does not look like an Anthropic key (sk-ant-...)"
        return "missing — set ANTHROPIC_API_KEY (real Anthropic key)"
    if kind == "claude-cli":
        if shutil.which("claude"):
            return "claude CLI found"
        return "missing — install the official claude CLI and log in"
    return "unknown"


@cli.group()
def provider() -> None:
    """Inspect and switch MUSCLE's execution provider."""


@provider.command("show")
def provider_show() -> None:
    """Show the active provider and its credential status."""
    profile, source = resolve_provider(Path.cwd())
    console.print(f"[bold]Provider:[/bold] {profile.name}")
    console.print(f"[bold]Resolved from:[/bold] {source}")
    console.print(f"[bold]Model:[/bold] {profile.model}")
    console.print(f"[bold]Billing:[/bold] {profile.billing_label}")
    console.print(f"[bold]Credentials:[/bold] {_credential_status(profile.name)}")


@provider.command("list")
def provider_list() -> None:
    """List all providers, marking the active one with ``*``."""
    active, _source = resolve_provider(Path.cwd())
    table = Table(title="MUSCLE Providers")
    table.add_column("", style="green", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Model", style="white", no_wrap=True)
    table.add_column("Billing", style="yellow", no_wrap=True)
    table.add_column("Description", style="white")
    for name, profile in PROVIDERS.items():
        marker = "*" if name == active.name else ""
        table.add_row(
            marker,
            profile.name,
            profile.model,
            profile.billing_label,
            profile.description,
        )
    # Render wide so provider names/labels are never truncated to fit a narrow
    # terminal; only the trailing description column may wrap.
    console.print(table, width=200)


@provider.command("use")
@click.argument("name")
@click.option("--global", "global_scope", is_flag=True, help="Persist for all projects")
@click.option("--project", "project_scope", is_flag=True, help="Persist for this project only")
def provider_use(name: str, global_scope: bool, project_scope: bool) -> None:
    """Select provider NAME at project (default) or global scope."""
    if global_scope and project_scope:
        raise click.UsageError("--global and --project are mutually exclusive.")
    if name not in PROVIDERS:
        raise click.BadParameter(
            f"Unknown provider {name!r}. Valid providers: {', '.join(PROVIDERS)}",
            param_hint="NAME",
        )

    if global_scope:
        set_global_provider(name)
        scope_label = "global"
    else:
        try:
            set_project_provider(Path.cwd(), name)
        except ProviderError as exc:
            raise click.ClickException(str(exc)) from exc
        scope_label = "project"

    console.print(f"[green]Provider set to {name} ({scope_label} scope).[/green]")
    console.print(f"[bold]Credentials:[/bold] {_credential_status(name)}")


@cli.command("setup")
@click.option(
    "--provider",
    "provider_name",
    type=click.Choice(list(PROVIDERS)),
    default=None,
    help="Provider to select",
)
@click.option("--global", "global_scope", is_flag=True, help="Persist for all projects")
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
def setup(provider_name: str | None, global_scope: bool, non_interactive: bool) -> None:
    """Choose MUSCLE's execution provider, interactively or via ``--provider``."""
    names = list(PROVIDERS)

    if provider_name is None:
        if non_interactive:
            raise click.UsageError("--non-interactive requires --provider; no provider to select.")
        console.print("[bold]Choose a MUSCLE execution provider:[/bold]")
        for idx, name in enumerate(names, start=1):
            profile = PROVIDERS[name]
            console.print(f"  {idx}. {profile.name} — {profile.model} ({profile.billing_label})")
        choice = click.prompt(
            "Provider number",
            type=click.IntRange(1, len(names)),
        )
        provider_name = names[choice - 1]

    if global_scope:
        set_global_provider(provider_name)
        scope_label = "global"
    else:
        try:
            set_project_provider(Path.cwd(), provider_name)
        except ProviderError as exc:
            raise click.ClickException(str(exc)) from exc
        scope_label = "project"

    console.print(f"[green]Provider set to {provider_name} ({scope_label} scope).[/green]")
    console.print(f"[bold]Credentials:[/bold] {_credential_status(provider_name)}")
