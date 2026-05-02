"""
Static Analyzer for code review.

Runs static analysis tools (Ruff, ESLint, etc.) and parses their output
into structured StaticIssue objects for further analysis by M2.7.

Architecture Decision Record (ADR):
- Tool-agnostic interface for adding new analyzers
- Parallel execution of independent tools
- Structured output for M2.7 consumption
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from ..command_evidence import ParserTier, build_command_evidence
from .types import StaticAnalysisResult, StaticIssue

logger = logging.getLogger(__name__)

LANGUAGE_TOOLS: dict[str, list[dict[str, Any]]] = {
    "python": [
        {
            "name": "ruff",
            "cmd": ["ruff", "check", "--output-format=json"],
            "parser": "_parse_ruff_json",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
                "info": "LOW",
            },
        },
        {
            "name": "pyright",
            "cmd": ["pyright", "--outputjson"],
            "parser": "_parse_pyright_json",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
                "information": "LOW",
            },
        },
        {
            "name": "bandit",
            "cmd": ["bandit", "-f", "json", "-r"],
            "parser": "_parse_bandit_json",
            "severity_map": {
                "HIGH": "HIGH",
                "MEDIUM": "MEDIUM",
                "LOW": "LOW",
            },
        },
    ],
    "javascript": [
        {
            "name": "eslint",
            "cmd": ["eslint", "--format=json"],
            "parser": "_parse_eslint_json",
            "severity_map": {
                "2": "HIGH",
                "1": "MEDIUM",
                "0": "LOW",
            },
        },
    ],
    "typescript": [
        {
            "name": "eslint",
            "cmd": ["eslint", "--format=json"],
            "parser": "_parse_eslint_json",
            "severity_map": {
                "2": "HIGH",
                "1": "MEDIUM",
                "0": "LOW",
            },
        },
        {
            "name": "tsc",
            "cmd": ["tsc", "--noEmit", "--pretty", "false"],
            "parser": "_parse_tsc_text",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
            },
        },
    ],
    "svelte": [
        {
            "name": "svelte-check",
            "cmd": [
                "svelte-check",
                "--tsconfig",
                "./tsconfig.json",
                "--output",
                "machine-readable",
            ],
            "parser": "_parse_svelte_check_json",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
            },
        },
    ],
    "go": [
        {
            "name": "golangci-lint",
            "cmd": ["golangci-lint", "run", "--out-format=json"],
            "parser": "_parse_golangci_json",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
            },
        },
    ],
    "rust": [
        {
            "name": "clippy",
            "cmd": ["cargo", "clippy", "--message-format=json"],
            "parser": "_parse_clippy_json",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
            },
        },
    ],
    "cpp": [
        {
            "name": "cppcheck",
            "cmd": ["cppcheck", "--enable=all", "--json", "."],
            "parser": "_parse_cppcheck_json",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
                "style": "LOW",
                "performance": "MEDIUM",
                "portability": "LOW",
                "information": "INFO",
            },
        },
    ],
    "java": [
        {
            "name": "checkstyle",
            "cmd": ["checkstyle", "-c/google_checks.xml", "."],
            "parser": "_parse_checkstyle_text",
            "severity_map": {
                "error": "HIGH",
                "warning": "MEDIUM",
            },
        },
    ],
}

AUTO_FIXABLE_TOOLS = {"ruff", "eslint", "golangci-lint", "clippy"}

LANGUAGE_EXTENSIONS = {
    "python": {".py"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx"},
    "svelte": {".svelte"},
    "go": {".go"},
    "rust": {".rs"},
    "cpp": {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"},
    "java": {".java"},
}

STRICT_JSON_PARSERS = {
    "_parse_pyright_json",
    "_parse_bandit_json",
    "_parse_eslint_json",
    "_parse_golangci_json",
    "_parse_cppcheck_json",
    "_parse_svelte_check_json",
}
FALLBACK_JSON_PARSERS = {"_parse_ruff_json"}
NDJSON_PARSERS = {"_parse_clippy_json"}


class StaticAnalyzer:
    def __init__(
        self,
        target_path: str,
        language: str | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        self.target_path = Path(target_path)
        self.include_patterns = include_patterns or ["*"]
        default_excludes = [
            "node_modules",
            ".git",
            "__pycache__",
            "*.pyc",
            ".venv",
            "venv",
        ]
        self.exclude_patterns = exclude_patterns or default_excludes
        self._effective_exclude_patterns = list(
            dict.fromkeys([*default_excludes, *(exclude_patterns or [])])
        )
        self.language = language or self._detect_language()

    def _detect_language(self) -> str | None:
        path = self.target_path
        if path.is_file():
            suffix = path.suffix.lower()
            ext_to_lang = {
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".jsx": "javascript",
                ".tsx": "typescript",
                ".svelte": "svelte",
                ".go": "go",
                ".rs": "rust",
                ".cpp": "cpp",
                ".cc": "cpp",
                ".c": "c",
                ".h": "c",
                ".java": "java",
            }
            return ext_to_lang.get(suffix)
        else:
            files = self._iter_included_files(path)
            extensions = {f.suffix.lower() for f in files if f.is_file() and f.suffix}

            if ".svelte" in extensions:
                return "svelte"
            if ".py" in extensions:
                return "python"
            if ".js" in extensions:
                return "javascript"
            if ".ts" in extensions:
                return "typescript"
            if ".go" in extensions:
                return "go"
            if ".rs" in extensions:
                return "rust"
            if ".cpp" in extensions or ".cc" in extensions or ".h" in extensions:
                return "cpp"
            if ".java" in extensions:
                return "java"

        return None

    def _should_include(self, file_path: Path) -> bool:
        path = Path(file_path)
        try:
            rel_path = path.relative_to(
                self.target_path if self.target_path.is_dir() else self.target_path.parent
            )
        except ValueError:
            rel_path = path
        normalized = rel_path.as_posix()
        name = path.name

        for pattern in self._effective_exclude_patterns:
            if pattern in path.parts or fnmatch(name, pattern) or fnmatch(normalized, pattern):
                return False

        return any(
            fnmatch(name, pattern) or fnmatch(normalized, pattern)
            for pattern in self.include_patterns
        )

    def _iter_included_files(self, root: Path | None = None) -> list[Path]:
        target = root or self.target_path
        if target.is_file():
            return [target] if self._should_include(target) else []
        if not target.exists():
            return []
        extensions = LANGUAGE_EXTENSIONS.get(getattr(self, "language", None) or "")
        return [
            path
            for path in sorted(target.rglob("*"))
            if path.is_file()
            and self._should_include(path)
            and (extensions is None or path.suffix.lower() in extensions)
        ]

    def analyze(self) -> list[StaticAnalysisResult]:
        if not self.language:
            logger.warning("Could not detect language, no static analysis run")
            return []

        tools = LANGUAGE_TOOLS.get(self.language, [])
        if not tools:
            logger.warning(f"No tools configured for language: {self.language}")
            return []

        # Fix: SA-01. Sort tools by name for deterministic scheduling. We keep
        # parallel execution for throughput but iterate results back in the
        # input order so downstream consumers see stable output regardless of
        # which tool finishes first.
        ordered_tools = sorted(tools, key=lambda t: t.get("name", ""))

        indexed_results: dict[int, StaticAnalysisResult] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(ordered_tools))) as executor:
            futures = {
                executor.submit(self._run_tool, tool): index
                for index, tool in enumerate(ordered_tools)
            }
            for future in as_completed(futures):
                index = futures[future]
                tool = ordered_tools[index]
                try:
                    result = future.result()
                    if result:
                        indexed_results[index] = result
                except Exception as e:
                    logger.error(f"Tool {tool['name']} failed: {e}")

        return [indexed_results[i] for i in sorted(indexed_results)]

    def _run_tool(self, tool: dict[str, Any]) -> StaticAnalysisResult | None:
        tool_name = tool["name"]
        cmd = list(tool["cmd"])

        if not shutil.which(cmd[0]):
            logger.info(f"{tool_name} not found, skipping")
            return None

        if self.target_path.is_file():
            if not self._should_include(self.target_path):
                return StaticAnalysisResult(
                    tool_name=tool_name,
                    language=self.language or "unknown",
                    issues=[],
                    duration_seconds=0,
                    error_output="Target excluded by review scope",
                    parser_tier=ParserTier.FULL.value,
                )
            cmd.append(str(self.target_path.name))
            working_dir = str(self.target_path.parent)
        else:
            working_dir = str(self.target_path)
            files_to_analyze = self._iter_included_files()
            if not files_to_analyze:
                return StaticAnalysisResult(
                    tool_name=tool_name,
                    language=self.language or "unknown",
                    issues=[],
                    duration_seconds=0,
                    error_output="No files matched review scope",
                    parser_tier=ParserTier.FULL.value,
                )
            relative_files = [str(path.relative_to(self.target_path)) for path in files_to_analyze]
            if cmd and cmd[-1] == ".":
                cmd = cmd[:-1]
            cmd.extend(relative_files)

        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            duration = time.time() - start_time

            output = result.stdout + result.stderr
            issues, parser_tier, parse_warnings = self._parse_tool_output(tool, output)
            issues = [issue for issue in issues if self._should_include(Path(issue.file_path))]
            evidence = build_command_evidence(
                command=cmd,
                cwd=working_dir,
                exit_code=result.returncode,
                duration_ms=int(duration * 1000),
                raw_stdout=result.stdout,
                raw_stderr=result.stderr,
                parser_tier=parser_tier,
                warnings=parse_warnings,
            )

            return StaticAnalysisResult(
                tool_name=tool_name,
                language=self.language or "unknown",
                issues=issues,
                duration_seconds=duration,
                error_output=result.stderr if result.returncode != 0 else "",
                parser_tier=parser_tier.value,
                parse_warnings=parse_warnings,
                evidence=evidence,
            )

        except subprocess.TimeoutExpired:
            logger.warning(f"{tool_name} timed out")
            evidence = build_command_evidence(
                command=cmd,
                cwd=working_dir,
                exit_code=-1,
                duration_ms=300_000,
                raw_stdout="",
                raw_stderr="Tool timed out after 300 seconds",
                parser_tier=ParserTier.PASSTHROUGH,
                warnings=["tool timed out after 300 seconds"],
                force_raw_artifact=True,
            )
            return StaticAnalysisResult(
                tool_name=tool_name,
                language=self.language or "unknown",
                issues=[],
                duration_seconds=300,
                error_output="Tool timed out after 300 seconds",
                parser_tier=ParserTier.PASSTHROUGH.value,
                parse_warnings=["tool timed out after 300 seconds"],
                evidence=evidence,
            )
        except FileNotFoundError:
            logger.warning(f"{tool_name} not found")
            return None
        except Exception as e:
            logger.error(f"{tool_name} failed: {e}")
            duration = time.time() - start_time
            evidence = build_command_evidence(
                command=cmd,
                cwd=working_dir,
                exit_code=-3,
                duration_ms=int(duration * 1000),
                raw_stdout="",
                raw_stderr=str(e),
                parser_tier=ParserTier.PASSTHROUGH,
                warnings=[str(e)],
                force_raw_artifact=True,
            )
            return StaticAnalysisResult(
                tool_name=tool_name,
                language=self.language or "unknown",
                issues=[],
                duration_seconds=duration,
                error_output=str(e),
                parser_tier=ParserTier.PASSTHROUGH.value,
                parse_warnings=[str(e)],
                evidence=evidence,
            )

    def _parse_tool_output(
        self,
        tool: dict[str, Any],
        output: str,
    ) -> tuple[list[StaticIssue], ParserTier, list[str]]:
        """Parse one analyzer output and classify parse confidence."""
        parser_name = str(tool.get("parser") or "")
        severity_map = tool.get("severity_map", {})
        parser_method = getattr(self, parser_name, None)
        warnings: list[str] = []

        if not parser_method:
            issues = self._parse_generic(output, severity_map)
            if not output.strip():
                return issues, ParserTier.FULL, warnings
            if issues:
                return (
                    issues,
                    ParserTier.DEGRADED,
                    [f"{parser_name or 'unknown'} used generic parser"],
                )
            return (
                issues,
                ParserTier.PASSTHROUGH,
                [f"{parser_name or 'unknown'} parser unavailable"],
            )

        issues = parser_method(output, severity_map)
        if not output.strip():
            return issues, ParserTier.FULL, warnings

        if parser_name in STRICT_JSON_PARSERS | FALLBACK_JSON_PARSERS:
            try:
                json.loads(output)
            except json.JSONDecodeError:
                if issues:
                    return (
                        issues,
                        ParserTier.DEGRADED,
                        [f"{tool['name']} JSON parse failed; used fallback extraction"],
                    )
                return (
                    issues,
                    ParserTier.PASSTHROUGH,
                    [f"{tool['name']} JSON parse failed; raw output preserved"],
                )
            else:
                return issues, ParserTier.FULL, warnings

        if parser_name in NDJSON_PARSERS:
            malformed_lines = 0
            json_lines = 0
            for line in output.splitlines():
                if not line.strip() or not line.lstrip().startswith("{"):
                    continue
                json_lines += 1
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    malformed_lines += 1
            if malformed_lines and issues:
                return (
                    issues,
                    ParserTier.DEGRADED,
                    [f"{tool['name']} NDJSON parse had {malformed_lines} malformed line(s)"],
                )
            if malformed_lines or (not json_lines and output.strip()):
                return (
                    issues,
                    ParserTier.PASSTHROUGH,
                    [f"{tool['name']} NDJSON parse failed; raw output preserved"],
                )
            return issues, ParserTier.FULL, warnings

        if issues or not output.strip():
            return issues, ParserTier.FULL, warnings
        return issues, ParserTier.PASSTHROUGH, [f"{tool['name']} text parse produced no issues"]

    def _parse_ruff_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if "violations" in item:
                            for violation in item.get("violations", []):
                                issues.append(
                                    StaticIssue(
                                        file_path=violation.get("filename", ""),
                                        line_number=violation.get("location", {}).get("row", 0),
                                        severity=severity_map.get(
                                            violation.get("severity", "warning"), "MEDIUM"
                                        ),
                                        rule_id=violation.get("code", ""),
                                        message=violation.get("message", ""),
                                        category=violation.get("code", "").split(".")[0]
                                        if violation.get("code")
                                        else "style",
                                    )
                                )
                        elif "code" in item:
                            issues.append(
                                StaticIssue(
                                    file_path=item.get("filename", ""),
                                    line_number=item.get("location", {}).get("row", 0),
                                    severity=severity_map.get("warning", "MEDIUM"),
                                    rule_id=item.get("code", ""),
                                    message=item.get("message", ""),
                                    category=item.get("code", "").split(".")[0]
                                    if item.get("code")
                                    else "style",
                                )
                            )
        except json.JSONDecodeError:
            for line in output.split("\n"):
                if not line.strip():
                    continue
                match = re.match(r"(.*?):(\d+):(\d+):\s*(\w+)\s+(.*)", line)
                if match:
                    issues.append(
                        StaticIssue(
                            file_path=match.group(1),
                            line_number=int(match.group(2)),
                            severity=severity_map.get("warning", "MEDIUM"),
                            rule_id="",
                            message=match.group(5),
                            category="style",
                        )
                    )
        return issues

    def _parse_pyright_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            general_diagnostics = data.get("generalDiagnostics", [])
            for diag in general_diagnostics:
                issues.append(
                    StaticIssue(
                        file_path=diag.get("file", ""),
                        line_number=diag.get("range", {}).get("start", {}).get("line", 0) + 1,
                        severity=severity_map.get(diag.get("severity", "warning"), "MEDIUM"),
                        rule_id=diag.get("rule", ""),
                        message=diag.get("message", ""),
                        category="type" if diag.get("rule") else "error",
                    )
                )
        except json.JSONDecodeError:
            pass
        return issues

    def _parse_bandit_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            results = data.get("results", []) if isinstance(data, dict) else []
            for item in results:
                filename = item.get("filename", "")
                line = item.get("line", 0)
                severity = item.get("severity", "MEDIUM")
                issue_id = item.get("issue_id", "")
                issue_text = item.get("issue_text", "")

                issues.append(
                    StaticIssue(
                        file_path=filename,
                        line_number=int(line) if line else 0,
                        severity=severity_map.get(severity, "MEDIUM"),
                        rule_id=issue_id,
                        message=issue_text,
                        category="security",
                    )
                )
        except json.JSONDecodeError:
            pass
        return issues

    def _parse_eslint_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            if isinstance(data, list):
                for file_result in data:
                    for warning in file_result.get("messages", []):
                        issues.append(
                            StaticIssue(
                                file_path=file_result.get("filePath", ""),
                                line_number=warning.get("line", 0),
                                severity=severity_map.get(
                                    str(warning.get("severity", 1)), "MEDIUM"
                                ),
                                rule_id=warning.get("ruleId", ""),
                                message=warning.get("message", ""),
                                category=warning.get("ruleId", "").split("/")[0]
                                if warning.get("ruleId")
                                else "lint",
                            )
                        )
        except json.JSONDecodeError:
            pass
        return issues

    def _parse_tsc_text(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            match = re.match(r"(.*?)\((\d+),\d+\):\s*(error|warning)\s+(.*)", line)
            if match:
                issues.append(
                    StaticIssue(
                        file_path=match.group(1),
                        line_number=int(match.group(2)),
                        severity=severity_map.get(match.group(3), "MEDIUM"),
                        rule_id="",
                        message=match.group(4),
                        category="type",
                    )
                )
        return issues

    def _parse_golangci_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            for issue in data.get("Issues", []):
                pos = issue.get("Pos", {}) if isinstance(issue.get("Pos"), dict) else {}
                file_path = (
                    pos.get("Filename")
                    or issue.get("File")
                    or issue.get("Filename")
                    or issue.get("Path")
                    or ""
                )
                line_number = pos.get("Line") or issue.get("Line") or 0
                issues.append(
                    StaticIssue(
                        file_path=file_path,
                        line_number=line_number,
                        severity=severity_map.get(issue.get("Severity", "warning"), "MEDIUM"),
                        rule_id=issue.get("Linter", ""),
                        message=f"{issue.get('Linter', '')}: {issue.get('Text', '')}",
                        category=issue.get("Linter", "lint"),
                    )
                )
        except json.JSONDecodeError:
            pass
        return issues

    def _parse_clippy_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            try:
                if line.startswith("{"):
                    data = json.loads(line)
                    if data.get("reason") == "compiler-message":
                        message = data.get("message", {})
                        if message.get("level") in ("error", "warning"):
                            issues.append(
                                StaticIssue(
                                    file_path=message.get("spans", [{}])[0].get("file_name", ""),
                                    line_number=message.get("spans", [{}])[0].get("line_start", 0),
                                    severity=severity_map.get(message.get("level"), "MEDIUM"),
                                    rule_id=message.get("code", {}).get("code", ""),
                                    message=message.get("message", ""),
                                    category="clippy",
                                )
                            )
            except json.JSONDecodeError:
                continue
        return issues

    def _parse_cppcheck_json(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            for result in data.get("results", []):
                issues.append(
                    StaticIssue(
                        file_path=result.get("file", ""),
                        line_number=result.get("line", 0),
                        severity=severity_map.get(result.get("severity", "warning"), "MEDIUM"),
                        rule_id=result.get("id", ""),
                        message=result.get("msg", ""),
                        category=result.get("type", "style"),
                    )
                )
        except json.JSONDecodeError:
            pass
        return issues

    def _parse_checkstyle_text(
        self, output: str, severity_map: dict[str, str]
    ) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        for line in output.split("\n"):
            if not line.strip() or "[ERROR]" not in line and "[WARNING]" not in line:
                continue
            match = re.match(r".*\[(ERROR|WARNING)\]\s+(.*?):(\d+):\s*(.*)", line)
            if match:
                issues.append(
                    StaticIssue(
                        file_path=match.group(2),
                        line_number=int(match.group(3)),
                        severity=severity_map.get(match.group(1).lower(), "MEDIUM"),
                        rule_id="",
                        message=match.group(4),
                        category="style",
                    )
                )
        return issues

    def _parse_svelte_check_json(
        self, output: str, severity_map: dict[str, str]
    ) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        try:
            data = json.loads(output)
            if isinstance(data, dict) and "messages" in data:
                for msg in data.get("messages", []):
                    severity_str = msg.get("severity", "warning").upper()
                    issues.append(
                        StaticIssue(
                            file_path=msg.get("file", ""),
                            line_number=msg.get("startLine", msg.get("line", 0)),
                            severity=severity_map.get(severity_str.lower(), "MEDIUM"),
                            rule_id=msg.get("code", ""),
                            message=msg.get("message", ""),
                            category=msg.get("source", "svelte"),
                        )
                    )
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        severity_str = item.get("severity", "warning").upper()
                        issues.append(
                            StaticIssue(
                                file_path=item.get("file", ""),
                                line_number=item.get("line", 0),
                                severity=severity_map.get(severity_str.lower(), "MEDIUM"),
                                rule_id=item.get("code", ""),
                                message=item.get("message", ""),
                                category=item.get("source", "svelte"),
                            )
                        )
        except json.JSONDecodeError:
            pass
        return issues

    def _parse_generic(self, output: str, severity_map: dict[str, str]) -> list[StaticIssue]:
        issues: list[StaticIssue] = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            match = re.match(r"(.*?):(\d+):\s*(.*)", line)
            if match:
                issues.append(
                    StaticIssue(
                        file_path=match.group(1),
                        line_number=int(match.group(2)),
                        severity=severity_map.get("warning", "MEDIUM"),
                        rule_id="",
                        message=match.group(3),
                        category="lint",
                    )
                )
        return issues

    def auto_fix(self) -> list[str]:
        if not self.language:
            return []

        tools = LANGUAGE_TOOLS.get(self.language, [])
        fixable = [t for t in tools if t["name"] in AUTO_FIXABLE_TOOLS]
        fixed_files: list[str] = []

        for tool in fixable:
            tool_name = tool["name"]
            if not shutil.which(tool_name):
                continue

            if tool_name == "ruff":
                fix_cmd = ["ruff", "check", "--fix"]
            elif tool_name == "eslint":
                fix_cmd = ["eslint", "--fix"]
            elif tool_name == "golangci-lint":
                fix_cmd = ["golangci-lint", "run", "--fix"]
            elif tool_name == "clippy":
                fix_cmd = ["cargo", "clippy", "--fix", "--allow-dirty"]
            else:
                continue

            try:
                result = subprocess.run(
                    fix_cmd,
                    cwd=str(self.target_path),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    logger.info(f"{tool_name} auto-fix completed")
                    for line in result.stdout.split("\n"):
                        if "Fixed" in line or "fixed" in line:
                            fixed_files.append(line.strip())
            except Exception as e:
                logger.warning(f"{tool_name} auto-fix failed: {e}")

        return fixed_files
