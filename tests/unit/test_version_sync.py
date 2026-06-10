"""Guard against version desync across the authoritative pyproject and the
literal JSON manifests consumed by external tooling.

The plugin/marketplace manifests must stay literal JSON (external tools parse
them), so they cannot read the version dynamically. This test fails CI if a
version bump in pyproject is not mirrored into every manifest that carries a
version, and vice versa.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:  # tomllib is stdlib on 3.11+; fall back to tomli on 3.10.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]

# Manifests that carry a top-level "version" field.
TOP_LEVEL_VERSION_MANIFESTS = [
    REPO_ROOT / "src" / "muscle" / "plugin" / ".claude-plugin" / "plugin.json",
    REPO_ROOT / "src" / "muscle" / "plugin" / ".codex-plugin" / "plugin.json",
]

# Marketplace manifests that carry the version under plugins[] (name == "muscle").
MARKETPLACE_MANIFESTS = [
    REPO_ROOT / "src" / "muscle" / "plugin" / ".claude-plugin" / "marketplace.json",
    REPO_ROOT / ".claude-plugin" / "marketplace.json",
]


def _pyproject_version() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)
    return str(data["project"]["version"])


def test_pyproject_has_version() -> None:
    assert _pyproject_version()


@pytest.mark.parametrize(
    "manifest", TOP_LEVEL_VERSION_MANIFESTS, ids=lambda p: p.name + ":" + p.parent.name
)
def test_plugin_manifest_version_matches_pyproject(manifest: Path) -> None:
    assert manifest.exists(), f"missing manifest: {manifest}"
    data = json.loads(manifest.read_text())
    assert data.get("version") == _pyproject_version(), (
        f"{manifest} version {data.get('version')!r} != pyproject {_pyproject_version()!r}"
    )


@pytest.mark.parametrize(
    "manifest", MARKETPLACE_MANIFESTS, ids=lambda p: p.parent.name + "/" + p.name
)
def test_marketplace_muscle_plugin_version_matches_pyproject(manifest: Path) -> None:
    assert manifest.exists(), f"missing manifest: {manifest}"
    data = json.loads(manifest.read_text())
    entries = [p for p in data.get("plugins", []) if p.get("name") == "muscle"]
    assert entries, f"{manifest} has no 'muscle' plugin entry"
    versioned = [p for p in entries if "version" in p]
    # Removing the version field entirely is itself a desync: the guard must
    # fail loudly rather than silently pass.
    assert versioned, f"{manifest} 'muscle' entry lost its version field"
    for entry in versioned:
        assert entry["version"] == _pyproject_version(), (
            f"{manifest} plugin 'muscle' version {entry['version']!r} != "
            f"pyproject {_pyproject_version()!r}"
        )
