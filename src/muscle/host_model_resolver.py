"""Resolve the host (planner) model that consumes MUSCLE's output.

Claude Code exposes no stable model signal to plugins/hooks, so detection draws
on MUSCLE-side signals, in descending authority:

1. explicit override   — MUSCLE_HOST_MODEL env, then .muscle/config.yaml host.model
2. session evidence     — most recent imported host-session model (Task 6)
3. host settings        — ~/.claude/settings.json then .claude/settings.json "model" (Task 5)
4. unresolved           — caller falls back to the conservative default profile

Mirrors ``ModelIdentityResolver``: every result is a ``ModelIdentity`` carrying a
confidence + source so resolution stays explainable.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .model_identity import canonical_for_label
from .project_memory_types import ModelIdentity

logger = logging.getLogger(__name__)

# Host-context short aliases that settings.json / users commonly use, beyond the
# full labels handled by canonical_for_label.
_HOST_SHORT_ALIASES: dict[str, str] = {
    "opus": "anthropic/claude-opus-4-8@2026-05-28",
    "fable": "anthropic/claude-fable-5@2026-06-09",
    "sonnet": "anthropic/claude-sonnet@4",
}

# Host planners that consume MUSCLE output (excludes the MiniMax executor).
_HOST_SESSION_PROVIDERS = ("claude", "codex")

LabelFn = Callable[[Path | None], str | None]


def canonical_for_host_label(label: str | None) -> str | None:
    """Canonicalize a host label, tolerating bare names and ``[1m]`` suffixes."""
    if not label:
        return None
    normalized = label.strip().lower()
    # Deliberately strict: only a trailing "[1m]" suffix is stripped, not any
    # other bracket annotation, so future additions don't broaden this silently.
    if normalized.endswith("[1m]"):
        normalized = normalized[: -len("[1m]")].strip()
    direct = canonical_for_label(normalized)
    if direct is not None:
        return direct
    return _HOST_SHORT_ALIASES.get(normalized)


def _config_host_model(project_path: Path | None) -> str | None:
    if project_path is None:
        return None
    config_path = Path(project_path) / ".muscle" / "config.yaml"
    if not config_path.exists():
        return None
    try:
        # .muscle/config.yaml holds JSON content (see ProjectManager).
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("host_model_resolver: could not read %s", config_path, exc_info=True)
        return None
    host = data.get("host") if isinstance(data, dict) else None
    value = host.get("model") if isinstance(host, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def default_explicit_host_label(project_path: Path | None) -> str | None:
    """MUSCLE_HOST_MODEL env, then .muscle/config.yaml host.model."""
    env = os.environ.get("MUSCLE_HOST_MODEL")
    if env and env.strip():
        return env.strip()
    return _config_host_model(project_path)


def default_session_host_label(
    project_path: Path | None,
    *,
    memory: Any = None,
) -> str | None:
    """Most-recent host model from imported Claude/Codex sessions, or None.

    ``memory`` is injectable for testing; in production it is a ``ProjectMemory``
    bound to ``project_path``. Turn rows arrive id-ASC, so the most recent host
    turn with a non-empty model is the last match.
    """
    if project_path is None:
        return None
    if memory is None:
        try:
            from .project_memory import ProjectMemory

            memory = ProjectMemory(str(project_path))
        except Exception:
            logger.debug("host_model_resolver: ProjectMemory unavailable", exc_info=True)
            return None
    try:
        turns = memory.list_external_benchmark_turns(str(project_path), limit=200)
    except Exception:
        logger.debug("host_model_resolver: could not list session turns", exc_info=True)
        return None
    for row in reversed(list(turns)):
        if row.get("provider") not in _HOST_SESSION_PROVIDERS:
            continue
        model = row.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
    return None


def _read_settings_model(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("host_model_resolver: could not read %s", path, exc_info=True)
        return None
    value = data.get("model") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def default_settings_host_label(project_path: Path | None) -> str | None:
    """Project ``.claude/settings.json`` model, else ``~/.claude/settings.json``.

    This is the *configured* default and may lag a mid-session ``/model`` switch;
    it sits below explicit override and session evidence in precedence.
    """
    if project_path is not None:
        project_model = _read_settings_model(Path(project_path) / ".claude" / "settings.json")
        if project_model:
            return project_model
    return _read_settings_model(Path.home() / ".claude" / "settings.json")


class HostModelResolver:
    """Resolve the host model from injectable signals (precedence above)."""

    def __init__(
        self,
        *,
        explicit_fn: LabelFn | None = None,
        session_fn: LabelFn | None = None,
        settings_fn: LabelFn | None = None,
    ) -> None:
        self._explicit_fn = explicit_fn or default_explicit_host_label
        self._session_fn = session_fn or default_session_host_label
        self._settings_fn = settings_fn or default_settings_host_label

    def resolve(self, project_path: Path | None = None) -> ModelIdentity:
        signals: list[tuple[LabelFn, str, float]] = [
            (self._explicit_fn, "host_explicit", 1.0),
            (self._session_fn, "host_session_evidence", 0.8),
            (self._settings_fn, "host_settings", 0.5),
        ]
        for fn, source, confidence in signals:
            label = fn(project_path)
            if not label:
                continue
            canonical = canonical_for_host_label(label)
            # A label we cannot canonicalize is weaker evidence than one we can.
            effective = confidence if canonical else confidence * 0.5
            return ModelIdentity(
                requested_label=label,
                provider_endpoint=None,
                provider_fingerprint=None,
                canonical_model_key=canonical,
                identity_source=source,
                confidence=effective,
                metadata={"position": "host"},
            )
        return ModelIdentity(
            requested_label=None,
            provider_endpoint=None,
            provider_fingerprint=None,
            canonical_model_key=None,
            identity_source="host_unresolved",
            confidence=0.0,
            metadata={"position": "host"},
        )
