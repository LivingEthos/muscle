"""Provider profiles and resolution for MUSCLE's execution backend.

MUSCLE's execution layer can run on one of four providers. Resolution order:
``MUSCLE_PROVIDER`` env var -> per-project ``.muscle/config.yaml`` -> global
``~/.muscle/config.json`` -> default ``minimax-plan`` (backward compatible).
Unknown provider names raise (fail closed) rather than silently falling back.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .m27_client import M27Client

logger = logging.getLogger("muscle.providers")

DEFAULT_PROVIDER = "minimax-plan"
GLOBAL_CONFIG_PATH = Path.home() / ".muscle" / "config.json"


class ProviderError(RuntimeError):
    """Provider misconfiguration or unavailability."""


class ProviderBillingError(ProviderError):
    """Provider refused work for billing reasons (e.g. Agent SDK credit exhausted)."""


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    kind: str  # "minimax-http" | "anthropic-http" | "claude-cli"
    model: str
    billing: str  # "plan-quota" | "api-dollars" | "agent-sdk-credit"
    billing_label: str
    description: str


PROVIDERS: Mapping[str, ProviderProfile] = MappingProxyType(
    {
        "minimax-plan": ProviderProfile(
            name="minimax-plan",
            kind="minimax-http",
            model="MiniMax-M3",
            billing="plan-quota",
            billing_label="plan quota, $0 marginal",
            description="MiniMax M3 via subscription token-plan key (default)",
        ),
        "minimax-api": ProviderProfile(
            name="minimax-api",
            kind="minimax-http",
            model="MiniMax-M3",
            billing="api-dollars",
            billing_label="MiniMax API dollars",
            description="MiniMax M3 pay-as-you-go API key (same wire protocol as plan)",
        ),
        "claude-subscription": ProviderProfile(
            name="claude-subscription",
            kind="claude-cli",
            model="claude-opus-4-8",
            billing="agent-sdk-credit",
            billing_label="Agent SDK credit",
            description="Official `claude` CLI in headless print mode (Opus only)",
        ),
        "anthropic-api": ProviderProfile(
            name="anthropic-api",
            kind="anthropic-http",
            model="claude-opus-4-8",
            billing="api-dollars",
            billing_label="Anthropic API dollars",
            description="Direct Anthropic API with a real ANTHROPIC_API_KEY (Opus only)",
        ),
    }
)


def _require(name: str, origin: str) -> ProviderProfile:
    profile = PROVIDERS.get(name)
    if profile is None:
        raise ValueError(
            f"Unknown provider {name!r} (from {origin}). "
            f"Valid providers: {', '.join(sorted(PROVIDERS))}"
        )
    return profile


def _project_provider_name(project_path: Path | None) -> str | None:
    if project_path is None:
        return None
    config_path = Path(project_path) / ".muscle" / "config.yaml"
    if not config_path.exists():
        return None
    try:
        text = config_path.read_text(encoding="utf-8")
        if text.lstrip().startswith("{"):
            # JSON-looking content must parse as JSON. Falling back to YAML
            # here could silently mis-parse partial/corrupt JSON.
            data = json.loads(text)
        else:
            data = yaml.safe_load(text) or {}
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        logger.warning(
            "Unreadable project config at %s; ignoring for provider resolution", config_path
        )
        return None
    value = (data.get("project") or {}).get("provider")
    return value if isinstance(value, str) and value else None


def _global_provider_name() -> str | None:
    if not GLOBAL_CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(GLOBAL_CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "Unreadable global config at %s; ignoring for provider resolution",
            GLOBAL_CONFIG_PATH,
        )
        return None
    value = data.get("provider")
    return value if isinstance(value, str) and value else None


def resolve_provider(project_path: Path | None = None) -> tuple[ProviderProfile, str]:
    """Resolve the active provider. Returns (profile, source).

    source is one of: "env", "project", "global", "default".
    """
    env_name = os.environ.get("MUSCLE_PROVIDER")
    if env_name:
        return _require(env_name, "MUSCLE_PROVIDER env var"), "env"
    project_name = _project_provider_name(project_path)
    if project_name:
        return _require(project_name, ".muscle/config.yaml"), "project"
    global_name = _global_provider_name()
    if global_name:
        return _require(global_name, str(GLOBAL_CONFIG_PATH)), "global"
    return PROVIDERS[DEFAULT_PROVIDER], "default"


def create_client(
    provider: str | None = None,
    project_path: Path | None = None,
    **client_kwargs: Any,
) -> M27Client:
    """Return the configured execution client. All M27Client construction in
    MUSCLE product code goes through here (tests may construct directly)."""
    from .m27_client import M27Client

    if provider is not None:
        profile, source = _require(provider, "create_client(provider=...)"), "explicit"
    else:
        profile, source = resolve_provider(project_path)
    logger.debug("Provider %s resolved from %s", profile.name, source)

    client: M27Client
    if profile.kind == "minimax-http":
        client = M27Client(**client_kwargs)
    elif profile.kind == "anthropic-http":
        from .anthropic_client import AnthropicApiClient

        client_kwargs.pop("api_key", None)  # MiniMax keys must never reach the Anthropic path
        client = AnthropicApiClient(model=profile.model, **client_kwargs)
    elif profile.kind == "claude-cli":
        from .claude_cli_client import ClaudeCliClient

        allowed = {"cache_db_path", "cache_pack_id"}
        client = ClaudeCliClient(
            model=profile.model,
            **{k: v for k, v in client_kwargs.items() if k in allowed},
        )
    else:  # pragma: no cover — registry is closed
        raise ProviderError(f"Unhandled provider kind {profile.kind!r}")
    client.provider_profile = profile
    return client


def set_global_provider(name: str) -> None:
    """Persist the provider choice in ~/.muscle/config.json (atomic, merged)."""
    from .io_safety import update_json_file_locked

    _require(name, "set_global_provider")
    GLOBAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _update(data: dict[str, object]) -> dict[str, object]:
        data["provider"] = name
        return data

    update_json_file_locked(GLOBAL_CONFIG_PATH, _update, default_factory=dict)


def set_project_provider(project_path: Path, name: str) -> None:
    """Persist the provider choice in <project>/.muscle/config.yaml (atomic, merged).

    The canonical on-disk format is JSON stored in a ``.yaml`` file (matching
    ``ProjectManager._write_config``). Legacy genuine-YAML files are accepted on
    read and migrated to JSON on the first provider write.
    """
    from .io_safety import advisory_file_lock, atomic_write_text

    _require(name, "set_project_provider")
    config_path = Path(project_path) / ".muscle" / "config.yaml"
    if not config_path.exists():
        raise ProviderError(f"No .muscle/config.yaml at {project_path} — run `muscle init` first.")

    with advisory_file_lock(config_path):
        text = config_path.read_text(encoding="utf-8")
        data: Any = {}
        if text.strip():
            if text.lstrip().startswith("{"):
                # JSON-looking content must parse as JSON (no YAML fallback that
                # could silently mis-parse partial JSON). Fail closed on corruption.
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"Corrupt project config at {config_path}: {exc}") from exc
            else:
                try:
                    data = yaml.safe_load(text)
                except yaml.YAMLError as exc:
                    raise ProviderError(f"Corrupt project config at {config_path}: {exc}") from exc
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ProviderError(
                f"Project config at {config_path} is not a mapping; refusing to overwrite."
            )
        project = data.setdefault("project", {})
        if isinstance(project, dict):
            project["provider"] = name
        atomic_write_text(config_path, json.dumps(data, indent=2))
