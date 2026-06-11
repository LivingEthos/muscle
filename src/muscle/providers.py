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

import yaml

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
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError):
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
    """Persist the provider choice in <project>/.muscle/config.yaml (atomic, merged)."""
    from .io_safety import update_json_file_locked

    _require(name, "set_project_provider")
    config_path = Path(project_path) / ".muscle" / "config.yaml"
    if not config_path.exists():
        raise ProviderError(f"No .muscle/config.yaml at {project_path} — run `muscle init` first.")

    def _update(data: dict[str, object]) -> dict[str, object]:
        project = data.setdefault("project", {})
        if isinstance(project, dict):
            project["provider"] = name
        return data

    update_json_file_locked(config_path, _update, default_factory=dict)
