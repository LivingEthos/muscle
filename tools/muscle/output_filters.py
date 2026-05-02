"""
Declarative output filters for command evidence compaction.

Architecture Decision Record (ADR):
- Filters may reduce boring command output before prompt-facing compaction, but
  raw output remains recoverable in command evidence artifacts.
- Built-in filters are trusted with the MUSCLE release. Project-local filters
  fail closed unless explicitly trusted by content digest or CI override.
- Success short-circuit messages require an ``unless`` guard so filters cannot
  hide warnings or errors by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .io_safety import atomic_write_json

FILTERS_PATH = Path(".muscle") / "filters.yaml"
TRUST_PATH = Path(".muscle") / "filter-trust.json"
DEFAULT_UNLESS_PATTERN = r"\b(error|failed|failure|traceback|exception|warning)\b"


@dataclass(frozen=True)
class OutputFilter:
    """One trusted output filter rule."""

    name: str
    command: str = ".*"
    strip_regexes: list[str] = field(default_factory=list)
    keep_regexes: list[str] = field(default_factory=list)
    line_cap: int | None = None
    success_message: str | None = None
    unless: str | None = None
    tests: list[dict[str, Any]] = field(default_factory=list)
    source: str = "builtin"

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str) -> OutputFilter:
        """Build a filter from a schema dict."""
        strip_value = data.get("strip_regexes", data.get("strip_regex", []))
        keep_value = data.get("keep_regexes", data.get("keep_regex", []))
        if isinstance(strip_value, str):
            strip_value = [strip_value]
        if isinstance(keep_value, str):
            keep_value = [keep_value]
        command = data.get("command_regex", data.get("command", ".*"))
        return cls(
            name=str(data["name"]),
            command=str(command),
            strip_regexes=[str(item) for item in strip_value],
            keep_regexes=[str(item) for item in keep_value],
            line_cap=int(data["line_cap"]) if data.get("line_cap") is not None else None,
            success_message=str(data["success_message"])
            if data.get("success_message") is not None
            else None,
            unless=str(data["unless"]) if data.get("unless") is not None else None,
            tests=[dict(item) for item in data.get("tests", []) if isinstance(item, dict)],
            source=source,
        )


BUILTIN_FILTERS: tuple[OutputFilter, ...] = (
    OutputFilter(
        name="pytest-progress",
        command=r"\bpytest\b",
        strip_regexes=[r"^\s*\.+\s*$", r"^\s*collected \d+ items\s*$"],
        line_cap=200,
        tests=[
            {
                "input": "collected 3 items\n...\nFAILED test_a.py::test_x - boom",
                "expected_contains": "FAILED",
                "expected_not_contains": "collected 3 items",
            }
        ],
    ),
    OutputFilter(
        name="npm-noise",
        command=r"\b(npm|pnpm|yarn)\b",
        strip_regexes=[r"^\s*added \d+ packages.*$", r"^\s*found 0 vulnerabilities\s*$"],
        line_cap=200,
    ),
    OutputFilter(
        name="ruff-summary-noise",
        command=r"\bruff\b",
        strip_regexes=[r"^\s*All checks passed!\s*$"],
        line_cap=200,
    ),
)


def _project_path(project_path: str | Path) -> Path:
    return Path(project_path).resolve()


def _project_filter_path(project_path: str | Path) -> Path:
    return _project_path(project_path) / FILTERS_PATH


def _trust_path(project_path: str | Path) -> Path:
    return _project_path(project_path) / TRUST_PATH


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ci_override_enabled() -> bool:
    if os.environ.get("MUSCLE_TRUST_PROJECT_FILTERS") != "1":
        return False
    return any(
        os.environ.get(name)
        for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "BUILDKITE")
    )


def project_filters_trusted(project_path: str | Path) -> tuple[bool, str]:
    """Return whether project-local filters are trusted for current content."""
    filters_path = _project_filter_path(project_path)
    if not filters_path.exists():
        return False, "no project filters"
    digest = _file_sha256(filters_path)
    if _ci_override_enabled():
        return True, "trusted by CI override"
    trust_path = _trust_path(project_path)
    if not trust_path.exists():
        return False, "project filters are not trusted"
    try:
        trust = json.loads(trust_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "trust file is invalid"
    if trust.get("filters_sha256") != digest:
        return False, "project filter content changed since trust"
    return True, "trusted"


def load_project_filters(project_path: str | Path) -> tuple[list[OutputFilter], list[str]]:
    """Load trusted project-local filters."""
    filters_path = _project_filter_path(project_path)
    if not filters_path.exists():
        return [], []
    trusted, reason = project_filters_trusted(project_path)
    if not trusted:
        return [], [reason]
    try:
        data = yaml.safe_load(filters_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [], [f"project filter parse failed: {exc}"]
    specs = data.get("filters", data if isinstance(data, list) else [])
    if not isinstance(specs, list):
        return [], ["project filters must be a list or a mapping with filters"]
    filters: list[OutputFilter] = []
    warnings: list[str] = []
    for spec in specs:
        if not isinstance(spec, dict) or not spec.get("name"):
            warnings.append("skipping invalid project filter entry")
            continue
        filters.append(OutputFilter.from_dict(spec, source="project"))
    return filters, warnings


def trust_project_filters(project_path: str | Path) -> dict[str, Any]:
    """Trust the current project-local filter file by content digest."""
    filters_path = _project_filter_path(project_path)
    if not filters_path.exists():
        return {"trusted": False, "reason": "no project filters"}
    digest = _file_sha256(filters_path)
    trust_path = _trust_path(project_path)
    trust_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "filters_path": str(filters_path),
        "filters_sha256": digest,
        "trusted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    atomic_write_json(trust_path, payload, indent=2)
    return {"trusted": True, "filters_sha256": digest, "trust_path": str(trust_path)}


def untrust_project_filters(project_path: str | Path) -> dict[str, Any]:
    """Remove project-local filter trust."""
    trust_path = _trust_path(project_path)
    existed = trust_path.exists()
    if existed:
        trust_path.unlink()
    return {"trusted": False, "removed": existed, "trust_path": str(trust_path)}


def _matches_filter(rule: OutputFilter, command: str) -> bool:
    try:
        return re.search(rule.command, command) is not None
    except re.error:
        return False


def _apply_rule(rule: OutputFilter, output: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not output:
        return output, warnings

    if rule.success_message:
        guard = rule.unless
        if not guard:
            warnings.append(f"filter {rule.name} ignored success_message without unless guard")
        else:
            try:
                if re.search(guard, output, re.IGNORECASE) is None:
                    return rule.success_message, warnings
            except re.error as exc:
                warnings.append(f"filter {rule.name} has invalid unless regex: {exc}")

    lines = output.replace("\r\n", "\n").splitlines()
    if rule.keep_regexes:
        kept: list[str] = []
        for line in lines:
            for pattern in rule.keep_regexes:
                if re.search(pattern, line):
                    kept.append(line)
                    break
        lines = kept

    if rule.strip_regexes:
        stripped: list[str] = []
        for line in lines:
            if any(re.search(pattern, line) for pattern in rule.strip_regexes):
                continue
            stripped.append(line)
        lines = stripped

    if rule.line_cap is not None and len(lines) > rule.line_cap:
        omitted = len(lines) - rule.line_cap
        head_count = max(1, rule.line_cap // 2)
        tail_count = max(0, rule.line_cap - head_count)
        lines = [
            *lines[:head_count],
            f"... [output filter {rule.name} omitted {omitted} line(s)] ...",
            *lines[-tail_count:],
        ]
    return "\n".join(lines), warnings


def apply_output_filters(
    command: str,
    output: str,
    project_path: str | Path | None = None,
) -> tuple[str, list[str]]:
    """Apply trusted output filters to command output."""
    warnings: list[str] = []
    filters = list(BUILTIN_FILTERS)
    if project_path is not None:
        project_filters, filter_warnings = load_project_filters(project_path)
        filters.extend(project_filters)
        warnings.extend(filter_warnings)

    filtered = output
    for rule in filters:
        if not _matches_filter(rule, command):
            continue
        filtered, rule_warnings = _apply_rule(rule, filtered)
        warnings.extend(rule_warnings)
    return filtered, warnings


def verify_filters(
    project_path: str | Path,
    *,
    filter_name: str | None = None,
    require_all: bool = False,
) -> dict[str, Any]:
    """Run inline filter tests for built-in and trusted project filters."""
    project_filters, warnings = load_project_filters(project_path)
    filters = [*BUILTIN_FILTERS, *project_filters]
    if filter_name:
        filters = [rule for rule in filters if rule.name == filter_name]

    results: list[dict[str, Any]] = []
    for rule in filters:
        if require_all and not rule.tests:
            results.append(
                {
                    "name": rule.name,
                    "source": rule.source,
                    "passed": False,
                    "reason": "missing inline tests",
                }
            )
            continue
        for test in rule.tests:
            output, rule_warnings = _apply_rule(rule, str(test.get("input", "")))
            expected = test.get("expected")
            expected_contains = test.get("expected_contains")
            expected_not_contains = test.get("expected_not_contains")
            passed = True
            if expected is not None and output != str(expected):
                passed = False
            if expected_contains is not None and str(expected_contains) not in output:
                passed = False
            if expected_not_contains is not None and str(expected_not_contains) in output:
                passed = False
            results.append(
                {
                    "name": rule.name,
                    "source": rule.source,
                    "passed": passed,
                    "warnings": rule_warnings,
                }
            )
        if not rule.tests and not require_all:
            results.append(
                {
                    "name": rule.name,
                    "source": rule.source,
                    "passed": True,
                    "reason": "no inline tests",
                }
            )

    passed = all(item["passed"] for item in results) and not (filter_name and not filters)
    if filter_name and not filters:
        warnings.append(f"filter not found: {filter_name}")
    return {
        "passed": passed,
        "filter_count": len(filters),
        "results": results,
        "warnings": warnings,
    }
