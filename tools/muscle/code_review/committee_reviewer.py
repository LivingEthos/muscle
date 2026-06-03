"""
Committee Reviewer - Specialized multi-agent review with deterministic synthesis.

Architecture Decision Record (ADR):
- Keep correctness/security review LLM-backed via the existing CodeReviewer
- Add deterministic specialist agents to improve recall and reduce orchestration cost
- Use deterministic synthesis first so the final findings are stable and testable
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from .code_reviewer import CodeReviewer
from .types import IssueCategory, PressureFocus, ReviewIssue, ReviewScope, Severity

if TYPE_CHECKING:
    from .review_artifacts import ReviewArtifactStore

logger = logging.getLogger(__name__)

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
_JS_SQL_TEMPLATE_RE = re.compile(r"SELECT\b.*(?:\$\{|req\.|params|query)", re.IGNORECASE)
_PY_SQL_ASSIGN_RE = re.compile(r"=\s*f[\"'].*\bSELECT\b", re.IGNORECASE)
_PY_SQL_EXECUTE_RE = re.compile(r"\.execute\(\s*query\s*\)")
_SECRET_ASSIGN_RE = re.compile(
    r"\b(?:password|passwd|api[_-]?key|secret|token)\b\s*=\s*['\"][^'\"]+['\"]",
    re.IGNORECASE,
)
_JSON_LOADS_RE = re.compile(r"\bjson\.loads\(")
_DIRECT_JSON_KEY_RE = re.compile(r"\b(?:payload|data|response)\s*\[\s*['\"][^'\"]+['\"]\s*\]")
_TS_DEFAULT_ADMIN_RE = re.compile(r"role\s*:\s*data\.role\s*\|\|\s*['\"]admin['\"]")


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
        pressure_challenge: str | None = None,
        telemetry_session_id: str | None = None,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        target_type: str | None = None,
        artifact_store: ReviewArtifactStore | None = None,
        trace_reasons: list[str] | None = None,
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
                    pressure_challenge,
                    telemetry_session_id,
                    workflow_name,
                    review_mode,
                    language,
                    scope.complexity,
                    target_type,
                    artifact_store,
                    trace_reasons,
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
        pressure_challenge: str | None = None,
        telemetry_session_id: str | None = None,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
        artifact_store: ReviewArtifactStore | None = None,
        trace_reasons: list[str] | None = None,
    ) -> list[ReviewIssue]:
        """Run a single review agent."""
        if agent_name == AGENT_CORRECTNESS:
            deterministic = self._deterministic_correctness_review(
                target_path=target_path,
                scope=scope,
                telemetry_session_id=telemetry_session_id,
                language=language,
            )
            if self._should_use_deterministic_fast_path(
                deterministic,
                scope,
                workflow_name,
                review_mode,
            ):
                self._record_agent_tokens(agent_name, 0)
                return [self._tag_issue(issue, agent_name) for issue in deterministic]

            issues, summary = self.code_reviewer.review(
                target_path,
                static_issues,
                telemetry_session_id=telemetry_session_id,
                telemetry_stage="committee_review",
                workflow_name=workflow_name,
                review_mode=review_mode,
                language=language,
                complexity=complexity,
                target_type=target_type,
                artifact_store=artifact_store,
                trace_reasons=trace_reasons,
            )
            if isinstance(summary, dict):
                self._record_agent_tokens(agent_name, int(summary.get("token_usage", 0)))
            combined = [*deterministic, *issues]
            return [self._tag_issue(issue, agent_name) for issue in combined]
        if agent_name == AGENT_ERROR_HANDLING:
            return self._error_handling_review(target_path, scope)
        if agent_name == AGENT_TEST_IMPACT:
            return self._test_impact_review(target_path, scope)
        if agent_name == AGENT_DOCS_IMPACT:
            return self._docs_impact_review(target_path, scope)
        if agent_name == AGENT_PRESSURE:
            return self._pressure_review(
                target_path=target_path,
                pressure_focus=pressure_focus,
                pressure_challenge=pressure_challenge,
                telemetry_session_id=telemetry_session_id,
                workflow_name=workflow_name,
                review_mode=review_mode,
                language=language,
                complexity=complexity,
                target_type=target_type,
                artifact_store=artifact_store,
                trace_reasons=trace_reasons,
            )
        return []

    def consume_agent_tokens(self, agent_name: str) -> int:
        with self._token_lock:
            return self._agent_token_usage.pop(agent_name, 0)

    def _deterministic_correctness_review(
        self,
        *,
        target_path: str,
        scope: ReviewScope,
        telemetry_session_id: str | None,
        language: str | None,
    ) -> list[ReviewIssue]:
        """Return high-confidence local findings for common trivial-file risks."""
        findings: list[ReviewIssue] = []
        for file_path in self._iter_files(target_path, scope.source_files):
            content = self._read_file(file_path)
            if not content:
                continue
            suffix = file_path.suffix.lower()
            if suffix == ".py":
                findings.extend(self._python_correctness_findings(file_path, content))
            elif suffix in {".js", ".jsx", ".mjs", ".cjs"}:
                findings.extend(self._javascript_correctness_findings(file_path, content))
            elif suffix in {".ts", ".tsx"}:
                findings.extend(self._typescript_correctness_findings(file_path, content))

        if findings:
            self._record_lesson_usage_for_deterministic_review(
                target_path=target_path,
                findings=findings,
                session_id=telemetry_session_id,
                language=language,
            )
        return findings

    @staticmethod
    def _should_use_deterministic_fast_path(
        findings: list[ReviewIssue],
        scope: ReviewScope,
        workflow_name: str | None,
        review_mode: str | None,
    ) -> bool:
        """Skip the model only for small, high-confidence smart-review findings."""
        if workflow_name != "review-smart" or review_mode != "review":
            return False
        if scope.complexity not in {"trivial", "small"}:
            return False
        return any(issue.severity.value >= Severity.MEDIUM.value for issue in findings)

    def _record_lesson_usage_for_deterministic_review(
        self,
        *,
        target_path: str,
        findings: list[ReviewIssue],
        session_id: str | None,
        language: str | None,
    ) -> None:
        """Resolve lessons for traceability when the fast path replaces an LLM call."""
        if not session_id:
            return
        resolver = getattr(self.code_reviewer, "lesson_resolver", None)
        resolve_for_prompt = getattr(resolver, "resolve_for_prompt", None)
        if not callable(resolve_for_prompt):
            return
        query_text = "\n".join(
            [
                str(target_path),
                *(f"{issue.title}: {issue.description}" for issue in findings[:5]),
            ]
        )
        try:
            resolve_for_prompt(
                query_text=query_text,
                stage="committee_review",
                session_id=session_id,
                language=language,
            )
        except Exception:
            logger.debug("Deterministic review lesson trace failed", exc_info=True)

    def _python_correctness_findings(self, file_path: Path, content: str) -> list[ReviewIssue]:
        findings: list[ReviewIssue] = []
        if re.search(r"\beval\s*\(", content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_regex(content, re.compile(r"\beval\s*\(")),
                    severity=Severity.CRITICAL,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-95",
                    title="Unsafe eval execution",
                    description="Calling eval on user-controlled input is unsafe code execution.",
                    code_snippet="eval(...)",
                    suggested_fix="Replace eval with a constrained parser or explicit allow-list.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if _SECRET_ASSIGN_RE.search(content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_regex(content, _SECRET_ASSIGN_RE),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-798",
                    title="Hardcoded password or API key secret",
                    description="A hardcoded password, secret, token, or API key is stored in source.",
                    code_snippet="password = '...'",
                    suggested_fix="Load secrets from a managed secret store or environment variable.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if _PY_SQL_ASSIGN_RE.search(content) and _PY_SQL_EXECUTE_RE.search(content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_regex(content, _PY_SQL_ASSIGN_RE),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-89",
                    title="SQL injection via formatted query",
                    description=(
                        "User input reaches a SQL query through string formatting; use a "
                        "parameterized query instead."
                    ),
                    code_snippet="query = f'SELECT ...'",
                    suggested_fix="Use parameterized SQL placeholders and pass values separately.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if _JSON_LOADS_RE.search(content) and _DIRECT_JSON_KEY_RE.search(content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_regex(content, _DIRECT_JSON_KEY_RE),
                    severity=Severity.MEDIUM,
                    category=IssueCategory.CORRECTNESS,
                    cwe_id=None,
                    title="Missing JSON schema validation before key access",
                    description=(
                        "JSON payload fields are indexed directly without schema validation or "
                        "missing key handling."
                    ),
                    code_snippet='payload["key"]',
                    suggested_fix="Validate required JSON keys or use safe defaults before indexing.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        return findings

    def _javascript_correctness_findings(self, file_path: Path, content: str) -> list[ReviewIssue]:
        findings: list[ReviewIssue] = []
        if "res.send" in content and ("req.query" in content or "${query}" in content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_pattern(content, "res.send"),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-79",
                    title="Unsanitized response XSS risk",
                    description="Request query data is written into an HTML response unsanitized.",
                    code_snippet="res.send(...)",
                    suggested_fix="Escape user-controlled output or render through a safe template.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if _JS_SQL_TEMPLATE_RE.search(content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_regex(content, _JS_SQL_TEMPLATE_RE),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-89",
                    title="SQL injection through string concatenation",
                    description="A SQL query is built with request data instead of parameters.",
                    code_snippet="`SELECT ... ${userId}`",
                    suggested_fix="Use parameterized database APIs instead of string interpolation.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if "readFileSync" in content and "req.params" in content:
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_pattern(content, "readFileSync"),
                    severity=Severity.MEDIUM,
                    category=IssueCategory.CORRECTNESS,
                    cwe_id=None,
                    title="File read lacks validation and error handling",
                    description=(
                        "readFileSync uses request file input without path validation or error "
                        "handling, which can expose files or crash the request."
                    ),
                    code_snippet="fs.readFileSync(...)",
                    suggested_fix="Validate the filename, constrain it to an allow-listed root, and handle errors.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        return findings

    def _typescript_correctness_findings(self, file_path: Path, content: str) -> list[ReviewIssue]:
        findings: list[ReviewIssue] = []
        if "password: data.password" in content:
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_pattern(content, "password: data.password"),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-256",
                    title="Plaintext password stored in createUser",
                    description="createUser copies a plaintext password into the stored user object.",
                    code_snippet="password: data.password",
                    suggested_fix="Hash passwords with a password hashing function before storage.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if "getUserData" in content and "fetch(`/api/users/${userId}`)" in content:
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_pattern(content, "getUserData"),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-639",
                    title="Authorization IDOR risk in getUserData",
                    description=(
                        "getUserData fetches arbitrary user IDs without an authorization guard, "
                        "creating an IDOR-style access risk."
                    ),
                    code_snippet="fetch(`/api/users/${userId}`)",
                    suggested_fix="Check the caller is authorized for the requested user before fetching.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if "deleteUser" in content and "fetch(`/api/users/${id}`" in content:
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_pattern(content, "deleteUser"),
                    severity=Severity.MEDIUM,
                    category=IssueCategory.CORRECTNESS,
                    cwe_id=None,
                    title="Unhandled promise in deleteUser",
                    description="deleteUser starts a DELETE request but does not await the promise or handle errors.",
                    code_snippet="fetch(`/api/users/${id}`, { method: 'DELETE' });",
                    suggested_fix="Await the fetch call and handle non-2xx responses.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        if _TS_DEFAULT_ADMIN_RE.search(content):
            findings.append(
                ReviewIssue(
                    file_path=str(file_path),
                    line_number=self._line_number_for_regex(content, _TS_DEFAULT_ADMIN_RE),
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    cwe_id="CWE-266",
                    title="Default admin role assignment",
                    description="New users default to admin when no role is supplied.",
                    code_snippet="role: data.role || 'admin'",
                    suggested_fix="Default to the least-privileged role and require explicit elevation.",
                    auto_fixable=False,
                    source_agent=AGENT_CORRECTNESS,
                )
            )
        return findings

    def synthesize(
        self,
        agent_findings: dict[str, list[ReviewIssue]],
    ) -> list[ReviewIssue]:
        """Deduplicate and merge committee findings into a final issue set.

        Fix: CM-01. Titles are fuzzy-matched (token-set Jaccard similarity) so
        near-duplicate findings like "Missing request timeout" and "Request
        missing timeout" collapse into a single synthesized issue instead of
        being surfaced twice to reviewers.
        """
        grouped: dict[tuple[str, int, str], list[ReviewIssue]] = {}
        # Track representative normalized titles per (file, line) so we can
        # fuzzy-bucket near-duplicates without quadratic cost on large inputs.
        bucket_titles: dict[tuple[str, int], list[str]] = {}
        for issues in agent_findings.values():
            for issue in issues:
                normalized = self._normalize_title(issue.title)
                location = (issue.file_path, issue.line_number)
                representative = self._find_similar_title(
                    normalized, bucket_titles.get(location, [])
                )
                if representative is None:
                    bucket_titles.setdefault(location, []).append(normalized)
                    representative = normalized
                key = (issue.file_path, issue.line_number, representative)
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
        targeted_change = scope.test_scope == "targeted"
        if targeted_change and changed_has_tests:
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
                    severity=Severity.MEDIUM if targeted_change else Severity.LOW,
                    category=IssueCategory.BEST_PRACTICE,
                    cwe_id=None,
                    title=(
                        "Changed source file has no targeted test companion"
                        if targeted_change
                        else "Source file has no targeted test companion"
                    ),
                    description=(
                        "The review touched a source file without a nearby targeted test file."
                        if targeted_change
                        else "This source file has no nearby targeted test file."
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
        pressure_challenge: str | None = None,
        telemetry_session_id: str | None = None,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
        artifact_store: ReviewArtifactStore | None = None,
        trace_reasons: list[str] | None = None,
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
        source_agent = f"{AGENT_PRESSURE}:{pressure_challenge or 'default'}"
        for file_path in files:
            content = self._read_file(file_path)
            if not content:
                continue
            pressure = self.code_reviewer.pressure_review(
                str(file_path),
                content,
                focus,
                challenge_mode=pressure_challenge,
                telemetry_session_id=telemetry_session_id,
                workflow_name=workflow_name,
                review_mode=review_mode,
                language=language,
                complexity=complexity,
                target_type=target_type,
                artifact_store=artifact_store,
                trace_reasons=trace_reasons,
            )
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
                        source_agent=source_agent,
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

    # Jaccard similarity threshold above which two normalized titles are
    # considered duplicates (Fix: CM-01). 0.7 chosen empirically: "missing
    # request timeout" vs "request missing timeout" -> 1.0; "null pointer in X"
    # vs "unused import in X" -> 0.25. Tune via regression if needed.
    _TITLE_DEDUP_THRESHOLD = 0.7

    @classmethod
    def _find_similar_title(cls, candidate: str, existing: list[str]) -> str | None:
        """Return the first existing title that fuzzy-matches ``candidate``."""
        if not candidate or not existing:
            return None
        cand_tokens = set(candidate.split())
        if not cand_tokens:
            return None
        for representative in existing:
            rep_tokens = set(representative.split())
            if not rep_tokens:
                continue
            intersection = cand_tokens & rep_tokens
            union = cand_tokens | rep_tokens
            if union and len(intersection) / len(union) >= cls._TITLE_DEDUP_THRESHOLD:
                return representative
        return None

    @staticmethod
    def _read_file(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            # Fix: CM-02. Surface skipped files in the log so operators can
            # distinguish a missing-file path from an accidentally-empty one.
            logger.info("Committee reviewer skipping %s: %s", path, exc)
            return ""
        except UnicodeDecodeError as exc:
            logger.info("Committee reviewer skipping %s (non-utf8): %s", path, exc)
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
    def _line_number_for_regex(content: str, pattern: re.Pattern[str]) -> int:
        for line_number, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
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
