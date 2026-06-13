"""Tests for host_model_resolver — Tasks 4–7."""

from __future__ import annotations

import json
from pathlib import Path

from muscle.host_model_resolver import (
    HostModelResolver,
    canonical_for_host_label,
    default_explicit_host_label,
    default_session_host_label,
    default_settings_host_label,
)

OPUS_KEY = "anthropic/claude-opus-4-8@2026-05-28"
FABLE_KEY = "anthropic/claude-fable-5@2026-06-09"

# ---------------------------------------------------------------------------
# Task 4: canonical_for_host_label + explicit signal + resolver core
# ---------------------------------------------------------------------------


def test_canonical_for_host_label_handles_bare_and_suffixed():
    assert canonical_for_host_label("opus") == OPUS_KEY
    assert canonical_for_host_label("fable") == FABLE_KEY
    assert canonical_for_host_label("opus[1m]") == OPUS_KEY
    assert canonical_for_host_label("claude-opus-4-8") == OPUS_KEY
    assert canonical_for_host_label("mystery") is None


def test_explicit_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    assert default_explicit_host_label(tmp_path) == "opus"


def test_explicit_config_override(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    (muscle_dir / "config.yaml").write_text(json.dumps({"host": {"model": "fable"}}))
    assert default_explicit_host_label(tmp_path) == "fable"


def test_resolver_explicit_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
    resolver = HostModelResolver(session_fn=lambda _p: None, settings_fn=lambda _p: None)
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key == OPUS_KEY
    assert identity.identity_source == "host_explicit"
    assert identity.confidence == 1.0


# ---------------------------------------------------------------------------
# Task 5: settings.json signal
# ---------------------------------------------------------------------------


def test_settings_project_then_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    (project / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    # Project-scoped settings win over home.
    (project / ".claude" / "settings.json").write_text(json.dumps({"model": "opus"}))
    (home / ".claude" / "settings.json").write_text(json.dumps({"model": "fable"}))
    assert default_settings_host_label(project) == "opus"


def test_settings_falls_back_to_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    (home / ".claude").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".claude" / "settings.json").write_text(json.dumps({"model": "fable"}))
    assert default_settings_host_label(project) == "fable"


def test_settings_absent_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    assert default_settings_host_label(tmp_path / "no-proj") is None


def test_explicit_config_malformed_json(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    (muscle_dir / "config.yaml").write_text("{not valid json")
    assert default_explicit_host_label(tmp_path) is None  # must not raise


def test_settings_malformed_json(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("not-json")
    assert default_settings_host_label(tmp_path) is None  # must not raise


# ---------------------------------------------------------------------------
# Task 6: imported-session evidence signal
# ---------------------------------------------------------------------------


class _FakeMemory:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def list_external_benchmark_turns(
        self,
        project_path: object,
        provider: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, object]]:
        # NOTE: production default_session_host_label does NOT pass provider= to
        # this method; provider filtering is done client-side in the resolver.
        # The provider= parameter here is signature-compatibility only.
        rows = self._rows
        if provider:
            rows = [r for r in rows if r.get("provider") == provider]
        return rows[:limit]


def test_session_evidence_takes_most_recent_model():
    # Rows are ASC by id; the most recent host turn is last.
    rows: list[dict[str, object]] = [
        {"id": 1, "provider": "claude", "model": "claude-fable-5"},
        {"id": 2, "provider": "claude", "model": "claude-opus-4-8"},
    ]
    label = default_session_host_label(Path("/proj"), memory=_FakeMemory(rows))
    assert label == "claude-opus-4-8"


def test_session_evidence_ignores_non_host_providers():
    rows: list[dict[str, object]] = [{"id": 3, "provider": "minimax", "model": "MiniMax-M3"}]
    assert default_session_host_label(Path("/proj"), memory=_FakeMemory(rows)) is None


def test_session_evidence_empty_returns_none():
    assert default_session_host_label(Path("/proj"), memory=_FakeMemory([])) is None


def test_session_evidence_none_project_returns_none():
    assert default_session_host_label(None) is None


# ---------------------------------------------------------------------------
# Task 7: full-precedence characterization
# ---------------------------------------------------------------------------


def test_precedence_session_beats_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
    resolver = HostModelResolver(
        explicit_fn=lambda _p: None,
        session_fn=lambda _p: "claude-opus-4-8",
        settings_fn=lambda _p: "fable",
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key == OPUS_KEY
    assert identity.identity_source == "host_session_evidence"
    assert identity.confidence == 0.8


def test_precedence_settings_used_when_higher_absent(tmp_path):
    resolver = HostModelResolver(
        explicit_fn=lambda _p: None,
        session_fn=lambda _p: None,
        settings_fn=lambda _p: "fable",
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key == FABLE_KEY
    assert identity.identity_source == "host_settings"


def test_unresolved_when_all_signals_silent(tmp_path):
    resolver = HostModelResolver(
        explicit_fn=lambda _p: None,
        session_fn=lambda _p: None,
        settings_fn=lambda _p: None,
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key is None
    assert identity.identity_source == "host_unresolved"
    assert identity.confidence == 0.0


def test_uncanonicalizable_label_halves_confidence(tmp_path):
    resolver = HostModelResolver(
        explicit_fn=lambda _p: "some-unknown-host",
        session_fn=lambda _p: None,
        settings_fn=lambda _p: None,
    )
    identity = resolver.resolve(tmp_path)
    assert identity.canonical_model_key is None
    assert identity.requested_label == "some-unknown-host"
    assert identity.confidence == 0.5
