"""
Shared MUSCLE model-pack repository standard.

Architecture Decision Record (ADR):
- Keep one explicit repository contract for exported bundles and community PRs
- Version manifest and lessons payload schemas independently
- Make the public repo scaffold reproducible from MUSCLE itself
"""

from __future__ import annotations

import json
from typing import Any

PACK_REPO_ROOT = "packs"
PACK_REPO_LAYOUT_VERSION = "1.0"
PACK_MANIFEST_SCHEMA_VERSION = "1.0"
PACK_LESSONS_SCHEMA_VERSION = "1.0"


def canonical_model_repository_path(canonical_model_key: str) -> str:
    """Return the canonical path for one model pack inside the public repo."""
    return f"{PACK_REPO_ROOT}/{canonical_model_key.strip()}"


def repository_relative_paths(canonical_model_key: str) -> dict[str, str]:
    """Return the standard relative paths for one canonical model pack."""
    prefix = canonical_model_repository_path(canonical_model_key)
    return {
        "prefix": prefix,
        "manifest": f"{prefix}/pack.json",
        "lessons": f"{prefix}/lessons.json",
    }


def build_lessons_payload(
    canonical_model_key: str,
    lessons: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the standard lessons payload envelope."""
    return {
        "schema_version": PACK_LESSONS_SCHEMA_VERSION,
        "canonical_model_key": canonical_model_key,
        "lesson_count": len(lessons),
        "lessons": lessons,
    }


def _pack_repository_descriptor() -> dict[str, Any]:
    return {
        "repository_layout_version": PACK_REPO_LAYOUT_VERSION,
        "pack_root": PACK_REPO_ROOT,
        "pack_manifest_schema_version": PACK_MANIFEST_SCHEMA_VERSION,
        "lessons_schema_version": PACK_LESSONS_SCHEMA_VERSION,
    }


def _pack_manifest_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "MUSCLE Model Pack Manifest",
        "type": "object",
        "required": [
            "schema_version",
            "repository_layout_version",
            "repository_path",
            "canonical_model_key",
            "lessons_schema_version",
            "version",
            "supported_aliases",
        ],
        "properties": {
            "schema_version": {"const": PACK_MANIFEST_SCHEMA_VERSION},
            "repository_layout_version": {"const": PACK_REPO_LAYOUT_VERSION},
            "repository_path": {"type": "string", "minLength": 1},
            "canonical_model_key": {"type": "string", "minLength": 1},
            "lessons_schema_version": {"const": PACK_LESSONS_SCHEMA_VERSION},
            "version": {"type": "string", "minLength": 1},
            "supported_aliases": {"type": "array", "items": {"type": "string"}},
            "export_id": {"type": "string"},
            "generated_at": {"type": "string"},
            "lesson_count": {"type": "integer", "minimum": 0},
            "rejected_lesson_count": {"type": "integer", "minimum": 0},
            "scrubber_version": {"type": "string"},
            "source_project": {"type": "string"},
            "source_repo": {"type": "string"},
            "source_repo_commit": {"type": "string"},
        },
        "additionalProperties": True,
    }


def _lessons_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "MUSCLE Model Pack Lessons",
        "type": "object",
        "required": ["schema_version", "canonical_model_key", "lesson_count", "lessons"],
        "properties": {
            "schema_version": {"const": PACK_LESSONS_SCHEMA_VERSION},
            "canonical_model_key": {"type": "string", "minLength": 1},
            "lesson_count": {"type": "integer", "minimum": 0},
            "lessons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "canonical_model_key",
                        "lesson_key",
                        "lesson_text",
                        "scope_tags",
                        "safety_scope",
                        "portability",
                        "evidence",
                    ],
                    "properties": {
                        "canonical_model_key": {"type": "string", "minLength": 1},
                        "lesson_key": {"type": "string", "minLength": 1},
                        "lesson_text": {"type": "string", "minLength": 1},
                        "scope_tags": {"type": "array", "items": {"type": "string"}},
                        "safety_scope": {"type": "string", "minLength": 1},
                        "portability": {"type": "string", "minLength": 1},
                        "evidence": {"type": "object"},
                        "rationale": {"type": ["string", "null"]},
                        "source_repo_commit": {"type": ["string", "null"]},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": False,
    }


def repository_scaffold_files() -> dict[str, str]:
    """Return the standard file set for the public model-pack repository."""
    descriptor = json.dumps(_pack_repository_descriptor(), indent=2, sort_keys=True) + "\n"
    pack_schema = json.dumps(_pack_manifest_schema(), indent=2, sort_keys=True) + "\n"
    lessons_schema = json.dumps(_lessons_schema(), indent=2, sort_keys=True) + "\n"
    return {
        "README.md": (
            "# MUSCLE Model Packs\n\n"
            "This repository stores curated, model-specific MUSCLE packs in a "
            "single public layout.\n\n"
            "## Layout\n\n"
            f"- Pack root: `{PACK_REPO_ROOT}/<canonical-model-key>/`\n"
            f"- Layout version: `{PACK_REPO_LAYOUT_VERSION}`\n"
            f"- `pack.json` schema: `{PACK_MANIFEST_SCHEMA_VERSION}`\n"
            f"- `lessons.json` schema: `{PACK_LESSONS_SCHEMA_VERSION}`\n\n"
            "Each pack directory contains exactly `pack.json` and "
            "`lessons.json`.\n"
        ),
        "CONTRIBUTING.md": (
            "# Contributing Model Packs\n\n"
            "Submit only portable, model-specific lessons.\n\n"
            "## Rules\n\n"
            "- Keep lessons vendor/model scoped through the canonical model key.\n"
            "- Include scope tags so MUSCLE can apply lessons selectively.\n"
            "- Exclude project-specific paths, secrets, branch names, and repo "
            "identifiers.\n"
            "- Open submissions as draft PRs for human review.\n"
            "- Keep evidence concise and reproducible.\n"
        ),
        "docs/moderation.md": (
            "# Moderation Rules\n\n"
            "Reviewers should reject submissions that:\n\n"
            "- include secrets or project-specific identifiers\n"
            "- lack evidence or applicability tags\n"
            "- target the wrong canonical model family or version\n"
            "- make unsafe claims outside the declared safety scope\n"
            "- duplicate an existing lesson without stronger evidence\n"
        ),
        "packs/README.md": (
            "# Pack Layout\n\n"
            f"Every pack must live under `{PACK_REPO_ROOT}/<canonical-model-key>/`.\n"
            "Example:\n\n"
            "```text\n"
            "packs/\n"
            "  minimax/\n"
            "    m2.7@1/\n"
            "      pack.json\n"
            "      lessons.json\n"
            "```\n"
        ),
        "pack-repository.json": descriptor,
        "schemas/pack.schema.json": pack_schema,
        "schemas/lessons.schema.json": lessons_schema,
    }
