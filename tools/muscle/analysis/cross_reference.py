"""
Cross-reference analyzer for Python projects.

Builds an import graph across multiple files and detects architectural
issues such as circular imports, unused exports, and signature mismatches.

Architecture Decision Record (ADR):
- Lightweight AST-based import extraction avoids executing code
- DFS cycle detection is simple and sufficient for typical project sizes
- Signature comparison uses ast.FunctionDef for robustness
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import Finding, Severity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrossReferenceFinding(Finding):
    """Finding produced by the cross-reference analyzer."""

    file_path: str = ""
    symbol: str = ""

    def to_review_issue_dict(self) -> dict[str, Any]:
        """Emit a v1-compatible ReviewIssue shape."""
        return {
            "file_path": self.file_path,
            "line_number": self.line,
            "severity": self.severity.name,
            "category": self.category,
            "cwe_id": None,
            "title": self.rule_id,
            "description": self.message,
            "code_snippet": self.symbol,
            "suggested_fix": None,
            "auto_fixable": False,
            "source_agent": "cross_reference",
        }


@dataclass
class _ModuleInfo:
    """Internal representation of a parsed module."""

    path: Path
    imports: list[tuple[str, str | None]] = field(default_factory=list)
    exports: list[tuple[str, int]] = field(default_factory=list)
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)


class ImportGraph:
    """Directed graph of module imports."""

    def __init__(self) -> None:
        self._nodes: set[str] = set()
        self._edges: dict[str, list[str]] = {}

    def add_node(self, name: str) -> None:
        """Add a module node."""
        self._nodes.add(name)
        self._edges.setdefault(name, [])

    def add_edge(self, from_module: str, to_module: str) -> None:
        """Add a directed import edge."""
        self.add_node(from_module)
        self.add_node(to_module)
        self._edges[from_module].append(to_module)

    def neighbors(self, name: str) -> list[str]:
        """Return modules imported by *name*."""
        return list(self._edges.get(name, []))

    def find_cycles(self) -> list[list[str]]:
        """Find all simple cycles via DFS.

        Returns:
            List of cycles, where each cycle is a list of module names.
        """
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: list[str] = []
        rec_set: set[str] = set()

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.append(node)
            rec_set.add(node)
            for neighbor in self._edges.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_set:
                    idx = rec_stack.index(neighbor)
                    cycle = rec_stack[idx:] + [neighbor]
                    cycles.append(cycle)
            rec_stack.pop()
            rec_set.discard(node)

        for node in self._nodes:
            if node not in visited:
                dfs(node)
        return cycles


class CrossReferenceAnalyzer:
    """Analyzes cross-references across a Python project."""

    def __init__(self) -> None:
        self._modules: dict[str, _ModuleInfo] = {}
        self._graph = ImportGraph()

    def _module_name_from_path(self, path: Path, root: Path) -> str:
        """Derive a dotted module name from a file path."""
        try:
            rel = path.relative_to(root)
        except ValueError:
            # path is outside root — use the file name only
            rel = path
        parts = list(rel.with_suffix("").parts)
        return ".".join(parts)

    def _parse_module(self, path: Path, root: Path) -> _ModuleInfo | None:
        """Parse a single Python file and extract imports/exports."""
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", path, exc)
            return None

        info = _ModuleInfo(path=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    info.imports.append((alias.name, alias.asname))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full = f"{module}.{alias.name}" if module else alias.name
                    info.imports.append((full, alias.asname))
            elif isinstance(node, ast.FunctionDef):
                if not node.name.startswith("_"):
                    info.exports.append((node.name, node.lineno))
                    info.functions[node.name] = node
            elif isinstance(node, ast.ClassDef):
                if not node.name.startswith("_"):
                    info.exports.append((node.name, node.lineno))
        return info

    def build_graph(self, directory: str, pattern: str = "*.py") -> ImportGraph:
        """Build the import graph for all matching files under *directory*.

        Args:
            directory: Root directory to scan.
            pattern: Glob pattern for Python files.

        Returns:
            Populated ImportGraph instance.
        """
        root = Path(directory).resolve()
        self._modules.clear()
        self._graph = ImportGraph()

        for path in root.rglob(pattern):
            mod_name = self._module_name_from_path(path, root)
            info = self._parse_module(path, root)
            if info is None:
                continue
            self._modules[mod_name] = info
            self._graph.add_node(mod_name)

        for mod_name, info in self._modules.items():
            for imp, _ in info.imports:
                # Heuristic: map import to a local module if possible
                parts = imp.split(".")
                for i in range(len(parts), 0, -1):
                    candidate = ".".join(parts[:i])
                    if candidate in self._modules and candidate != mod_name:
                        self._graph.add_edge(mod_name, candidate)
                        break

        return self._graph

    def find_unused_exports(self) -> list[CrossReferenceFinding]:
        """Detect public functions/classes that are never imported locally.

        Returns:
            List of findings for orphaned exports.
        """
        findings: list[CrossReferenceFinding] = []
        all_imported: set[str] = set()
        for info in self._modules.values():
            for imp, alias in info.imports:
                all_imported.add(imp)
                if alias:
                    all_imported.add(alias)

        for mod_name, info in self._modules.items():
            for symbol, line in info.exports:
                full_name = f"{mod_name}.{symbol}"
                if full_name not in all_imported and symbol not in all_imported:
                    findings.append(
                        CrossReferenceFinding(
                            rule_id="XREF-001",
                            message=f"Unused export '{symbol}' in {mod_name}",
                            severity=Severity.LOW,
                            line=line,
                            column=0,
                            category="best_practice",
                            file_path=str(info.path),
                            symbol=symbol,
                        )
                    )
        return findings

    def find_circular_imports(self) -> list[CrossReferenceFinding]:
        """Detect circular import chains.

        Returns:
            List of findings, one per unique cycle.
        """
        findings: list[CrossReferenceFinding] = []
        seen: set[tuple[str, ...]] = set()
        for cycle in self._graph.find_cycles():
            key = tuple(sorted(set(cycle)))
            if key in seen:
                continue
            seen.add(key)
            cycle_str = " -> ".join(cycle)
            # Report on the first module in the cycle
            first = cycle[0]
            info = self._modules.get(first)
            file_path = str(info.path) if info else ""
            findings.append(
                CrossReferenceFinding(
                    rule_id="XREF-002",
                    message=f"Circular import detected: {cycle_str}",
                    severity=Severity.HIGH,
                    line=1,
                    column=0,
                    category="correctness",
                    file_path=file_path,
                    symbol=first,
                )
            )
        return findings

    def find_missing_dependencies(self) -> list[CrossReferenceFinding]:
        """Detect imports that do not resolve to known local modules.

        Returns:
            List of findings for potentially missing local dependencies.
        """
        findings: list[CrossReferenceFinding] = []
        known = set(self._modules.keys())
        for mod_name, info in self._modules.items():
            for imp, _ in info.imports:
                parts = imp.split(".")
                candidate = parts[0]
                # Skip stdlib and well-known third-party packages
                if candidate in {"os", "sys", "typing", "collections", "json", "pathlib"}:
                    continue
                if len(parts) == 1 and candidate not in known:
                    findings.append(
                        CrossReferenceFinding(
                            rule_id="XREF-003",
                            message=f"Missing local dependency '{imp}' in {mod_name}",
                            severity=Severity.MEDIUM,
                            line=1,
                            column=0,
                            category="correctness",
                            file_path=str(info.path),
                            symbol=imp,
                        )
                    )
        return findings

    def find_signature_mismatches(self) -> list[CrossReferenceFinding]:
        """Detect functions with identical names but different signatures.

        Returns:
            List of findings for inconsistent signatures.
        """
        findings: list[CrossReferenceFinding] = []
        signatures: dict[str, list[tuple[str, ast.FunctionDef]]] = {}

        for mod_name, info in self._modules.items():
            for name, func in info.functions.items():
                signatures.setdefault(name, []).append((mod_name, func))

        for name, defs in signatures.items():
            if len(defs) < 2:
                continue
            base_args = self._arg_signature(defs[0][1])
            for mod_name, func in defs[1:]:
                if self._arg_signature(func) != base_args:
                    findings.append(
                        CrossReferenceFinding(
                            rule_id="XREF-004",
                            message=(
                                f"Inconsistent signature for '{name}' in {mod_name} vs {defs[0][0]}"
                            ),
                            severity=Severity.MEDIUM,
                            line=func.lineno,
                            column=func.col_offset,
                            category="correctness",
                            file_path=str(self._modules[mod_name].path),
                            symbol=name,
                        )
                    )
        return findings

    @staticmethod
    def _arg_signature(func: ast.FunctionDef) -> tuple[str, ...]:
        """Return a hashable signature tuple for a function."""
        args = func.args
        parts: list[str] = []
        for arg in args.args:
            parts.append(arg.arg)
        for arg in args.posonlyargs:
            parts.append(arg.arg)
        for arg in args.kwonlyargs:
            parts.append(arg.arg)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        return tuple(parts)

    def analyze(self, directory: str, pattern: str = "*.py") -> list[CrossReferenceFinding]:
        """Run all cross-reference checks and return combined findings.

        Args:
            directory: Root directory to scan.
            pattern: Glob pattern for Python files.

        Returns:
            Combined list of findings from all checks.
        """
        self.build_graph(directory, pattern)
        findings: list[CrossReferenceFinding] = []
        findings.extend(self.find_unused_exports())
        findings.extend(self.find_circular_imports())
        findings.extend(self.find_missing_dependencies())
        findings.extend(self.find_signature_mismatches())
        return findings
