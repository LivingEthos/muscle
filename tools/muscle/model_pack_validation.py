"""
Shared validation and compatibility helpers for MUSCLE model packs.

Architecture Decision Record (ADR):
- Keep model-pack validation rules centralized across install, update, and use
- Reject incompatible or underspecified packs before they can affect runtime
- Treat safety scope and portability as enforceable contract fields
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model_pack_standard import (
    PACK_LESSONS_SCHEMA_VERSION,
    PACK_MANIFEST_SCHEMA_VERSION,
    PACK_REPO_LAYOUT_VERSION,
    canonical_model_repository_path,
)
from .project_memory_types import ModelPackLesson, ModelPackMetadata

ALLOWED_MODEL_PACK_SAFETY_SCOPES = frozenset(
    {
        "review-only",
        "review-and-fix",
        "all-stages",
    }
)
ALLOWED_MODEL_PACK_PORTABILITY = frozenset({"portable"})
ALLOWED_MODEL_PACK_INSTALL_STATUSES = frozenset({"installed", "disabled", "exported"})
SUPPORTED_MODEL_PACK_MANIFEST_SCHEMA_VERSIONS = frozenset({PACK_MANIFEST_SCHEMA_VERSION})
SUPPORTED_MODEL_PACK_LESSONS_SCHEMA_VERSIONS = frozenset({PACK_LESSONS_SCHEMA_VERSION})
SUPPORTED_MODEL_PACK_LAYOUT_VERSIONS = frozenset({PACK_REPO_LAYOUT_VERSION})

SAFETY_SCOPE_STAGE_ALLOWLIST: dict[str, frozenset[str]] = {
    "review-only": frozenset({"semantic_review"}),
    "review-and-fix": frozenset({"semantic_review", "fix_generation", "handoff"}),
    "all-stages": frozenset(),
}


@dataclass(frozen=True)
class CanonicalModelKeyParts:
    vendor: str
    family: str
    version: str

    @property
    def family_key(self) -> str:
        return f"{self.vendor}/{self.family}"


def parse_canonical_model_key(canonical_model_key: str) -> CanonicalModelKeyParts:
    """Parse and validate a canonical MUSCLE model key."""
    normalized = canonical_model_key.strip()
    if not normalized or "/" not in normalized or "@" not in normalized:
        msg = f"Invalid canonical model key: {canonical_model_key!r}"
        raise ValueError(msg)

    vendor, family_and_version = normalized.split("/", 1)
    family, version = family_and_version.rsplit("@", 1)
    if not vendor or not family or not version:
        msg = f"Invalid canonical model key: {canonical_model_key!r}"
        raise ValueError(msg)
    return CanonicalModelKeyParts(vendor=vendor, family=family, version=version)


def compatibility_error(
    expected_canonical_model_key: str | None,
    candidate_canonical_model_key: str,
) -> str | None:
    """Return a helpful incompatibility reason, or None when compatible."""
    if not expected_canonical_model_key:
        return None

    expected = parse_canonical_model_key(expected_canonical_model_key)
    candidate = parse_canonical_model_key(candidate_canonical_model_key)
    if expected.family_key != candidate.family_key:
        return (
            f"Pack {candidate_canonical_model_key} is incompatible with current model family "
            f"{expected_canonical_model_key}"
        )
    if expected.version != candidate.version:
        return (
            f"Pack {candidate_canonical_model_key} is incompatible with current model version "
            f"{expected_canonical_model_key}"
        )
    return None


def stage_allows_model_pack_scope(stage: str, safety_scope: str) -> bool:
    """Return whether one lesson safety scope is valid for the current stage."""
    allowed_stages = SAFETY_SCOPE_STAGE_ALLOWLIST.get(safety_scope)
    if allowed_stages is None:
        return False
    if not allowed_stages:
        return True
    return stage in allowed_stages


def _normalize_version_field(
    value: Any,
    *,
    field_name: str,
    default: str,
    supported: frozenset[str],
) -> str:
    normalized = str(value or default).strip()
    if not normalized:
        raise ValueError(f"Model-pack {field_name} is missing.")
    if normalized not in supported:
        raise ValueError(f"Unsupported model-pack {field_name}: {normalized}")
    return normalized


def validate_model_pack_manifest(
    manifest: dict[str, Any],
    *,
    expected_canonical_model_key: str | None = None,
) -> dict[str, Any]:
    """Validate pack manifest structure and compatibility."""
    canonical_model_key = str(manifest.get("canonical_model_key") or "").strip()
    parse_canonical_model_key(canonical_model_key)
    schema_version = _normalize_version_field(
        manifest.get("schema_version"),
        field_name="manifest schema_version",
        default=PACK_MANIFEST_SCHEMA_VERSION,
        supported=SUPPORTED_MODEL_PACK_MANIFEST_SCHEMA_VERSIONS,
    )
    repository_layout_version = _normalize_version_field(
        manifest.get("repository_layout_version"),
        field_name="repository_layout_version",
        default=PACK_REPO_LAYOUT_VERSION,
        supported=SUPPORTED_MODEL_PACK_LAYOUT_VERSIONS,
    )
    lessons_schema_version = _normalize_version_field(
        manifest.get("lessons_schema_version"),
        field_name="lessons_schema_version",
        default=PACK_LESSONS_SCHEMA_VERSION,
        supported=SUPPORTED_MODEL_PACK_LESSONS_SCHEMA_VERSIONS,
    )
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise ValueError("Model-pack manifest is missing a version.")
    expected_repository_path = canonical_model_repository_path(canonical_model_key)
    repository_path = str(manifest.get("repository_path") or expected_repository_path).strip()
    if repository_path != expected_repository_path:
        raise ValueError(
            "Model-pack manifest repository_path must match the canonical repository path "
            f"{expected_repository_path}"
        )

    aliases = manifest.get("supported_aliases", [])
    if aliases is None:
        aliases = []
    if not isinstance(aliases, list):
        raise ValueError("Model-pack manifest supported_aliases must be a list.")
    normalized_aliases: list[str] = []
    for alias in aliases:
        normalized_alias = str(alias).strip()
        if not normalized_alias:
            raise ValueError("Model-pack manifest contains an empty supported alias.")
        normalized_aliases.append(normalized_alias)

    incompatibility = compatibility_error(expected_canonical_model_key, canonical_model_key)
    if incompatibility is not None:
        raise ValueError(incompatibility)

    normalized_manifest = dict(manifest)
    normalized_manifest["schema_version"] = schema_version
    normalized_manifest["repository_layout_version"] = repository_layout_version
    normalized_manifest["repository_path"] = repository_path
    normalized_manifest["canonical_model_key"] = canonical_model_key
    normalized_manifest["lessons_schema_version"] = lessons_schema_version
    normalized_manifest["version"] = version
    normalized_manifest["supported_aliases"] = sorted(set(normalized_aliases))
    return normalized_manifest


def validate_model_pack_metadata(metadata: ModelPackMetadata) -> None:
    """Validate metadata before persisting an installed pack."""
    parse_canonical_model_key(metadata.canonical_model_key)
    if not str(metadata.version or "").strip():
        raise ValueError("Model-pack metadata requires a version.")
    if metadata.install_status not in ALLOWED_MODEL_PACK_INSTALL_STATUSES:
        raise ValueError(f"Unsupported model-pack install status: {metadata.install_status}")


def _normalize_scope_tags(scope_tags: Any) -> list[str]:
    if not isinstance(scope_tags, list):
        raise ValueError("Model-pack lesson scope_tags must be a list.")
    normalized_scope_tags = sorted(
        {str(tag).strip().lower() for tag in scope_tags if str(tag).strip()}
    )
    if not normalized_scope_tags:
        raise ValueError("Model-pack lessons require at least one non-empty scope tag.")
    return normalized_scope_tags


def validate_model_pack_lesson(
    lesson: ModelPackLesson,
    *,
    expected_canonical_model_key: str,
) -> ModelPackLesson:
    """Validate and normalize one model-pack lesson."""
    if lesson.canonical_model_key != expected_canonical_model_key:
        raise ValueError(
            "Model-pack lesson canonical model key does not match manifest canonical model key."
        )
    if not str(lesson.lesson_key or "").strip():
        raise ValueError("Model-pack lessons require a non-empty lesson_key.")
    if not str(lesson.lesson_text or "").strip():
        raise ValueError("Model-pack lessons require non-empty lesson_text.")

    normalized_scope_tags = _normalize_scope_tags(list(lesson.scope_tags))
    safety_scope = str(lesson.safety_scope or "").strip().lower()
    if safety_scope not in ALLOWED_MODEL_PACK_SAFETY_SCOPES:
        raise ValueError(f"Unsupported model-pack safety scope: {lesson.safety_scope}")
    portability = str(lesson.portability or "").strip().lower()
    if portability not in ALLOWED_MODEL_PACK_PORTABILITY:
        raise ValueError(f"Unsupported model-pack portability: {lesson.portability}")
    if not isinstance(lesson.evidence, dict):
        raise ValueError("Model-pack lessons require evidence to be a dictionary.")

    return ModelPackLesson(
        canonical_model_key=lesson.canonical_model_key,
        lesson_key=str(lesson.lesson_key).strip(),
        lesson_text=str(lesson.lesson_text).strip(),
        scope_tags=normalized_scope_tags,
        safety_scope=safety_scope,
        portability=portability,
        evidence=lesson.evidence,
        rationale=lesson.rationale,
        source_repo_commit=lesson.source_repo_commit,
    )


def lesson_from_bundle_item(
    item: dict[str, Any],
    *,
    expected_canonical_model_key: str,
) -> ModelPackLesson:
    """Build and validate one lesson from a bundle payload item."""
    lesson = ModelPackLesson(
        canonical_model_key=str(item.get("canonical_model_key") or "").strip(),
        lesson_key=str(item.get("lesson_key") or "").strip(),
        lesson_text=str(item.get("lesson_text") or "").strip(),
        scope_tags=item.get("scope_tags", []),
        safety_scope=str(item.get("safety_scope", "review-only")),
        portability=str(item.get("portability", "portable")),
        evidence=item.get("evidence", {}),
        rationale=item.get("rationale"),
        source_repo_commit=item.get("source_repo_commit"),
    )
    return validate_model_pack_lesson(
        lesson,
        expected_canonical_model_key=expected_canonical_model_key,
    )


def normalize_model_pack_lessons_payload(
    payload: Any,
    *,
    expected_canonical_model_key: str,
) -> dict[str, Any]:
    """Validate and normalize a lessons bundle payload."""
    if isinstance(payload, list):
        return {
            "schema_version": PACK_LESSONS_SCHEMA_VERSION,
            "canonical_model_key": expected_canonical_model_key,
            "lesson_count": len(payload),
            "lessons": payload,
        }
    if not isinstance(payload, dict):
        raise ValueError("Model-pack lessons payload must be an object or a legacy list.")

    schema_version = _normalize_version_field(
        payload.get("schema_version"),
        field_name="lessons schema_version",
        default=PACK_LESSONS_SCHEMA_VERSION,
        supported=SUPPORTED_MODEL_PACK_LESSONS_SCHEMA_VERSIONS,
    )
    canonical_model_key = str(
        payload.get("canonical_model_key") or expected_canonical_model_key
    ).strip()
    if canonical_model_key != expected_canonical_model_key:
        raise ValueError(
            "Model-pack lessons canonical model key does not match the manifest canonical "
            "model key."
        )
    lessons = payload.get("lessons", [])
    if not isinstance(lessons, list):
        raise ValueError("Model-pack lessons payload 'lessons' must be a list.")
    declared_lesson_count = payload.get("lesson_count", len(lessons))
    try:
        normalized_lesson_count = int(declared_lesson_count)
    except (TypeError, ValueError) as exc:
        raise ValueError("Model-pack lessons payload lesson_count must be an integer.") from exc
    if normalized_lesson_count != len(lessons):
        raise ValueError("Model-pack lessons payload lesson_count does not match lessons length.")
    return {
        "schema_version": schema_version,
        "canonical_model_key": canonical_model_key,
        "lesson_count": normalized_lesson_count,
        "lessons": lessons,
    }
