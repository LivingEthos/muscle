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
