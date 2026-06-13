"""Focused tests for model identity resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from muscle.model_identity import (
    SUPPORTED_CANONICAL_MODELS,
    ModelIdentityResolver,
    canonical_for_label,
)
from muscle.system_db import SystemDatabase

OPUS_KEY = "anthropic/claude-opus-4-8@2026-05-28"


@pytest.fixture
def isolated_system_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "home" / ".muscle" / "system.db"
    monkeypatch.setattr("muscle.system_db.DEFAULT_SYSTEM_DB_PATH", db_path)
    return db_path


def test_fable_alias_resolves_to_canonical_key_on_anthropic_endpoint(
    isolated_system_db: Path,
) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())

    identity = resolver.resolve(
        requested_label="fable 5",
        provider_endpoint="https://api.anthropic.com/v1/messages",
    )

    assert identity.canonical_model_key == "anthropic/claude-fable-5@2026-06-09"
    assert identity.identity_source == "provider_endpoint"
    assert "anthropic/claude-fable-5@2026-06-09" in SUPPORTED_CANONICAL_MODELS


def test_openrouter_label_is_gateway_scoped_not_first_party(
    isolated_system_db: Path,
) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())

    identity = resolver.resolve(
        requested_label="openai/gpt-5",
        provider_endpoint="https://openrouter.ai/api/v1",
    )

    assert identity.canonical_model_key is None
    assert identity.identity_source == "gateway_label"
    assert identity.confidence < 0.5
    assert identity.metadata["gateway_provider"] == "openrouter-api"
    assert identity.metadata["requested_model"] == "openai/gpt-5"


def test_gpt_55_alias_resolves_to_openai_canonical_key(
    isolated_system_db: Path,
) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())

    identity = resolver.resolve(
        requested_label="gpt-5.5",
        provider_endpoint="https://api.openai.com/v1",
    )

    assert identity.canonical_model_key == "openai/gpt-5.5@1"
    assert identity.identity_source == "provider_endpoint"
    assert "openai/gpt-5.5@1" in SUPPORTED_CANONICAL_MODELS


def test_gpt_55_provider_response_introspects_to_openai_canonical_key(
    isolated_system_db: Path,
) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())

    identity = resolver.introspect_response(
        requested_label="gpt-5.5",
        provider_endpoint="https://api.openai.com/v1",
        response_payload={"model": "gpt-5.5"},
    )

    assert identity is not None
    assert identity.canonical_model_key == "openai/gpt-5.5@1"


def test_openrouter_gateway_response_does_not_become_provider_introspection(
    isolated_system_db: Path,
) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())

    identity = resolver.introspect_response(
        requested_label="anthropic/claude-sonnet-4",
        provider_endpoint="https://openrouter.ai/api/v1",
        response_payload={"model": "anthropic/claude-sonnet-4"},
    )

    assert identity is None


def test_canonical_for_label_resolves_opus_aliases():
    assert canonical_for_label("claude-opus-4-8") == OPUS_KEY
    assert canonical_for_label("Opus 4.8") == OPUS_KEY
    assert canonical_for_label("opus-4-8") == OPUS_KEY


def test_canonical_for_label_resolves_existing_models():
    assert canonical_for_label("MiniMax-M3") == "minimax/m3@1"
    assert canonical_for_label("claude-fable-5") == "anthropic/claude-fable-5@2026-06-09"


def test_canonical_for_label_unknown_returns_none():
    assert canonical_for_label("totally-unknown-model") is None
    assert canonical_for_label(None) is None


def test_opus_key_is_supported():
    assert OPUS_KEY in SUPPORTED_CANONICAL_MODELS
