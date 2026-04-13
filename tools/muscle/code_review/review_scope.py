"""
Review Scope Classification - Heuristic routing for smart review workflows.

Architecture Decision Record (ADR):
- Prefer deterministic scope classification over another LLM hop
- Bias toward low-noise defaults for repo-wide reviews without changed-files input
- Use workflow name to decide whether to run a smart or comprehensive committee
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .types import Intensity, ReviewMode, ReviewScope

SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "c",
}
DOC_EXTENSIONS = {".md", ".rst", ".txt"}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini"}
PUBLIC_SURFACE_MARKERS = (
    "cli.py",
    "__init__.py",
    "README.md",
    "docs/",
    "plugin/commands/",
    "plugin/.claude-plugin/",
)
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}


@dataclass(frozen=True)
class ScopeInputs:
    target_path: str
    changed_files: list[str] | None = None
    workflow_name: str = "review-smart"
    mode: ReviewMode = ReviewMode.REVIEW


class ReviewScopeClassifier:
    """Classify review scope and route smart workflow agents."""

    def classify(self, inputs: ScopeInputs) -> ReviewScope:
        target = Path(inputs.target_path)
        discovered = self._discover_files(target, inputs.changed_files)
        changed_files = [str(path) for path in discovered]

        source_files = [str(path) for path in discovered if path.suffix.lower() in SOURCE_EXTENSIONS]
        doc_files = [str(path) for path in discovered if path.suffix.lower() in DOC_EXTENSIONS]
        test_files = [
            str(path)
            for path in discovered
            if self._is_test_path(path)
        ]
        touched_languages = sorted(
            {SOURCE_EXTENSIONS[path.suffix.lower()] for path in discovered if path.suffix.lower() in SOURCE_EXTENSIONS}
        )
        line_count = sum(self._safe_line_count(path) for path in discovered)
        docs_only = bool(discovered) and len(doc_files) == len(discovered)
        tests_only = bool(discovered) and len(test_files) == len(discovered)
        public_api_changed = any(self._is_public_surface(path) for path in discovered)
        complexity = self._classify_complexity(len(source_files), len(discovered), line_count)

        review_agents = self._select_agents(
            workflow_name=inputs.workflow_name,
            mode=inputs.mode,
            target=target,
            source_files=source_files,
            docs_only=docs_only,
            tests_only=tests_only,
            public_api_changed=public_api_changed,
            has_changed_files=bool(inputs.changed_files),
        )
        review_intensity = self._intensity_for_complexity(complexity, inputs.mode)
        test_scope = self._test_scope(source_files, test_files, docs_only, tests_only, inputs.changed_files)
        auto_fix_cap = self._auto_fix_cap(complexity)
        reasoning = self._build_reasoning(
            complexity=complexity,
            docs_only=docs_only,
            tests_only=tests_only,
            public_api_changed=public_api_changed,
            review_agents=review_agents,
            has_changed_files=bool(inputs.changed_files),
        )

        return ReviewScope(
            complexity=complexity,
            changed_files=changed_files,
            source_files=source_files,
            doc_files=doc_files,
            test_files=test_files,
            touched_languages=touched_languages,
            review_agents=review_agents,
            review_intensity=review_intensity,
            test_scope=test_scope,
            auto_fix_cap=auto_fix_cap,
            public_api_changed=public_api_changed,
            docs_only=docs_only,
            tests_only=tests_only,
            line_count=line_count,
            reasoning=reasoning,
        )

    def _discover_files(self, target: Path, changed_files: list[str] | None) -> list[Path]:
        if changed_files:
            return [Path(path).resolve() for path in changed_files]
        if target.is_file():
            return [target.resolve()]
        if not target.exists():
            return []

        files: list[Path] = []
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            if (
                path.suffix.lower() in SOURCE_EXTENSIONS
                or path.suffix.lower() in DOC_EXTENSIONS
                or path.suffix.lower() in CONFIG_EXTENSIONS
            ):
                files.append(path.resolve())
        return files

    def _classify_complexity(self, source_count: int, file_count: int, line_count: int) -> str:
        if file_count <= 1 and line_count <= 80:
            return "trivial"
        if source_count <= 3 and file_count <= 5 and line_count <= 250:
            return "small"
        if source_count <= 10 and file_count <= 12 and line_count <= 800:
            return "medium"
        return "large"

    def _select_agents(
        self,
        workflow_name: str,
        mode: ReviewMode,
        target: Path,
        source_files: list[str],
        docs_only: bool,
        tests_only: bool,
        public_api_changed: bool,
        has_changed_files: bool,
    ) -> list[str]:
        if workflow_name == "pressure-review" or mode == ReviewMode.PRESSURE:
            return ["pressure"]

        all_agents = [
            "correctness_security",
            "error_handling_concurrency",
            "test_impact_coverage",
            "docs_api_impact",
        ]
        if workflow_name == "review-comprehensive":
            return all_agents

        review_agents = ["correctness_security"]

        if docs_only:
            return ["docs_api_impact"]

        if source_files and (has_changed_files or target.is_file()):
            review_agents.append("error_handling_concurrency")
            review_agents.append("test_impact_coverage")

        if public_api_changed:
            review_agents.append("docs_api_impact")

        if tests_only and "test_impact_coverage" in review_agents:
            review_agents.remove("test_impact_coverage")

        # Stable order with duplicate suppression.
        ordered = [agent for agent in all_agents if agent in review_agents]
        return ordered or ["correctness_security"]

    def _intensity_for_complexity(self, complexity: str, mode: ReviewMode) -> str:
        if mode == ReviewMode.PRESSURE:
            return Intensity.INTENSIVE.value
        mapping = {
            "trivial": Intensity.MINIMAL.value,
            "small": Intensity.MODERATE.value,
            "medium": Intensity.INTENSIVE.value,
            "large": Intensity.EXHAUSTIVE.value,
        }
        return mapping.get(complexity, Intensity.MODERATE.value)

    def _test_scope(
        self,
        source_files: list[str],
        test_files: list[str],
        docs_only: bool,
        tests_only: bool,
        changed_files: list[str] | None,
    ) -> str:
        if docs_only:
            return "none"
        if tests_only:
            return "tests-only"
        if changed_files and source_files:
            return "targeted"
        if source_files:
            return "repo-scan"
        if test_files:
            return "tests-only"
        return "none"

    def _auto_fix_cap(self, complexity: str) -> int:
        mapping = {
            "trivial": 1,
            "small": 2,
            "medium": 3,
            "large": 5,
        }
        return mapping.get(complexity, 2)

    def _build_reasoning(
        self,
        complexity: str,
        docs_only: bool,
        tests_only: bool,
        public_api_changed: bool,
        review_agents: list[str],
        has_changed_files: bool,
    ) -> str:
        parts = [f"complexity={complexity}"]
        if docs_only:
            parts.append("docs-only change")
        if tests_only:
            parts.append("tests-only change")
        if public_api_changed:
            parts.append("public surface changed")
        if has_changed_files:
            parts.append("changed-files input available")
        parts.append(f"agents={','.join(review_agents)}")
        return "; ".join(parts)

    @staticmethod
    def _safe_line_count(path: Path) -> int:
        try:
            return len(path.read_text(encoding="utf-8").splitlines())
        except Exception:
            return 0

    @staticmethod
    def _is_test_path(path: Path) -> bool:
        normalized = str(path).lower()
        return "/tests/" in normalized or normalized.endswith("_test.py") or "test_" in path.name.lower()

    @staticmethod
    def _is_public_surface(path: Path) -> bool:
        normalized = str(path).replace("\\", "/")
        return any(marker in normalized for marker in PUBLIC_SURFACE_MARKERS)
