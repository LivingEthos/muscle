"""Provider selection commands for the MUSCLE CLI.

Exposes ``muscle provider show/list/use/login`` and the top-level
``muscle setup`` command. These let users inspect and switch MUSCLE's
execution backend across registered providers and report credential presence
without ever printing secret values.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import click
from rich.table import Table

from ..codex_cli_client import codex_login_status, is_chatgpt_login_status
from ..providers import (
    PROVIDERS,
    ProviderError,
    resolve_provider,
    set_global_provider,
    set_project_provider,
)
from ._shared import cli, console


def _project_config_path(project_path: Path) -> Path:
    """Return the project-scoped provider config path for a working directory."""
    return project_path / ".muscle" / "config.yaml"


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
    if kind == "codex-cli":
        binary = shutil.which("codex")
        if not binary:
            return "missing — install the official codex CLI"
        try:
            status = codex_login_status(binary, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return "codex CLI found, login status unavailable"
        lowered = status.lower()
        if is_chatgpt_login_status(status):
            return "codex CLI found, ChatGPT login active"
        if "api key" in lowered or "apikey" in lowered:
            return "codex CLI found, API-key login active (not valid for codex-subscription)"
        return "codex CLI found, ChatGPT login missing"
    if kind == "openrouter-http":
        if os.environ.get("OPENROUTER_API_KEY"):
            return "present"
        return "missing — set OPENROUTER_API_KEY"
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
    console.print(f"[bold]Role:[/bold] {profile.provider_role}")
    console.print(f"[bold]Surface:[/bold] {profile.execution_surface}")
    console.print(f"[bold]Identity trust:[/bold] {profile.identity_trust}")
    console.print(f"[bold]Pricing source:[/bold] {profile.pricing_source}")
    console.print(f"[bold]Effort control:[/bold] {profile.effort_transport}")
    console.print(f"[bold]Credentials:[/bold] {_credential_status(profile.name)}")
    # Cyber-safeguard friction (data-driven from the provider model's profile).
    # When the model flags dual-use refusal friction (Opus 4.8), warn that using
    # it as the EXECUTOR may hit refusals on security/exploit-adjacent tasks.
    try:
        from ..model_identity import canonical_for_label
        from ..model_profiles import profile_for

        canonical = canonical_for_label(profile.model)
        if profile_for(canonical).security.cyber_safeguard_friction:
            console.print(
                "[yellow]Cyber-safeguard friction:[/yellow] this model as the executor "
                "may refuse or heavily caveat dual-use/security tasks (exploit-adjacent "
                "code, offensive tooling). Prefer it as the host/planner and MiniMax M3 "
                "as the executor for those tasks."
            )
    except Exception:  # pragma: no cover - defensive; never break `provider show`
        pass


@provider.command("list")
def provider_list() -> None:
    """List all providers, marking the active one with ``*``."""
    active, _source = resolve_provider(Path.cwd())
    console.print("Providers: " + ", ".join(PROVIDERS))
    console.print(
        "Roles: "
        + ", ".join(f"{name}={profile.provider_role}" for name, profile in PROVIDERS.items())
    )
    table = Table(title="MUSCLE Providers")
    table.add_column("", style="green", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Model", style="white", no_wrap=True)
    table.add_column("Role", style="green", no_wrap=True)
    table.add_column("Billing", style="yellow", no_wrap=True)
    table.add_column("Trust", style="blue", no_wrap=True)
    table.add_column("Pricing", style="blue", no_wrap=True)
    table.add_column("Effort", style="magenta", no_wrap=True)
    table.add_column("Description", style="white")
    for name, profile in PROVIDERS.items():
        marker = "*" if name == active.name else ""
        table.add_row(
            marker,
            profile.name,
            profile.model,
            profile.provider_role,
            profile.billing_label,
            profile.identity_trust,
            profile.pricing_source,
            profile.effort_transport,
            profile.description,
        )
    # Render wide so provider names/labels are never truncated to fit a narrow
    # terminal; only the trailing description column may wrap.
    console.print(table, width=200)


@provider.command("use")
@click.argument("name")
@click.option("--global", "global_scope", is_flag=True, help="Persist for all projects")
@click.option(
    "--project",
    "project_scope",
    is_flag=True,
    help="Persist for this project only (explicit form of the default)",
)
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
    elif project_scope or not global_scope:
        try:
            set_project_provider(Path.cwd(), name)
        except ProviderError as exc:
            if not _project_config_path(Path.cwd()).exists():
                console.print(
                    "[yellow]No project config found at .muscle/config.yaml. "
                    "Run `muscle init` to create one, or pass `--global` to persist "
                    "this provider for all projects.[/yellow]"
                )
            raise click.ClickException(str(exc)) from exc
        scope_label = "project"

    console.print(f"[green]Provider set to {name} ({scope_label} scope).[/green]")
    console.print(f"[bold]Credentials:[/bold] {_credential_status(name)}")


@provider.command("login")
@click.argument("name", type=click.Choice(["codex-subscription"]))
def provider_login(name: str) -> None:
    """Run provider-owned authentication flows for subscription providers."""
    if name != "codex-subscription":  # pragma: no cover - click choice is closed
        raise click.BadParameter("Only codex-subscription supports provider login.")

    binary = shutil.which("codex")
    if not binary:
        raise click.ClickException(
            "codex-subscription login needs the official `codex` CLI on PATH."
        )

    console.print("[bold]Starting Codex ChatGPT sign-in...[/bold]")
    try:
        proc = subprocess.run([binary, "login"])
    except OSError as exc:
        raise click.ClickException(f"Failed to run `codex login`: {exc}") from exc
    if proc.returncode != 0:
        raise click.ClickException(f"`codex login` exited with status {proc.returncode}.")

    try:
        status = codex_login_status(binary)
    except (OSError, subprocess.SubprocessError) as exc:
        raise click.ClickException(f"Failed to check Codex login status: {exc}") from exc
    lowered = status.lower()
    if is_chatgpt_login_status(status):
        console.print("[green]Codex ChatGPT login active.[/green]")
        return
    if "api key" in lowered or "apikey" in lowered:
        raise click.ClickException(
            "Codex is logged in with an API key. `codex-subscription` requires ChatGPT "
            "sign-in so usage draws from the ChatGPT Codex subscription allowance, not "
            "OpenAI API billing."
        )
    raise click.ClickException(
        f"Codex ChatGPT login was not detected after login. `codex login status` reported: {status}"
    )


def _run_provider_setup(
    provider_name: str | None,
    global_scope: bool,
    non_interactive: bool,
    *,
    fallback_to_global_on_missing_project: bool = False,
) -> None:
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
    elif fallback_to_global_on_missing_project and not _project_config_path(Path.cwd()).exists():
        console.print(
            "[yellow]No project config found at .muscle/config.yaml; writing provider "
            "selection to global scope. Run `muscle init` to create a project config "
            "for project-scoped provider settings.[/yellow]"
        )
        set_global_provider(provider_name)
        scope_label = "global"
    else:
        try:
            set_project_provider(Path.cwd(), provider_name)
        except ProviderError as exc:
            raise click.ClickException(str(exc)) from exc
        scope_label = "project"

    console.print(f"[green]Provider set to {provider_name} ({scope_label} scope).[/green]")
    status = _credential_status(provider_name)
    console.print(f"[bold]Credentials:[/bold] {status}")
    if provider_name == "codex-subscription" and "ChatGPT login active" not in status:
        console.print(
            "[yellow]Run `muscle provider login codex-subscription` to start ChatGPT "
            "sign-in through the official Codex CLI.[/yellow]"
        )


@provider.command("setup")
@click.option(
    "--provider",
    "provider_name",
    type=click.Choice(list(PROVIDERS)),
    default=None,
    help="Provider to select",
)
@click.option("--global", "global_scope", is_flag=True, help="Persist for all projects")
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
def provider_setup(provider_name: str | None, global_scope: bool, non_interactive: bool) -> None:
    """Choose MUSCLE's execution provider from the provider command group."""
    _run_provider_setup(provider_name, global_scope, non_interactive)


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
    _run_provider_setup(
        provider_name,
        global_scope,
        non_interactive,
        fallback_to_global_on_missing_project=True,
    )
