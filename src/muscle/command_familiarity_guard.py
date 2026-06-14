"""Command familiarity guard for MUSCLE-owned command execution.

Architecture Decision Record (ADR):
- Treat commands copied from untrusted text as unfamiliar until local evidence
  or an internal allowlist explains them.
- Block obviously destructive commands before execution in MUSCLE-owned helpers.
- Keep evaluator commands cheap by allowlisting the stable command shapes used
  by MUSCLE's static analyzer and test runners.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KNOWN_EVALUATOR_COMMANDS = frozenset(
    {
        "bandit",
        "cargo",
        "checkstyle",
        "cppcheck",
        "eslint",
        "go",
        "golangci-lint",
        "mypy",
        "npm",
        "pnpm",
        "pyright",
        "pytest",
        "python",
        "python3",
        "ruff",
        "svelte-check",
        "tsc",
        "uv",
        "yarn",
    }
)
DESTRUCTIVE_COMMANDS = frozenset({"rm", "unlink", "shred", "dd", "mkfs", "shutdown", "reboot"})
DESTRUCTIVE_GIT_SUBCOMMANDS = frozenset(
    {"clean", "commit", "push", "reset", "restore", "checkout", "rebase", "merge"}
)
SHELL_METACHAR_RE = re.compile(r"(;|&&|\|\||\||`|\$\(|>|<)")


@dataclass(frozen=True)
class CommandFamiliarityResult:
    """Result of checking one argv command."""

    checked: bool
    familiar: bool
    risk_level: str
    source: str
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "familiar": self.familiar,
            "risk_level": self.risk_level,
            "source": self.source,
            "warnings": list(self.warnings),
            "blocked": self.blocked,
        }

    def warning_labels(self) -> list[str]:
        labels = ["command_familiarity_checked"]
        labels.extend(self.warnings)
        if not self.familiar:
            labels.append("command_unfamiliar")
        if self.blocked:
            labels.append("command_blocked")
        return labels


class CommandFamiliarityGuard:
    """Check whether a command is known enough for MUSCLE-owned execution."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def check(self, command: list[str], cwd: str | Path | None = None) -> CommandFamiliarityResult:
        """Return familiarity and risk metadata for *command*."""
        if not command:
            return CommandFamiliarityResult(
                checked=True,
                familiar=False,
                risk_level="high",
                source="empty",
                warnings=["empty_command"],
                blocked=True,
            )

        cwd_path = Path(cwd or self.project_root).resolve()
        executable = Path(str(command[0])).name
        warnings: list[str] = []

        familiar, source = self._is_familiar(executable)
        risk_level = "low" if familiar else "medium"
        blocked = False

        destructive_reason = self._destructive_reason(command)
        if destructive_reason:
            warnings.append(destructive_reason)
            risk_level = "high"
            blocked = True

        if self._has_shell_metacharacters(command):
            warnings.append("shell_metacharacters_in_argv")
            risk_level = "high"
            blocked = blocked or not familiar

        option_filename_warnings = self._option_looking_filename_warnings(command, cwd_path)
        if option_filename_warnings:
            warnings.extend(option_filename_warnings)
            risk_level = "high"

        outside_repo_warnings = self._outside_repo_warnings(command)
        if outside_repo_warnings:
            warnings.extend(outside_repo_warnings)
            risk_level = "high"

        return CommandFamiliarityResult(
            checked=True,
            familiar=familiar,
            risk_level=risk_level,
            source=source,
            warnings=warnings,
            blocked=blocked,
        )

    def _is_familiar(self, executable: str) -> tuple[bool, str]:
        if executable in KNOWN_EVALUATOR_COMMANDS:
            return True, "known_evaluator_allowlist"
        if executable in self._project_script_names():
            return True, "project_script"
        if self._mentioned_in_local_docs(executable):
            return True, "local_docs"
        return False, "unfamiliar"

    def _project_script_names(self) -> set[str]:
        scripts: set[str] = set()
        pyproject = self.project_root / "pyproject.toml"
        if pyproject.exists():
            try:
                scripts.update(_script_names_from_pyproject(pyproject.read_text(encoding="utf-8")))
            except OSError:
                pass
        package_json = self.project_root / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text(encoding="utf-8"))
                package_scripts = data.get("scripts", {})
                if isinstance(package_scripts, dict):
                    scripts.update(str(name) for name in package_scripts)
            except (OSError, json.JSONDecodeError):
                pass
        return scripts

    def _mentioned_in_local_docs(self, executable: str) -> bool:
        if not executable:
            return False
        for name in ("AGENTS.md", "CLAUDE.md", "README.md", "Makefile"):
            path = self.project_root / name
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if re.search(rf"(^|\s){re.escape(executable)}(\s|$)", text):
                return True
        return False

    @staticmethod
    def _destructive_reason(command: list[str]) -> str | None:
        executable = Path(str(command[0])).name
        if executable in DESTRUCTIVE_COMMANDS:
            return f"destructive_command:{executable}"
        if executable == "git" and len(command) > 1 and command[1] in DESTRUCTIVE_GIT_SUBCOMMANDS:
            return f"git_state_mutation:{command[1]}"
        return None

    @staticmethod
    def _has_shell_metacharacters(command: list[str]) -> bool:
        return any(SHELL_METACHAR_RE.search(str(part)) for part in command)

    @staticmethod
    def _option_looking_filename_warnings(command: list[str], cwd: Path) -> list[str]:
        warnings: list[str] = []
        after_separator = False
        for arg in command[1:]:
            if arg == "--":
                after_separator = True
                continue
            if after_separator or not arg.startswith("-"):
                continue
            candidate = (cwd / arg).resolve()
            if candidate.exists():
                warnings.append(f"option_looking_filename_requires_separator:{arg}")
        return warnings

    def _outside_repo_warnings(self, command: list[str]) -> list[str]:
        warnings: list[str] = []
        for arg in command[1:]:
            if not arg.startswith("/"):
                continue
            path = Path(arg).resolve()
            try:
                path.relative_to(self.project_root)
            except ValueError:
                warnings.append(f"path_outside_project:{arg}")
        return warnings


def _script_names_from_pyproject(text: str) -> set[str]:
    """Extract script names from simple pyproject script tables.

    This intentionally parses only table headers and top-level assignments in
    ``[project.scripts]`` and ``[tool.uv.scripts]``. It avoids adding a runtime
    dependency for Python 3.10 while still covering the command-familiarity
    source of truth we need.
    """
    names: set[str] = set()
    in_scripts = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_scripts = line in {"[project.scripts]", "[tool.uv.scripts]"}
            continue
        if not in_scripts or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip().strip('"').strip("'")
        if key:
            names.add(key)
    return names
