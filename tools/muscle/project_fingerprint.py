"""
Project fingerprinting and related-project similarity scoring.

Architecture Decision Record (ADR):
- Use lightweight metadata only so normal review/run commands stay cheap
- Prefer explicit manifest parsing over deep codebase traversal
- Keep similarity stable and explainable with fixed weighted overlap
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, cast

try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef, import-not-found]
    except ImportError:  # pragma: no cover
        tomllib = None

from .project_memory_types import ProjectFingerprint

logger = logging.getLogger(__name__)

FRAMEWORK_MARKERS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "pytest": "Pytest",
    "react": "React",
    "next": "Next.js",
    "nextjs": "Next.js",
    "vue": "Vue",
    "nuxt": "Nuxt",
    "svelte": "Svelte",
    "astro": "Astro",
    "express": "Express",
    "nestjs": "NestJS",
    "tailwindcss": "Tailwind",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "click": "Click",
    "typer": "Typer",
    "vite": "Vite",
    "vitest": "Vitest",
    "drizzle-orm": "Drizzle",
    "prisma": "Prisma",
    "tanstack": "TanStack",
    "solid-js": "SolidJS",
    "remix": "Remix",
    "rails": "Rails",
    "sinatra": "Sinatra",
    "laravel": "Laravel",
    "symfony": "Symfony",
}

ARCHETYPE_MARKERS = {
    "tests": "tests",
    "src": "src-layout",
    "app": "app-dir",
    "packages": "monorepo",
    "services": "services",
    "api": "api",
    "infra": "infra",
    "ios": "ios",
    "android": "android",
    "cmd": "cli",
    "bin": "cli",
    "worker": "worker",
    "workers": "workers",
    "functions": "functions",
}

FRAMEWORK_FILE_MARKERS = {
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "next.config.ts": "Next.js",
    "nuxt.config.js": "Nuxt",
    "nuxt.config.ts": "Nuxt",
    "astro.config.js": "Astro",
    "astro.config.mjs": "Astro",
    "astro.config.ts": "Astro",
    "vite.config.js": "Vite",
    "vite.config.ts": "Vite",
    "vitest.config.ts": "Vitest",
    "vitest.config.js": "Vitest",
    "tailwind.config.js": "Tailwind",
    "tailwind.config.ts": "Tailwind",
    "manage.py": "Django",
    "Gemfile": "Rails",
    "composer.json": "Laravel",
}

LANGUAGE_HINTS = {
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "package.json": "JavaScript",
    "tsconfig.json": "TypeScript",
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
}

DEPENDENCY_SPLIT_RE = re.compile(r"[<>=!~ \t\[]")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return cast(dict[str, Any], data)
        return None
    except Exception:
        logger.debug("Failed to parse JSON manifest %s", path, exc_info=True)
        return None


def _normalize_dependency_name(raw_name: str) -> str | None:
    name = DEPENDENCY_SPLIT_RE.split(raw_name.strip(), maxsplit=1)[0].strip()
    if not name or name.startswith("#"):
        return None
    return name.lower()


def _collect_python_dependencies(project_path: Path) -> list[str]:
    deps: set[str] = set()
    pyproject = project_path / "pyproject.toml"
    if pyproject.exists():
        try:
            if tomllib is None:
                return sorted(deps)
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = data.get("project", {})
            for dep in project.get("dependencies", []):
                normalized = _normalize_dependency_name(str(dep))
                if normalized:
                    deps.add(normalized)

            optional = project.get("optional-dependencies", {})
            for values in optional.values():
                for dep in values:
                    normalized = _normalize_dependency_name(str(dep))
                    if normalized:
                        deps.add(normalized)

            poetry = data.get("tool", {}).get("poetry", {})
            for dep_name in poetry.get("dependencies", {}):
                normalized = _normalize_dependency_name(str(dep_name))
                if normalized and normalized != "python":
                    deps.add(normalized)
        except Exception:
            logger.debug("Failed to parse pyproject.toml", exc_info=True)

    requirements = project_path / "requirements.txt"
    if requirements.exists():
        for line in requirements.read_text(encoding="utf-8").splitlines():
            normalized = _normalize_dependency_name(line)
            if normalized:
                deps.add(normalized)
    return sorted(deps)


def _collect_js_dependencies(project_path: Path) -> list[str]:
    package_json = project_path / "package.json"
    if not package_json.exists():
        return []
    data = _load_json(package_json)
    if data is None:
        return []
    deps = (
        set(data.get("dependencies", {}).keys())
        | set(data.get("devDependencies", {}).keys())
        | set(data.get("peerDependencies", {}).keys())
        | set(data.get("optionalDependencies", {}).keys())
    )
    normalized = [_normalize_dependency_name(dep) for dep in deps]
    return sorted(dep for dep in normalized if dep)


def _collect_go_dependencies(project_path: Path) -> list[str]:
    go_mod = project_path / "go.mod"
    if not go_mod.exists():
        return []
    deps: set[str] = set()
    for line in go_mod.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("require ") and len(stripped.split()) >= 2:
            normalized = _normalize_dependency_name(stripped.split()[1])
            if normalized:
                deps.add(normalized)
    return sorted(deps)


def _collect_rust_dependencies(project_path: Path) -> list[str]:
    cargo_toml = project_path / "Cargo.toml"
    if not cargo_toml.exists():
        return []
    deps: set[str] = set()
    current_section = ""
    for line in cargo_toml.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped.strip("[]")
            continue
        if "dependencies" in current_section and "=" in stripped:
            normalized = _normalize_dependency_name(stripped.split("=", 1)[0])
            if normalized:
                deps.add(normalized)
    return sorted(deps)


def _collect_ruby_dependencies(project_path: Path) -> list[str]:
    gemfile = project_path / "Gemfile"
    if not gemfile.exists():
        return []
    deps: set[str] = set()
    for line in gemfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("gem "):
            continue
        parts = stripped.split('"')
        if len(parts) >= 2:
            normalized = _normalize_dependency_name(parts[1])
            if normalized:
                deps.add(normalized)
    return sorted(deps)


def _collect_php_dependencies(project_path: Path) -> list[str]:
    composer = project_path / "composer.json"
    if not composer.exists():
        return []
    data = _load_json(composer)
    if data is None:
        return []
    deps = set(data.get("require", {}).keys()) | set(data.get("require-dev", {}).keys())
    normalized = [_normalize_dependency_name(dep) for dep in deps]
    return sorted(dep for dep in normalized if dep)


def _infer_languages(project_path: Path, provided_languages: list[str] | None) -> list[str]:
    if provided_languages:
        return sorted({language.strip() for language in provided_languages if language.strip()})

    inferred: set[str] = set()
    for filename, language in LANGUAGE_HINTS.items():
        if (project_path / filename).exists():
            inferred.add(language)

    if "JavaScript" in inferred and (project_path / "tsconfig.json").exists():
        inferred.discard("JavaScript")
        inferred.add("TypeScript")

    if not inferred:
        suffixes = {path.suffix.lower() for path in project_path.iterdir() if path.is_file()}
        if ".py" in suffixes:
            inferred.add("Python")
        if ".ts" in suffixes or ".tsx" in suffixes:
            inferred.add("TypeScript")
        elif ".js" in suffixes or ".jsx" in suffixes:
            inferred.add("JavaScript")

    return sorted(inferred)


def explain_relatedness(
    current: ProjectFingerprint, candidate: ProjectFingerprint
) -> dict[str, Any]:
    """Explain why a candidate project is related to the current project."""
    language_overlap = sorted(set(current.languages) & set(candidate.languages))
    framework_overlap = sorted(set(current.frameworks) & set(candidate.frameworks))
    dependency_overlap = sorted(set(current.dependencies[:15]) & set(candidate.dependencies[:15]))
    archetype_overlap = sorted(set(current.archetypes) & set(candidate.archetypes))

    component_scores = {
        "languages": round(_jaccard(current.languages, candidate.languages), 4),
        "frameworks": round(_jaccard(current.frameworks, candidate.frameworks), 4),
        "dependencies": round(_jaccard(current.dependencies[:15], candidate.dependencies[:15]), 4),
        "archetypes": round(_jaccard(current.archetypes, candidate.archetypes), 4),
    }

    reasons: list[str] = []
    if language_overlap:
        reasons.append(f"languages: {', '.join(language_overlap[:2])}")
    if framework_overlap:
        reasons.append(f"frameworks: {', '.join(framework_overlap[:2])}")
    if dependency_overlap:
        reasons.append(f"deps: {', '.join(dependency_overlap[:3])}")
    if archetype_overlap:
        reasons.append(f"shape: {', '.join(archetype_overlap[:2])}")

    return {
        "score": score_relatedness(current, candidate),
        "component_scores": component_scores,
        "overlap": {
            "languages": language_overlap,
            "frameworks": framework_overlap,
            "dependencies": dependency_overlap,
            "archetypes": archetype_overlap,
        },
        "shared_total": sum(
            len(items)
            for items in (
                language_overlap,
                framework_overlap,
                dependency_overlap,
                archetype_overlap,
            )
        ),
        "summary": "; ".join(reasons) if reasons else "shared project shape only",
    }


def build_project_fingerprint(
    project_path: Path,
    display_name: str | None = None,
    languages: list[str] | None = None,
) -> ProjectFingerprint:
    """Build a lightweight project fingerprint from manifests and directory markers."""
    project_path = project_path.resolve()
    resolved_languages = _infer_languages(project_path, languages)
    dependencies: set[str] = set()
    dependencies.update(_collect_python_dependencies(project_path))
    dependencies.update(_collect_js_dependencies(project_path))
    dependencies.update(_collect_go_dependencies(project_path))
    dependencies.update(_collect_rust_dependencies(project_path))
    dependencies.update(_collect_ruby_dependencies(project_path))
    dependencies.update(_collect_php_dependencies(project_path))

    frameworks = {
        framework
        for dep in dependencies
        for marker, framework in FRAMEWORK_MARKERS.items()
        if marker in dep
    }
    frameworks.update(
        framework
        for marker, framework in FRAMEWORK_FILE_MARKERS.items()
        if (project_path / marker).exists()
    )

    archetypes = sorted(
        {
            archetype
            for name, archetype in ARCHETYPE_MARKERS.items()
            if (project_path / name).exists()
        }
    )

    canonical = {
        "languages": sorted(set(resolved_languages)),
        "frameworks": sorted(frameworks),
        "dependencies": sorted(dependencies)[:30],
        "archetypes": archetypes,
    }
    fingerprint_hash = hashlib.sha1(
        json.dumps(canonical, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return ProjectFingerprint(
        project_path=str(project_path),
        display_name=display_name or project_path.name,
        languages=canonical["languages"],
        frameworks=canonical["frameworks"],
        dependencies=canonical["dependencies"],
        archetypes=canonical["archetypes"],
        fingerprint_hash=fingerprint_hash,
    )


def _jaccard(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def score_relatedness(current: ProjectFingerprint, candidate: ProjectFingerprint) -> float:
    """Score overlap using fixed weighted similarity components."""
    language_score = _jaccard(current.languages, candidate.languages)
    framework_score = _jaccard(current.frameworks, candidate.frameworks)
    dependency_score = _jaccard(current.dependencies[:15], candidate.dependencies[:15])
    archetype_score = _jaccard(current.archetypes, candidate.archetypes)
    return round(
        (language_score * 0.35)
        + (framework_score * 0.25)
        + (dependency_score * 0.25)
        + (archetype_score * 0.15),
        4,
    )


def fingerprint_from_row(row: dict[str, Any]) -> ProjectFingerprint:
    """Rehydrate a fingerprint from a ``registered_projects`` row."""
    raw = json.loads(row.get("fingerprint_json") or "{}")
    return ProjectFingerprint(
        project_path=str(raw.get("project_path") or row.get("project_path") or ""),
        display_name=str(raw.get("display_name") or row.get("display_name") or ""),
        languages=list(raw.get("languages") or json.loads(row.get("languages_json") or "[]")),
        frameworks=list(raw.get("frameworks") or json.loads(row.get("frameworks_json") or "[]")),
        dependencies=list(
            raw.get("dependencies") or json.loads(row.get("dependency_summary_json") or "[]")
        ),
        archetypes=list(raw.get("archetypes") or []),
        fingerprint_hash=str(raw.get("fingerprint_hash") or ""),
    )
