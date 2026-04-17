"""
Model identity resolution for MUSCLE.

Architecture Decision Record (ADR):
- Treat configured labels as hints, not truth
- Prefer explicit manual override when endpoint provenance is ambiguous
- Keep resolution explainable and conservative for Anthropic-compatible endpoints
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .project_memory_types import ModelIdentity
from .system_db import SystemDatabase

logger = logging.getLogger(__name__)

TRUSTED_ENDPOINTS = {
    "api.minimax.io": "minimax",
    "api.minimaxi.com": "minimax",
    "api.anthropic.com": "anthropic",
    "api.openai.com": "openai",
    "generativelanguage.googleapis.com": "google",
}

HEURISTIC_ALIAS_MAP = {
    "minimax-m2.7": "minimax/m2.7@1",
    "minimax m2.7": "minimax/m2.7@1",
    "m2.7": "minimax/m2.7@1",
    "claude-sonnet-4": "anthropic/claude-sonnet@4",
    "claude 4 sonnet": "anthropic/claude-sonnet@4",
    "claude-3-7-sonnet": "anthropic/claude-sonnet@3.7",
    "gpt-5": "openai/gpt-5@1",
    "gpt-5-mini": "openai/gpt-5-mini@1",
    "gemini-2.5-pro": "google/gemini-pro@2.5",
    "gemini-2.5-flash": "google/gemini-flash@2.5",
}

SUPPORTED_CANONICAL_MODELS = sorted(
    {
        "minimax/m2.7@1",
        "anthropic/claude-sonnet@4",
        "anthropic/claude-sonnet@3.7",
        "openai/gpt-5@1",
        "openai/gpt-5-mini@1",
        "google/gemini-pro@2.5",
        "google/gemini-flash@2.5",
    }
)

INTROSPECTION_MODEL_PATTERNS: dict[str, tuple[tuple[str, str], ...]] = {
    "minimax": (
        ("minimax-m2.7", "minimax/m2.7@1"),
        ("m2.7", "minimax/m2.7@1"),
    ),
    "anthropic": (
        ("claude-sonnet-4", "anthropic/claude-sonnet@4"),
        ("claude-4-sonnet", "anthropic/claude-sonnet@4"),
        ("claude-3-7-sonnet", "anthropic/claude-sonnet@3.7"),
    ),
    "openai": (
        ("gpt-5-mini", "openai/gpt-5-mini@1"),
        ("gpt-5", "openai/gpt-5@1"),
    ),
    "google": (
        ("models/gemini-2.5-pro", "google/gemini-pro@2.5"),
        ("gemini-2.5-pro", "google/gemini-pro@2.5"),
        ("models/gemini-2.5-flash", "google/gemini-flash@2.5"),
        ("gemini-2.5-flash", "google/gemini-flash@2.5"),
    ),
}


def endpoint_fingerprint(endpoint: str | None) -> str | None:
    """Normalize a provider endpoint into a host/path fingerprint."""
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if not host:
        return None
    return f"{host}{path}"


def _provider_owner(provider_endpoint: str | None) -> tuple[str | None, str | None]:
    """Return the trusted provider owner and fingerprint for an endpoint."""
    fingerprint = endpoint_fingerprint(provider_endpoint)
    if not fingerprint:
        return None, None
    host = fingerprint.split("/", 1)[0]
    return TRUSTED_ENDPOINTS.get(host), fingerprint


def _extract_response_model_name(response_payload: Mapping[str, Any] | None) -> str | None:
    """Best-effort extraction of a provider-declared model identifier."""
    if not isinstance(response_payload, Mapping):
        return None
    candidates: list[Any] = [
        response_payload.get("model"),
        response_payload.get("model_name"),
        response_payload.get("response_model"),
    ]
    message = response_payload.get("message")
    if isinstance(message, Mapping):
        candidates.append(message.get("model"))
        candidates.append(message.get("model_name"))
    response = response_payload.get("response")
    if isinstance(response, Mapping):
        candidates.append(response.get("model"))
        candidates.append(response.get("model_name"))
    metadata = response_payload.get("metadata")
    if isinstance(metadata, Mapping):
        candidates.append(metadata.get("model"))
        candidates.append(metadata.get("model_name"))

    for candidate in candidates:
        if candidate is None:
            continue
        normalized = str(candidate).strip()
        if normalized:
            return normalized
    return None


def _canonical_model_from_introspection(owner: str, response_model_name: str) -> str | None:
    """Map a trusted provider model identifier to a canonical MUSCLE key."""
    normalized = response_model_name.strip().lower()
    for token, canonical_model_key in INTROSPECTION_MODEL_PATTERNS.get(owner, ()):
        if token in normalized:
            return canonical_model_key
    return None


def introspect_provider_response_identity(
    requested_label: str | None,
    provider_endpoint: str | None,
    response_payload: Mapping[str, Any] | None,
    *,
    manual_override: bool = False,
) -> ModelIdentity | None:
    """Resolve model identity from trusted provider response evidence."""
    if manual_override:
        return None

    owner, fingerprint = _provider_owner(provider_endpoint)
    if owner is None or fingerprint is None:
        return None

    response_model_name = _extract_response_model_name(response_payload)
    if response_model_name is None:
        return None

    canonical_model_key = _canonical_model_from_introspection(owner, response_model_name)
    if canonical_model_key is None:
        return None

    return ModelIdentity(
        requested_label=requested_label,
        provider_endpoint=provider_endpoint,
        provider_fingerprint=fingerprint,
        canonical_model_key=canonical_model_key,
        identity_source="provider_introspection",
        confidence=0.98,
        manual_override=False,
        metadata={
            "provider_owner": owner,
            "response_model_name": response_model_name,
        },
    )


@dataclass
class ModelIdentityResolver:
    """Resolve a requested model label into a canonical model identity."""

    system_db: SystemDatabase

    def resolve(
        self,
        requested_label: str | None,
        provider_endpoint: str | None,
        manual_override: str | None = None,
    ) -> ModelIdentity:
        """Resolve the effective model identity using a conservative precedence order."""
        fingerprint = endpoint_fingerprint(provider_endpoint)

        if manual_override:
            return ModelIdentity(
                requested_label=requested_label,
                provider_endpoint=provider_endpoint,
                provider_fingerprint=fingerprint,
                canonical_model_key=manual_override,
                identity_source="manual_override",
                confidence=1.0,
                manual_override=True,
            )

        trusted_identity = self._resolve_trusted_first_party(requested_label, provider_endpoint)
        if trusted_identity is not None:
            return trusted_identity

        alias_match = self.system_db.resolve_alias(requested_label, fingerprint)
        if alias_match is not None:
            alias_match.provider_endpoint = provider_endpoint
            alias_match.provider_fingerprint = fingerprint
            alias_match.identity_source = "verified_alias"
            return alias_match

        heuristic = self._resolve_heuristic(requested_label, provider_endpoint)
        if heuristic is not None:
            return heuristic

        return ModelIdentity(
            requested_label=requested_label,
            provider_endpoint=provider_endpoint,
            provider_fingerprint=fingerprint,
            canonical_model_key=None,
            identity_source="unresolved",
            confidence=0.0,
            manual_override=False,
        )

    def introspect_response(
        self,
        requested_label: str | None,
        provider_endpoint: str | None,
        response_payload: Mapping[str, Any] | None,
        manual_override: bool = False,
    ) -> ModelIdentity | None:
        """Resolve model identity from trusted provider response evidence."""
        return introspect_provider_response_identity(
            requested_label=requested_label,
            provider_endpoint=provider_endpoint,
            response_payload=response_payload,
            manual_override=manual_override,
        )

    def _resolve_trusted_first_party(
        self,
        requested_label: str | None,
        provider_endpoint: str | None,
    ) -> ModelIdentity | None:
        owner, fingerprint = _provider_owner(provider_endpoint)
        if owner is None or fingerprint is None:
            return None
        normalized = (requested_label or "").strip().lower()

        if owner == "minimax" and any(token in normalized for token in ("minimax", "m2.7")):
            return ModelIdentity(
                requested_label=requested_label,
                provider_endpoint=provider_endpoint,
                provider_fingerprint=fingerprint,
                canonical_model_key="minimax/m2.7@1",
                identity_source="provider_endpoint",
                confidence=0.95,
            )

        if owner in {"anthropic", "openai", "google"} and normalized:
            canonical_key = HEURISTIC_ALIAS_MAP.get(normalized)
            if canonical_key and canonical_key.startswith(owner):
                return ModelIdentity(
                    requested_label=requested_label,
                    provider_endpoint=provider_endpoint,
                    provider_fingerprint=fingerprint,
                    canonical_model_key=canonical_key,
                    identity_source="provider_endpoint",
                    confidence=0.9,
                )
        return None

    def _resolve_heuristic(
        self,
        requested_label: str | None,
        provider_endpoint: str | None,
    ) -> ModelIdentity | None:
        normalized = (requested_label or "").strip().lower()
        if not normalized:
            return None

        fingerprint = endpoint_fingerprint(provider_endpoint)
        host = fingerprint.split("/", 1)[0] if fingerprint else None
        is_untrusted_anthropic_compat = bool(
            fingerprint
            and host not in TRUSTED_ENDPOINTS
            and (
                "anthropic" in fingerprint
                or normalized.startswith("claude")
                or "anthropic" in normalized
            )
        )
        if is_untrusted_anthropic_compat:
            return None

        canonical_key = HEURISTIC_ALIAS_MAP.get(normalized)
        if canonical_key is None:
            return None
        return ModelIdentity(
            requested_label=requested_label,
            provider_endpoint=provider_endpoint,
            provider_fingerprint=fingerprint,
            canonical_model_key=canonical_key,
            identity_source="label_heuristic",
            confidence=0.6,
        )
