"""Fetch third-party JS/TS package sources via opensrc for review enrichment."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_JS_TS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}

_PROJECT_ROOT_MARKERS = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    ".git",
}

_IMPORT_PATTERNS = [
    # import ... from 'pkg' and export * from 'pkg'
    re.compile(r'(?:import|export)\s+[\w\s{},*]+\s+from\s+["\']([^"\'./][^"\']*)["\']'),
    # import 'pkg' (side-effect)
    re.compile(r'import\s+["\']([^"\'./][^"\']*)["\']'),
    # require('pkg')
    re.compile(r'require\s*\(\s*["\']([^"\'./][^"\']*)["\']'),
    # import('pkg')
    re.compile(r'import\s*\(\s*["\']([^"\'./][^"\']*)["\']'),
]

_ENTRY_CANDIDATES = [
    "index.js",
    "index.ts",
    "dist/index.js",
    "src/index.ts",
]

_MAX_PACKAGES = 3
_MAX_LINES_PER_SNIPPET = 60
_MAX_SNIPPETS_PER_PACKAGE = 2
_MAX_TOTAL_LINES = 180
_OPENSRC_TIMEOUT = 60


@dataclass
class SourceContextResult:
    context: str = ""
    skip_reason: str = ""
    packages_fetched: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.context.strip()


class SourceContextBuilder:
    """Builds compact third-party dependency context for JS/TS review prompts."""

    def __init__(self, target_path: str | Path) -> None:
        self._target = Path(target_path)

    def build(
        self,
        fetch_source_packages: list[str] | None = None,
    ) -> SourceContextResult:
        project_root = self._resolve_project_root()
        if project_root is None:
            return SourceContextResult(
                skip_reason="No JS/TS project root found; skipping dependency context"
            )

        reviewed_files = self._collect_js_ts_files()
        if not reviewed_files:
            return SourceContextResult(
                skip_reason="Skipping dependency context: source fetching currently supports JS/TS foreground review only"
            )

        if fetch_source_packages:
            packages = fetch_source_packages[:_MAX_PACKAGES]
        else:
            imports = self._extract_imports(reviewed_files)
            if not imports:
                return SourceContextResult(
                    skip_reason="No third-party JS/TS package imports found; continuing without dependency context"
                )
            packages = [pkg for pkg, _ in Counter(imports).most_common(_MAX_PACKAGES)]

        if not self._opensrc_available():
            logger.warning(
                "opensrc not installed; continuing without dependency context. "
                "Install with: npm install -g opensrc"
            )
            return SourceContextResult(
                skip_reason="opensrc not installed; continuing without dependency context. "
                "Install with: npm install -g opensrc"
            )

        fetch_ok = self._fetch_packages(packages, project_root)
        if not fetch_ok:
            return SourceContextResult(
                skip_reason="Failed to fetch package sources via opensrc; continuing without dependency context"
            )

        listing = self._list_fetched(project_root)
        if listing is None:
            return SourceContextResult(
                skip_reason="Failed to fetch package sources via opensrc; continuing without dependency context"
            )

        context = self._build_context(packages, listing, project_root)
        fetched = [p for p in packages if any(e.get("name") == p for e in listing)]
        return SourceContextResult(context=context, packages_fetched=fetched)

    def _resolve_project_root(self) -> Path | None:
        candidates = [self._target] if self._target.is_dir() else [self._target.parent]
        current = candidates[0]
        for _ in range(20):
            for marker in _PROJECT_ROOT_MARKERS:
                if (current / marker).exists():
                    return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    def _collect_js_ts_files(self) -> list[Path]:
        if self._target.is_file():
            return [self._target] if self._target.suffix in _JS_TS_EXTENSIONS else []
        return [p for p in self._target.rglob("*") if p.suffix in _JS_TS_EXTENSIONS and p.is_file()]

    def _extract_imports(self, files: list[Path]) -> list[str]:
        imports: list[str] = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pat in _IMPORT_PATTERNS:
                for match in pat.finditer(text):
                    pkg = _normalize_package(match.group(1))
                    if pkg:
                        imports.append(pkg)
        return imports

    @staticmethod
    def _opensrc_available() -> bool:
        try:
            result = subprocess.run(
                ["opensrc", "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _fetch_packages(self, packages: list[str], cwd: Path) -> bool:
        try:
            result = subprocess.run(
                ["opensrc", *packages, "--cwd", str(cwd), "--modify=false"],
                capture_output=True,
                timeout=_OPENSRC_TIMEOUT,
                cwd=str(cwd),
            )
            if result.returncode != 0:
                logger.warning(
                    "opensrc fetch failed (exit %d): %s",
                    result.returncode,
                    result.stderr.decode(errors="replace")[:500],
                )
                return False
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("opensrc fetch error: %s", exc)
            return False

    def _list_fetched(self, cwd: Path) -> list[dict] | None:
        try:
            result = subprocess.run(
                ["opensrc", "list", "--json", "--cwd", str(cwd)],
                capture_output=True,
                timeout=10,
                cwd=str(cwd),
            )
            if result.returncode != 0:
                return None
            raw = result.stdout.decode(errors="replace").strip()
            return json.loads(raw) if raw else []
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            logger.warning("opensrc list failed: %s", exc)
            return None

    def _build_context(
        self,
        packages: list[str],
        listing: list[dict],
        project_root: Path,
    ) -> str:
        index = {e.get("name", ""): e for e in listing}
        lines_budget = _MAX_TOTAL_LINES
        sections: list[str] = []

        for pkg_name in packages:
            if lines_budget <= 0:
                break
            entry = index.get(pkg_name)
            if entry is None:
                continue

            pkg_dir_raw = entry.get("path") or entry.get("dir")
            if not pkg_dir_raw:
                continue
            pkg_dir = Path(pkg_dir_raw)
            if not pkg_dir.is_absolute():
                pkg_dir = project_root / pkg_dir

            pkg_json_path = pkg_dir / "package.json"
            pkg_meta: dict = {}
            if pkg_json_path.exists():
                try:
                    pkg_meta = json.loads(
                        pkg_json_path.read_text(encoding="utf-8", errors="replace")
                    )
                except (OSError, json.JSONDecodeError):
                    pass

            version = entry.get("version") or pkg_meta.get("version", "unknown")
            description = pkg_meta.get("description", "")
            main = pkg_meta.get("main", "")
            module = pkg_meta.get("module", "")
            types = pkg_meta.get("types") or pkg_meta.get("typings", "")
            exports_dot = ""
            if isinstance(pkg_meta.get("exports"), dict):
                exports_dot = str(pkg_meta["exports"].get(".", ""))

            header_lines = [
                f"## Package: {pkg_name} @ {version}",
                f"Path: {pkg_dir}",
            ]
            if description:
                header_lines.append(f"Description: {description}")
            for label, val in [
                ("main", main),
                ("module", module),
                ("types", types),
                ('exports["."]', exports_dot),
            ]:
                if val:
                    header_lines.append(f"{label}: {val}")

            entry_files = _candidate_entry_files(pkg_dir, main, module, types)
            snippets: list[str] = []
            snippets_used = 0
            for ef in entry_files:
                if snippets_used >= _MAX_SNIPPETS_PER_PACKAGE or lines_budget <= 0:
                    break
                snippet = _read_snippet(ef, _MAX_LINES_PER_SNIPPET)
                if snippet:
                    cost = snippet.count("\n") + 1
                    if lines_budget - cost < 0:
                        continue
                    snippets.append(f"### {ef.name}\n```\n{snippet}\n```")
                    lines_budget -= cost
                    snippets_used += 1

            section = "\n".join(header_lines)
            if snippets:
                section += "\n\n" + "\n\n".join(snippets)
            sections.append(section)

        if not sections:
            return ""
        return "## Third-Party Dependency Context\n\n" + "\n\n---\n\n".join(sections)


def _normalize_package(raw: str) -> str:
    """Strip subpaths and node: built-ins; return empty string to skip."""
    if raw.startswith("node:"):
        return ""
    if raw.startswith(".") or raw.startswith("/"):
        return ""
    if raw.startswith("@"):
        parts = raw.split("/")
        return "/".join(parts[:2]) if len(parts) >= 2 else raw
    return raw.split("/")[0]


def _candidate_entry_files(pkg_dir: Path, main: str, module: str, types: str) -> list[Path]:
    candidates: list[Path] = []
    for rel in [main, module, types]:
        if rel:
            p = pkg_dir / rel
            if p.exists() and p.is_file():
                candidates.append(p)
    for name in _ENTRY_CANDIDATES:
        p = pkg_dir / name
        if p.exists() and p.is_file() and p not in candidates:
            candidates.append(p)
    return candidates


def _read_snippet(path: Path, max_lines: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return "\n".join(lines[:max_lines])
    except OSError:
        return ""
