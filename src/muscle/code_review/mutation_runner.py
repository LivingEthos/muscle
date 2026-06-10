"""
Mutation testing runner for MUSCLE long evaluations.

Architecture Decision Record (ADR):
- Run every mutation in a disposable workspace copy so the user's checkout stays untouched
- Keep v1 Python-first with a deterministic bounded mutation catalog
- Persist mutation reports separately from review findings and log survived mutants as test-gap evidence
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..io_safety import atomic_write_json, atomic_write_text
from ..project_memory import ProjectMemory

logger = logging.getLogger(__name__)

REPORT_PREFIX = "mutation_eval"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_MUTATION_LIMIT = 12
IGNORED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".muscle",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SUPPORTED_MUTATION_TYPES = (
    "delete_side_effect",
    "negate_condition",
    "boundary_flip",
    "hardcoded_return",
    "removed_guard_clause",
    "default_value_change",
    "swapped_operands",
)


@dataclass(frozen=True)
class MutationCandidate:
    """One deterministic source-level mutation."""

    mutation_type: str
    file_path: str
    line_number: int
    description: str
    original_line: str
    mutated_line: str


class MutationRunner:
    """Run bounded mutation tests in disposable workspaces."""

    def __init__(
        self,
        project_path: str,
        project_memory: ProjectMemory | None = None,
    ) -> None:
        self.project_path = Path(project_path).resolve()
        self.reports_dir = self.project_path / ".muscle" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.project_memory = project_memory
        if self.project_memory is None:
            try:
                self.project_memory = ProjectMemory(str(self.project_path))
            except Exception as exc:
                logger.warning(
                    "Could not initialize project memory for mutation testing in %s: %s",
                    self.project_path,
                    exc,
                )

    def run(
        self,
        target: str,
        *,
        test_command: str | None = None,
        limit: int = DEFAULT_MUTATION_LIMIT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Discover mutations, run tests for each one, and persist a report."""
        resolved_target = self._resolve_target(target)
        candidates = self.discover_candidates(resolved_target, limit=limit)
        command = test_command or self._default_test_command()
        started_at = datetime.now()

        results: list[dict[str, Any]] = []
        for candidate in candidates:
            outcome = self._run_candidate(candidate, command, timeout_seconds)
            results.append(outcome)
            if outcome["status"] == "survived":
                self._record_survived_mutant(outcome)

        report = {
            "report_type": "mutation_test",
            "result_category": "mutation_test",
            "project_path": str(self.project_path),
            "target": str(resolved_target),
            "test_command": command,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now().isoformat(),
            "duration_seconds": (datetime.now() - started_at).total_seconds(),
            "mutation_types": list(SUPPORTED_MUTATION_TYPES),
            "candidates": len(candidates),
            "killed": sum(1 for item in results if item["status"] == "killed"),
            "survived": sum(1 for item in results if item["status"] == "survived"),
            "timeouts": sum(1 for item in results if item["status"] == "timeout"),
            "results": results,
        }
        report_paths = self._write_report(report)
        report["report_paths"] = report_paths
        self._record_run_summary(report)
        return report

    def discover_candidates(
        self,
        target: str | Path,
        *,
        limit: int = DEFAULT_MUTATION_LIMIT,
    ) -> list[MutationCandidate]:
        """Return a deterministic list of Python mutation candidates under the target."""
        resolved_target = self._resolve_target(target)
        candidates: list[MutationCandidate] = []
        for file_path in self._iter_python_files(resolved_target):
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                logger.warning("Could not read %s for mutation discovery: %s", file_path, exc)
                continue

            relative_path = str(file_path.relative_to(self.project_path))
            for line_number, line in enumerate(lines, start=1):
                candidates.extend(
                    self._mutation_candidates_for_line(relative_path, line_number, line)
                )
                if len(candidates) >= limit:
                    return candidates[:limit]
        return candidates[:limit]

    def _resolve_target(self, target: str | Path) -> Path:
        candidate = Path(target)
        if not candidate.is_absolute():
            candidate = (self.project_path / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _iter_python_files(self, target: Path) -> list[Path]:
        if target.is_file():
            return [target] if target.suffix == ".py" else []
        if not target.exists():
            return []
        return [
            path
            for path in sorted(target.rglob("*.py"))
            if path.is_file() and not any(part in IGNORED_DIR_NAMES for part in path.parts)
        ]

    def _mutation_candidates_for_line(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> list[MutationCandidate]:
        builders = (
            self._delete_side_effect_candidate,
            self._negate_condition_candidate,
            self._boundary_flip_candidate,
            self._hardcoded_return_candidate,
            self._removed_guard_clause_candidate,
            self._default_value_change_candidate,
            self._swapped_operands_candidate,
        )
        candidates: list[MutationCandidate] = []
        for builder in builders:
            candidate = builder(file_path, line_number, line)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _delete_side_effect_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if stripped.startswith(
            ("return", "if ", "elif ", "for ", "while ", "def ", "class ", "import ", "from ")
        ):
            return None
        if re.match(r"^[A-Za-z_][A-Za-z0-9_\.]*\s*\(", stripped) or re.match(
            r"^[A-Za-z_][A-Za-z0-9_\.\[\]'\"]*\s*=", stripped
        ):
            indent = line[: len(line) - len(line.lstrip())]
            mutated = f"{indent}pass  # MUTATION: delete side effect"
            return MutationCandidate(
                mutation_type="delete_side_effect",
                file_path=file_path,
                line_number=line_number,
                description=f"Delete side effect at {file_path}:{line_number}",
                original_line=line,
                mutated_line=mutated,
            )
        return None

    def _negate_condition_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        match = re.match(r"^(?P<indent>\s*)if (?P<condition>.+):\s*$", line)
        if match is None:
            return None
        condition = match.group("condition").strip()
        if condition.startswith("not "):
            return None
        mutated = f"{match.group('indent')}if not ({condition}):"
        return MutationCandidate(
            mutation_type="negate_condition",
            file_path=file_path,
            line_number=line_number,
            description=f"Negate condition at {file_path}:{line_number}",
            original_line=line,
            mutated_line=mutated,
        )

    def _boundary_flip_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        if line.strip().startswith("#"):
            return None
        replacements = (
            (r"<=", "<"),
            (r">=", ">"),
            (r"(?<![<>=-])<(?![<=>])", "<="),
            (r"(?<![<>=])>(?![=>])", ">="),
        )
        for pattern, replacement in replacements:
            if re.search(pattern, line):
                mutated = re.sub(pattern, replacement, line, count=1)
                if mutated != line:
                    return MutationCandidate(
                        mutation_type="boundary_flip",
                        file_path=file_path,
                        line_number=line_number,
                        description=f"Flip comparison boundary at {file_path}:{line_number}",
                        original_line=line,
                        mutated_line=mutated,
                    )
        return None

    def _hardcoded_return_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        match = re.match(r"^(?P<indent>\s*)return\s+.+$", line)
        if match is None:
            return None
        mutated = f"{match.group('indent')}return 0"
        return MutationCandidate(
            mutation_type="hardcoded_return",
            file_path=file_path,
            line_number=line_number,
            description=f"Hardcode return value at {file_path}:{line_number}",
            original_line=line,
            mutated_line=mutated,
        )

    def _removed_guard_clause_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        match = re.match(
            r"^(?P<indent>\s*)if\s+.+:\s+(?:return|raise|continue|break)\b.+$",
            line,
        )
        if match is None:
            return None
        mutated = f"{match.group('indent')}pass  # MUTATION: removed guard clause"
        return MutationCandidate(
            mutation_type="removed_guard_clause",
            file_path=file_path,
            line_number=line_number,
            description=f"Remove guard clause at {file_path}:{line_number}",
            original_line=line,
            mutated_line=mutated,
        )

    def _default_value_change_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        match = re.match(
            r"^(?P<prefix>\s*def\s+[A-Za-z_][A-Za-z0-9_]*\s*\()(?P<params>.*)(?P<suffix>\)\s*(?:->\s*[^:]+)?\s*:)\s*$",
            line,
        )
        if match is None or "=" not in match.group("params"):
            return None
        params = match.group("params")
        param_match = re.search(r"=\s*([^,\)]+)", params)
        if param_match is None:
            return None
        original_default = param_match.group(1).strip()
        mutated_default = self._mutated_default_value(original_default)
        mutated_params = (
            params[: param_match.start(1)] + mutated_default + params[param_match.end(1) :]
        )
        mutated = f"{match.group('prefix')}{mutated_params}{match.group('suffix')}"
        if mutated == line:
            return None
        return MutationCandidate(
            mutation_type="default_value_change",
            file_path=file_path,
            line_number=line_number,
            description=f"Change default parameter at {file_path}:{line_number}",
            original_line=line,
            mutated_line=mutated,
        )

    def _swapped_operands_candidate(
        self,
        file_path: str,
        line_number: int,
        line: str,
    ) -> MutationCandidate | None:
        match = re.match(
            r"^(?P<prefix>\s*(?:return\s+|[A-Za-z_][A-Za-z0-9_]*\s*=\s*))"
            r"(?P<left>[A-Za-z_][A-Za-z0-9_\.]*)\s*"
            r"(?P<operator>[+\-*/])\s*"
            r"(?P<right>[A-Za-z_][A-Za-z0-9_\.]*)\s*$",
            line,
        )
        if match is None:
            return None
        mutated = (
            f"{match.group('prefix')}{match.group('right')} "
            f"{match.group('operator')} {match.group('left')}"
        )
        return MutationCandidate(
            mutation_type="swapped_operands",
            file_path=file_path,
            line_number=line_number,
            description=f"Swap operands at {file_path}:{line_number}",
            original_line=line,
            mutated_line=mutated,
        )

    def _mutated_default_value(self, original_default: str) -> str:
        lowered = original_default.lower()
        if lowered == "true":
            return "False"
        if lowered == "false":
            return "True"
        if lowered == "none":
            return "0"
        if re.fullmatch(r"-?\d+", original_default):
            return "1" if original_default == "0" else "0"
        if re.fullmatch(r"'.*'|\".*\"", original_default):
            return "''"
        return "None"

    def _run_candidate(
        self,
        candidate: MutationCandidate,
        test_command: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="muscle-mutation-") as temp_dir:
            workspace = Path(temp_dir) / self.project_path.name
            shutil.copytree(
                self.project_path,
                workspace,
                ignore=shutil.ignore_patterns(*IGNORED_DIR_NAMES),
            )
            target_file = workspace / candidate.file_path
            original_lines = target_file.read_text(encoding="utf-8").splitlines()
            original_lines[candidate.line_number - 1] = candidate.mutated_line
            atomic_write_text(target_file, "\n".join(original_lines) + "\n")

            try:
                completed = subprocess.run(
                    test_command,
                    cwd=str(workspace),
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                combined_output = f"{completed.stdout}\n{completed.stderr}".strip()
                status = "survived" if completed.returncode == 0 else "killed"
                return {
                    **asdict(candidate),
                    "status": status,
                    "returncode": completed.returncode,
                    "diagnostic_quality": self._diagnostic_quality(
                        combined_output,
                        candidate,
                        status,
                    ),
                    "failing_test": self._extract_failing_test(combined_output, timeout_seconds),
                    "recommended_test": (
                        self._recommended_test(candidate) if status == "survived" else None
                    ),
                }
            except subprocess.TimeoutExpired as exc:
                combined_output = (
                    f"{self._timeout_output_text(exc.stdout)}\n"
                    f"{self._timeout_output_text(exc.stderr)}"
                ).strip()
                return {
                    **asdict(candidate),
                    "status": "timeout",
                    "returncode": None,
                    "diagnostic_quality": "cascading",
                    "failing_test": f"timeout after {timeout_seconds}s",
                    "recommended_test": self._recommended_test(candidate),
                    "output_tail": combined_output.splitlines()[-20:],
                }

    def _extract_failing_test(self, output: str, timeout_seconds: int) -> str | None:
        failed_match = re.search(r"FAILED\s+([^\s]+::[^\s]+)", output)
        if failed_match is not None:
            return failed_match.group(1)
        error_match = re.search(r"ERROR\s+([^\s]+::[^\s]+)", output)
        if error_match is not None:
            return error_match.group(1)
        if output:
            return output.splitlines()[-1][:240]
        return f"timeout after {timeout_seconds}s"

    def _diagnostic_quality(
        self,
        output: str,
        candidate: MutationCandidate,
        status: str,
    ) -> str:
        if status == "survived":
            return "indirect"
        if candidate.file_path in output or f"line {candidate.line_number}" in output:
            return "clear"
        if output.count("FAILED ") > 1 or output.count("ERROR ") > 1:
            return "cascading"
        return "indirect"

    def _recommended_test(self, candidate: MutationCandidate) -> str:
        return (
            "Add or tighten a focused regression test for "
            f"{candidate.mutation_type} at {candidate.file_path}:{candidate.line_number}."
        )

    def _timeout_output_text(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _default_test_command(self) -> str:
        tests_dir = self.project_path / "tests"
        if tests_dir.exists():
            return "uv run pytest tests/ -q"
        return "pytest -q"

    def _write_report(self, report: dict[str, Any]) -> dict[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.reports_dir / f"{REPORT_PREFIX}_{timestamp}.json"
        md_path = self.reports_dir / f"{REPORT_PREFIX}_{timestamp}.md"
        atomic_write_json(json_path, report, indent=2, sort_keys=True)
        atomic_write_text(md_path, self._markdown_report(report))
        return {"json": str(json_path), "markdown": str(md_path)}

    def _markdown_report(self, report: dict[str, Any]) -> str:
        lines = [
            "# MUSCLE Mutation Evaluation",
            "",
            f"- Target: `{report['target']}`",
            f"- Test command: `{report['test_command']}`",
            f"- Candidates: {report['candidates']}",
            f"- Killed: {report['killed']}",
            f"- Survived: {report['survived']}",
            f"- Timeouts: {report['timeouts']}",
            "",
            "## Results",
            "",
        ]
        for result in report.get("results", []):
            lines.append(
                f"- `{result['status']}` `{result['mutation_type']}` "
                f"{result['file_path']}:{result['line_number']} "
                f"({result.get('diagnostic_quality', 'indirect')})"
            )
            if result.get("recommended_test"):
                lines.append(f"  Suggested test: {result['recommended_test']}")
        return "\n".join(lines) + "\n"

    def _record_survived_mutant(self, outcome: dict[str, Any]) -> None:
        if self.project_memory is None:
            return
        try:
            self.project_memory.insert_action_log(
                project_path=str(self.project_path),
                action_type="mutation_survived",
                entity_type="mutation_test",
                details_json=json.dumps(outcome, sort_keys=True),
            )
        except Exception as exc:
            logger.warning("Failed to record survived mutant for %s: %s", self.project_path, exc)

    def _record_run_summary(self, report: dict[str, Any]) -> None:
        if self.project_memory is None:
            return
        try:
            self.project_memory.insert_action_log(
                project_path=str(self.project_path),
                action_type="mutation_run",
                entity_type="mutation_test",
                details_json=json.dumps(
                    {
                        "target": report["target"],
                        "test_command": report["test_command"],
                        "candidates": report["candidates"],
                        "killed": report["killed"],
                        "survived": report["survived"],
                        "timeouts": report["timeouts"],
                        "report_paths": report.get("report_paths", {}),
                    },
                    sort_keys=True,
                ),
            )
        except Exception as exc:
            logger.warning(
                "Failed to record mutation run summary for %s: %s", self.project_path, exc
            )
