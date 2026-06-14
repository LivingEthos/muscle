"""
AST-based security analyzer for Python source files.

Architecture Decision Record (ADR):
- Uses the stdlib ``ast`` module for zero-dependency parsing
- Visitor pattern keeps detection logic modular and testable
- High-level ``ASTAnalyzer`` service wraps the visitor for batch processing
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import Finding, Severity

logger = logging.getLogger(__name__)

# Patterns that suggest hardcoded secrets in assignment targets or values.
_SECRET_PATTERNS = [
    re.compile(r"password\s*[=:]\s*['\"]", re.IGNORECASE),
    re.compile(r"secret\s*[=:]\s*['\"]", re.IGNORECASE),
    re.compile(r"api_key\s*[=:]\s*['\"]", re.IGNORECASE),
    re.compile(r"token\s*[=:]\s*['\"]", re.IGNORECASE),
    re.compile(r"auth\s*[=:]\s*['\"]", re.IGNORECASE),
]

# Dangerous built-in functions and methods.
_DANGEROUS_CALLS = {
    "eval": "AST-001",
    "exec": "AST-002",
    "compile": "AST-003",
    "__import__": "AST-004",
}

_DANGEROUS_ATTRS = {
    ("pickle", "loads"): "AST-005",
    ("yaml", "load"): "AST-006",
    ("os", "system"): "AST-007",
    ("os", "popen"): "AST-008",
}

_SQL_METHODS = {"execute", "executemany", "executescript"}


@dataclass(frozen=True)
class ASTFinding(Finding):
    """Finding produced by the AST security analyzer."""

    file_path: str = ""

    def to_static_issue_dict(self) -> dict[str, Any]:
        """Emit a v1-compatible StaticIssue shape."""
        return {
            "file_path": self.file_path,
            "line_number": self.line,
            "severity": self.severity.name,
            "rule_id": self.rule_id,
            "message": self.message,
            "category": self.category,
        }


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor that collects security-related findings."""

    def __init__(self, file_path: str, source_lines: list[str]) -> None:
        self.file_path = file_path
        self.source_lines = source_lines
        self.findings: list[ASTFinding] = []

    def _add(
        self,
        rule_id: str,
        message: str,
        severity: Severity,
        node: ast.AST,
        category: str = "security",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        lineno = max(1, getattr(node, "lineno", 1))
        col_offset = getattr(node, "col_offset", 0)
        self.findings.append(
            ASTFinding(
                rule_id=rule_id,
                message=message,
                severity=severity,
                line=lineno,
                column=col_offset,
                category=category,
                metadata=metadata or {},
                file_path=self.file_path,
            )
        )

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self._check_dangerous_call(node)
        self._check_subprocess_shell(node)
        self._check_sql_injection(node)
        self._check_os_getenv_secret(node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self._check_hardcoded_secrets(node)
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:  # noqa: N802
        self._check_debug_mode(node)
        self.generic_visit(node)

    def _check_dangerous_call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in _DANGEROUS_CALLS:
            rule_id = _DANGEROUS_CALLS[func.id]
            self._add(
                rule_id,
                f"Use of dangerous built-in '{func.id}' detected",
                Severity.CRITICAL,
                node,
            )
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            key = (func.value.id, func.attr)
            if key in _DANGEROUS_ATTRS:
                rule_id = _DANGEROUS_ATTRS[key]
                self._add(
                    rule_id,
                    f"Use of dangerous function '{func.value.id}.{func.attr}' detected",
                    Severity.HIGH,
                    node,
                )

    def _check_subprocess_shell(self, node: ast.Call) -> None:
        func = node.func
        is_subprocess = False
        if isinstance(func, ast.Name) and func.id in {"subprocess", "Popen", "call", "run"}:
            is_subprocess = True
        elif isinstance(func, ast.Attribute) and func.attr in {"Popen", "call", "run"}:
            is_subprocess = True

        if not is_subprocess:
            return

        shell_true = False
        for keyword in node.keywords:
            if keyword.arg == "shell":
                if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    shell_true = True
                break

        if shell_true:
            self._add(
                "AST-009",
                "subprocess invoked with shell=True",
                Severity.HIGH,
                node,
            )

    def _check_sql_injection(self, node: ast.Call) -> None:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _SQL_METHODS:
            return

        for arg in node.args:
            if self._is_formatted_string(arg):
                self._add(
                    "AST-010",
                    "Potential SQL injection via string formatting",
                    Severity.CRITICAL,
                    node,
                )
                return

    def _is_formatted_string(self, node: ast.AST) -> bool:
        if isinstance(node, ast.JoinedStr):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return True
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                return True
        return False

    def _check_os_getenv_secret(self, node: ast.Call) -> None:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "getenv":
            return
        if not isinstance(func.value, ast.Name) or func.value.id != "os":
            return
        if len(node.args) < 2:
            return
        default_arg = node.args[1]
        if isinstance(default_arg, ast.Constant) and isinstance(default_arg.value, str):
            self._add(
                "AST-011",
                "os.getenv called with a hardcoded default secret value",
                Severity.MEDIUM,
                node,
            )

    def _check_hardcoded_secrets(self, node: ast.Assign) -> None:
        line = self.source_lines[node.lineno - 1] if node.lineno <= len(self.source_lines) else ""
        for pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self._add(
                            "AST-012",
                            f"Possible hardcoded secret in assignment to '{target.id}'",
                            Severity.HIGH,
                            node,
                        )
                        return

    def _check_debug_mode(self, node: ast.Expr) -> None:
        value = node.value
        if isinstance(value, ast.Assign):
            # Handled in visit_Assign
            return
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Attribute) and func.attr in {"run", "debug"}:
                for keyword in value.keywords:
                    if keyword.arg == "debug" and isinstance(keyword.value, ast.Constant):
                        if keyword.value.value is True:
                            self._add(
                                "AST-013",
                                "Debug mode explicitly enabled",
                                Severity.LOW,
                                node,
                            )


class ASTSecurityAnalyzer:
    """Low-level AST security analyzer for a single source file."""

    def analyze(self, file_path: str, source: str) -> list[ASTFinding]:
        """Analyze Python source and return security findings.

        Args:
            file_path: Path to the file (used for metadata).
            source: Python source code.

        Returns:
            List of findings sorted by line number.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning("Syntax error in %s: %s", file_path, exc)
            return []

        lines = source.splitlines()
        visitor = _SecurityVisitor(file_path, lines)
        visitor.visit(tree)
        return sorted(visitor.findings, key=lambda f: (f.line, f.column))


class ASTAnalyzer:
    """High-level service that analyzes multiple files."""

    def __init__(self) -> None:
        self._security = ASTSecurityAnalyzer()

    def analyze_file(self, file_path: str) -> list[ASTFinding]:
        """Analyze a single file on disk.

        Args:
            file_path: Absolute or relative path to a Python file.

        Returns:
            List of findings.
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning("File not found: %s", file_path)
            return []
        source = path.read_text(encoding="utf-8")
        return self._security.analyze(file_path, source)

    def analyze_directory(self, directory: str, pattern: str = "*.py") -> list[ASTFinding]:
        """Recursively analyze all matching files in a directory.

        Args:
            directory: Root directory to scan.
            pattern: Glob pattern for file matching.

        Returns:
            Flat list of findings from all files.
        """
        findings: list[ASTFinding] = []
        for path in Path(directory).rglob(pattern):
            findings.extend(self.analyze_file(str(path)))
        return findings
