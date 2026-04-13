"""
Committee Reviewer - Specialized multi-agent review with deterministic synthesis.

Architecture Decision Record (ADR):
- Keep correctness/security review LLM-backed via the existing CodeReviewer
- Add deterministic specialist agents to improve recall and reduce orchestration cost
- Use deterministic synthesis first so the final findings are stable and testable
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from .code_reviewer import CodeReviewer
from .types import IssueCategory, PressureFocus, ReviewIssue, ReviewScope, Severity

AGENT_CORRECTNESS = "correctness_security"
AGENT_ERROR_HANDLING = "error_handling_concurrency"
AGENT_TEST_IMPACT = "test_impact_coverage"
AGENT_DOCS_IMPACT = "docs_api_impact"
AGENT_PRESSURE = "pressure"

_REQUESTS_CALL_RE = re.compile(r"requests\.(get|post|put|patch|delete)\(")
_SWALLOWED_EXCEPT_RE = re.compile(
    r"except(?:\s+[A-Za-z_][A-Za-z0-9_\.]*?(?:\s+as\s+\w+)?)?\s*:\s*(?:pass|return\s+None)",
    re.MULTILINE,
)


class CommitteeReviewer:
    """Run a review committee and synthesize a final finding set."""

    def __init__(self, code_reviewer: CodeReviewer):
        self.code_reviewer = code_reviewer
        self._agent_token_usage: dict[str, int] = {}
        self._token_lock = Lock()

    def run_committee(
        self,
        target_path: str,
        static_issues: list[dict],
        scope: ReviewScope,
        pressure_focus: PressureFocus | None = None,
    ) -> dict[str, list[ReviewIssue]]:
        """Run the selected review agents in parallel."""
        agent_findings: dict[str, list[ReviewIssue]] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(scope.review_agents))) as executor:
            futures = {
                executor.submit(
                    self.run_agent,
                    agent_name,
                    target_path,
                    static_issues,
                    scope,
                    pressure_focus,
                ): agent_name
                for agent_name in scope.review_agents
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    agent_findings[agent_name] = future.result()
                except Exception:
                    agent_findings[agent_name] = []
        return agent_findings

    def run_agent(
        self,
        agent_name: str,
        target_path: str,
        static_issues: list[dict],
        scope: ReviewScope,
        pressure_focus: PressureFocus | None = None,
    ) -> list[ReviewIssue]:
        """Run a single review agent."""
        if agent_name == AGENT_CORRECTNESS:
            issues, summary = self.code_reviewer.review(target_path, static_issues)
            if isinstance(summary, dict):
                self._record_agent_tokens(agent_name, int(summary.get("token_usage", 0)))
            return [self._tag_issue(issue, agent_name) for issue in issues]
        if agent_name == AGENT_ERROR_HANDLING:
            return self._error_handling_review(target_path, scope)
        if agent_name == AGENT_TEST_IMPACT:
            return self._test_impact_review(target_path, scope)
        if agent_name == AGENT_DOCS_IMPACT:
            return self._docs_impact_review(target_path, scope)
        if agent_name == AGENT_PRESSURE:
            return self._pressure_review(target_path, pressure_focus)
        return []

    def consume_agent_tokens(self, agent_name: str) -> int:
        with self._token_lock:
            return self._agent_token_usage.pop(agent_name, 0)

    def synthesize(
        self,
        agent_findings: dict[str, list[ReviewIssue]],
    ) -> list[ReviewIssue]:
        """Deduplicate and merge committee findings into a final issue set."""
        grouped: dict[tuple[str, int, str], list[ReviewIssue]] = {}
        for issues in agent_findings.values():
            for issue in issues:
                key = (
                    issue.file_path,
                    issue.line_number,
                    self._normalize_title(issue.title),
                )
                grouped.setdefault(key, []).append(issue)

        synthesized: list[ReviewIssue] = []
        for issues in grouped.values():
            if len(issues) == 1:
                synthesized.append(issues[0])
                continue

            issues_sorted = sorted(issues, key=lambda issue: issue.severity.value, reverse=True)
            primary = issues_sorted[0]
            merged_description = " ".join(
                description
                for description in {
                    issue.description.strip() for issue in issues if issue.description.strip()
                }
            )
            merged_fix = next(
                (issue.suggested_fix for issue in issues if issue.suggested_fix), None
            )
            merged_agents = sorted({issue.source_agent for issue in issues if issue.source_agent})

            synthesized.append(
                ReviewIssue(
                    file_path=primary.file_path,
                    line_number=primary.line_number,
                    severity=primary.severity,
                    category=primary.category,
                    cwe_id=primary.cwe_id,
                    title=primary.title,
                    description=merged_description or primary.description,
                    code_snippet=primary.code_snippet,
                    suggested_fix=merged_fix,
                    auto_fixable=any(issue.auto_fixable for issue in issues),
                    source_agent=",".join(merged_agents) if merged_agents else primary.source_agent,
                )
            )

        synthesized.sort(
            key=lambda issue: (
                -issue.severity.value,
                issue.file_path,
                issue.line_number,
                issue.title,
            )
        )
        return synthesized

    def summarize(self, synthesized_issues: list[ReviewIssue]) -> dict[str, int]:
        """Build summary counts for synthesized issues."""
        return {
            "critical": sum(
                1 for issue in synthesized_issues if issue.severity == Severity.CRITICAL
            ),
            "high": sum(1 for issue in synthesized_issues if issue.severity == Severity.HIGH),
            "medium": sum(1 for issue in synthesized_issues if issue.severity == Severity.MEDIUM),
            "low": sum(1 for issue in synthesized_issues if issue.severity == Severity.LOW),
            "info": sum(1 for issue in synthesized_issues if issue.severity == Severity.INFO),
            "total": len(synthesized_issues),
        }

    def _error_handling_review(self, target_path: str, scope: ReviewScope) -> list[ReviewIssue]:
        findings: list[ReviewIssue] = []
        for file_path in self._iter_files(target_path, scope.source_files):
            content = self._read_file(file_path)
            if not content:
                continue

            if _SWALLOWED_EXCEPT_RE.search(content):
                findings.append(
                    ReviewIssue(
                        file_path=str(file_path),
                        line_number=self._line_number_for_pattern(content, "except"),
                        severity=Severity.MEDIUM,
                        category=IssueCategory.CORRECTNESS,
                        cwe_id=None,
                        title="Swallowed exception hides failure path",
                        description=(
                            "An exception handler suppresses errors with `pass` or `return None`, "
                            "which can hide production failures and break diagnosis."
                        ),
                        code_snippet="except ...: pass",
                        suggested_fix="Log the exception or raise a domain-specific error with context.",
                        auto_fixable=False,
                        source_agent=AGENT_ERROR_HANDLING,
                    )
                )

            for line_number, line in enumerate(content.splitlines(), start=1):
                if _REQUESTS_CALL_RE.search(line) and "timeout=" not in line:
                    findings.append(
                        ReviewIssue(
                            file_path=str(file_path),
                            line_number=line_number,
                            severity=Severity.MEDIUM,
                            category=IssueCategory.BEST_PRACTICE,
                            cwe_id=None,
                            title="Network request missing timeout",
                            description=(
                                "The request call does not declare a timeout, so a stalled dependency "
                                "can block the workflow indefinitely."
                            ),
                            code_snippet=line.strip(),
                            suggested_fix="Add an explicit timeout=... argument to the requests call.",
                            auto_fixable=False,
                            source_agent=AGENT_ERROR_HANDLING,
                        )
                    )
        return findings

    def _test_impact_review(self, target_path: str, scope: ReviewScope) -> list[ReviewIssue]:
        if not scope.source_files:
            return []

        findings: list[ReviewIssue] = []
        repo_root = self._infer_repo_root(target_path)
        changed_has_tests = bool(scope.test_files)
        if scope.changed_files and changed_has_tests:
            return []

        for source_path_str in scope.source_files[:10]:
            source_path = Path(source_path_str)
            if self._is_test_file(source_path):
                continue
            if self._has_matching_test(repo_root, source_path):
                continue
            findings.append(
                ReviewIssue(
                    file_path=str(source_path),
                    line_number=1,
                    severity=Severity.LOW if not scope.changed_files else Severity.MEDIUM,
                    category=IssueCategory.BEST_PRACTICE,
                    cwe_id=None,
                    title="Changed source file has no targeted test companion",
                    description=(
                        "The review touched a source file without a nearby targeted test file, "
                        "which increases regression risk for future auto-fixes."
                    ),
                    code_snippet="",
                    suggested_fix=(
                        "Add or update a focused test that exercises the behavior changed in this file."
                    ),
                    auto_fixable=False,
                    source_agent=AGENT_TEST_IMPACT,
                )
            )
        return findings

    def _docs_impact_review(self, target_path: str, scope: ReviewScope) -> list[ReviewIssue]:
        if not scope.public_api_changed:
            return []
        if scope.doc_files:
            return []

        target = Path(target_path)
        return [
            ReviewIssue(
                file_path=str(target),
                line_number=1,
                severity=Severity.MEDIUM,
                category=IssueCategory.DOCUMENTATION,
                cwe_id=None,
                title="Public surface changed without docs update",
                description=(
                    "A CLI, plugin command, README surface, or public module appears to have changed "
                    "without a matching documentation update."
                ),
                code_snippet="",
                suggested_fix="Update the relevant docs, README, or command reference alongside the code change.",
                auto_fixable=False,
                source_agent=AGENT_DOCS_IMPACT,
            )
        ]

    def _pressure_review(
        self,
        target_path: str,
        pressure_focus: PressureFocus | None = None,
    ) -> list[ReviewIssue]:
        target = Path(target_path)
        if target.is_file():
            files = [target]
        elif target.exists():
            files = [
                path
                for path in sorted(target.rglob("*"))
                if path.is_file() and path.suffix.lower() in {".py", ".js", ".ts", ".go", ".rs"}
            ]
        else:
            files = []

        focus = pressure_focus or PressureFocus(
            design_tradeoffs=True,
            failure_modes=True,
            race_conditions=True,
            auth_security=True,
            data_loss=True,
        )
        findings: list[ReviewIssue] = []
        for file_path in files:
            content = self._read_file(file_path)
            if not content:
                continue
            pressure = self.code_reviewer.pressure_review(str(file_path), content, focus)
            summary = pressure.get("summary", {})
            if isinstance(summary, dict):
                self._record_agent_tokens(AGENT_PRESSURE, int(summary.get("token_usage", 0)))
            for item in pressure.get("pressure_findings", []):
                findings.append(
                    ReviewIssue(
                        file_path=item.get("file_path", str(file_path)),
                        line_number=item.get("line_number", 0),
                        severity=CodeReviewer._parse_severity(item.get("severity", "MEDIUM")),
                        category=IssueCategory.BEST_PRACTICE,
                        cwe_id=None,
                        title=item.get("title", "Pressure finding"),
                        description=item.get("description", ""),
                        code_snippet=item.get("code_snippet", ""),
                        suggested_fix=item.get("suggested_approach"),
                        auto_fixable=False,
                        source_agent=AGENT_PRESSURE,
                    )
                )
        return findings

    def _record_agent_tokens(self, agent_name: str, tokens: int) -> None:
        with self._token_lock:
            self._agent_token_usage[agent_name] = (
                self._agent_token_usage.get(agent_name, 0) + tokens
            )

    @staticmethod
    def _tag_issue(issue: ReviewIssue, agent_name: str) -> ReviewIssue:
        return ReviewIssue(
            file_path=issue.file_path,
            line_number=issue.line_number,
            severity=issue.severity,
            category=issue.category,
            cwe_id=issue.cwe_id,
            title=issue.title,
            description=issue.description,
            code_snippet=issue.code_snippet,
            suggested_fix=issue.suggested_fix,
            auto_fixable=issue.auto_fixable,
            source_agent=agent_name,
        )

    @staticmethod
    def _normalize_title(title: str) -> str:
        return " ".join(title.lower().split())

    @staticmethod
    def _read_file(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    @staticmethod
    def _iter_files(target_path: str, preferred_files: list[str]) -> list[Path]:
        if preferred_files:
            return [Path(path) for path in preferred_files]
        target = Path(target_path)
        if target.is_file():
            return [target]
        if not target.exists():
            return []
        return [path for path in sorted(target.rglob("*")) if path.is_file()]

    @staticmethod
    def _line_number_for_pattern(content: str, pattern: str) -> int:
        for line_number, line in enumerate(content.splitlines(), start=1):
            if pattern in line:
                return line_number
        return 1

    @staticmethod
    def _infer_repo_root(target_path: str) -> Path:
        target = Path(target_path)
        return target if target.is_dir() else target.parent

    @staticmethod
    def _is_test_file(path: Path) -> bool:
        normalized = str(path).lower()
        return (
            "/tests/" in normalized
            or path.name.startswith("test_")
            or path.name.endswith("_test.py")
        )

    def _has_matching_test(self, repo_root: Path, source_path: Path) -> bool:
        stem = source_path.stem
        candidate_names = {f"test_{stem}.py", f"{stem}_test.py"}
        tests_dir = repo_root / "tests"
        if tests_dir.exists():
            for path in tests_dir.rglob("*.py"):
                if path.name in candidate_names:
                    return True
        for sibling in source_path.parent.glob("test_*.py"):
            if sibling.name in candidate_names:
                return True
        return False
