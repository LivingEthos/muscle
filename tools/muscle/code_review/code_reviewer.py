"""
Code Reviewer - M2.7 powered code analysis.

Uses M2.7 to perform semantic analysis of code issues found by static analyzers,
classifies them by severity and category, and determines fix strategies.

Architecture Decision Record (ADR):
- M2.7 provides semantic understanding beyond static analysis
- Structured JSON output for reliable parsing
- Separate review context to avoid polluting code generation
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..escalation import EscalationRecord, EscalationRecorder
from ..m27_client import M27Client, M27StructuredError, StructuredCallMetadata
from ..optimization.prompt_context import build_telemetry_context, compose_prompt_envelope
from ..structured_io import ReviewFindings
from .review_artifacts import resolve_trace_policy
from .types import IssueCategory, PressureFocus, ReviewIssue, Severity

if TYPE_CHECKING:
    from ..optimization.context_budgeter import ContextBudgeter
    from .review_artifacts import ReviewArtifactStore

logger = logging.getLogger(__name__)

MAX_PARALLEL_FILE_REVIEWS = 5
FILE_CONTENT_CACHE_SIZE = 100
_PRESSURE_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
FRAGILITY_CHALLENGE = "fragility"


@lru_cache(maxsize=FILE_CONTENT_CACHE_SIZE)
def _read_file_cached(file_path: str) -> str | None:
    try:
        path = Path(file_path)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Could not read {file_path}: {e}")
    return None


SYSTEM_PROMPT = """You are an expert code reviewer analyzing code for bugs, security issues,
performance problems, and code quality issues. You receive:
1. Source code files to review
2. Issues found by static analysis tools (with line numbers and messages)

WHY SEVERITY MATTERS: Severity drives triage priority. CRITICAL issues stop releases.
HIGH issues ship but damage users. MEDIUM issues are technical debt. LOW/INFO are polish.

Your task is to:
1. Read each flagged code section
2. Determine if the issue is:
   - VALID and NEEDS FIXING
   - FALSE POSITIVE (ignore it)
   - INTENTIONAL (ignore it)
3. For valid issues, classify by:
   - SEVERITY: CRITICAL(5) > HIGH(4) > MEDIUM(3) > LOW(2) > INFO(1)
   - CATEGORY: security, correctness, performance, style, documentation, best_practice
   - CWE ID if applicable (e.g., CWE-89 for SQL injection)
4. Determine if auto-fixable (code replacement) or requires human intervention
5. If fixable, provide the specific code fix

SEVERITY EXAMPLES (borderline cases):
- CRITICAL: RCE, SQL Injection, hardcoded secrets, unvalidated input leading to injection
- HIGH: Unhandled exceptions, race conditions, memory leaks, use after free, auth bypass
- MEDIUM: Logic errors, inefficient algorithms (O(n²) when O(n) possible), missing error handling
- LOW: Code style, missing comments, variable naming, formatting
- INFO: Suggestions for improvement, best practices

Example borderline: Missing try-catch around file write = MEDIUM (logic error, can fail silently).
Same issue in auth module = HIGH (security/data loss risk).

Your response MUST be valid JSON with this exact structure:
{
  "reviews": [
    {
      "file_path": "src/auth.py",
      "line_number": 42,
      "valid": true,
      "severity": "HIGH",
      "category": "security",
      "cwe_id": "CWE-89",
      "title": "SQL Injection vulnerability",
      "description": "User input directly interpolated into SQL query...",
      "code_snippet": "query = f'SELECT * FROM users WHERE id = {user_id}'",
      "auto_fixable": true,
      "suggested_fix": "query = 'SELECT * FROM users WHERE id = ?'\\ncursor.execute(query, (user_id,))",
      "reasoning": "The user_id is directly string-interpolated into SQL..."
    },
    ...
  ],
  "summary": {
    "total_reviewed": 15,
    "valid_issues": 8,
    "false_positives": 5,
    "intentional": 2,
    "critical": 1,
    "high": 2,
    "medium": 3,
    "low": 2,
    "info": 0
  }
}
"""

PRESSURE_PROMPT = """You are performing a PRESSURE TEST review. This is NOT a normal code review.
Your goal is to CHALLENGE the implementation and expose weaknesses, hidden assumptions, and risks.

Normal reviews find bugs. PRESSURE TESTS find the bugs that normal reviews miss.

For each code section, you MUST question:
1. Is this the RIGHT solution or just A solution?
2. What could go wrong? (failure modes)
3. What assumptions are being made?
4. Is there a simpler, safer approach?
5. What are the security implications?
6. Could this cause data loss or corruption?
7. Are there race conditions or concurrency issues?
8. What happens at scale or under load?

Be ADVERSARIAL. Challenge decisions. Question trade-offs. Expose hidden risks.

Focus areas for this review:
{focus_areas}

Your response MUST be valid JSON with this exact structure:
{{
  "pressure_findings": [
    {{
      "file_path": "src/auth.py",
      "line_number": 42,
      "finding_type": "design_tradeoff|failure_mode|security_risk|concurrency_issue|data_loss_risk|scalability_concern",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "Short punchy title",
      "description": "Detailed explanation of the concern",
      "exploit_scenario": "How an attacker/malicious actor could exploit this",
      "suggested_approach": "A potentially safer/better approach",
      "challenge_question": "Have you considered...?"
    }}
  ],
  "summary": {{
    "total_examined": 15,
    "critical_findings": 2,
    "high_findings": 3,
    "concerns_addressed": 2,
    "confidence_score": 7
}}
}}
"""

FRAGILITY_PRESSURE_PROMPT = """You are performing a FRAGILITY PRE-MORTEM review.
Assume this code works today but is likely to fail after a plausible future change.

Your job is to identify fragile implementation details that normal bug reviews miss:
1. Hidden invariants
2. Load-bearing defaults
3. Shared mutable state
4. Ordering dependencies
5. Non-atomic updates
6. Assumptions about timing, retries, or caller behaviour
7. Future edits that look safe but would trigger production incidents

Focus areas for this review:
{focus_areas}

Return valid JSON with this exact structure:
{{
  "pressure_findings": [
    {{
      "file_path": "src/service.py",
      "line_number": 42,
      "finding_type": "fragility",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "title": "Short incident title",
      "description": "Why the current code is fragile",
      "incident_title": "Human-readable future incident title",
      "fragility_type": "hidden_invariant|ordering_dependency|load_bearing_default|shared_mutable_state|non_atomic_update|reliability_gap",
      "plausible_triggering_change": "A realistic future edit or scale change",
      "failure_surface": "How the failure would show up in production",
      "hardening_suggestions": [
        "Concrete hardening step 1",
        "Concrete hardening step 2"
      ],
      "suggested_approach": "Concise hardening direction",
      "challenge_question": "Question the team should answer before shipping"
    }}
  ],
  "summary": {{
    "total_examined": 15,
    "critical_findings": 2,
    "high_findings": 3,
    "concerns_addressed": 0,
    "confidence_score": 7
  }}
}}
"""


class PressureFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_path: str = ""
    line_number: int = Field(default=1, ge=1)
    finding_type: str = "design_tradeoff"
    severity: str
    title: str
    description: str
    exploit_scenario: str = ""
    suggested_approach: str = ""
    challenge_question: str = ""

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in _PRESSURE_SEVERITIES:
            raise ValueError(f"Unsupported severity: {value}")
        return normalized


class PressureSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_examined: int = 0
    critical_findings: int = 0
    high_findings: int = 0
    concerns_addressed: int = 0
    confidence_score: int = 0


class PressureReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pressure_findings: list[PressureFinding] = Field(default_factory=list)
    summary: PressureSummary = Field(default_factory=PressureSummary)


class FragilityPressureFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_path: str = ""
    line_number: int = Field(default=1, ge=1)
    finding_type: str = "fragility"
    severity: str
    title: str
    description: str
    incident_title: str = ""
    fragility_type: str = "hidden_invariant"
    plausible_triggering_change: str = ""
    failure_surface: str = ""
    hardening_suggestions: list[str] = Field(default_factory=list)
    suggested_approach: str = ""
    challenge_question: str = ""

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in _PRESSURE_SEVERITIES:
            raise ValueError(f"Unsupported severity: {value}")
        return normalized


class FragilityPressureReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pressure_findings: list[FragilityPressureFinding] = Field(default_factory=list)
    summary: PressureSummary = Field(default_factory=PressureSummary)


class CodeReviewer:
    def __init__(
        self,
        m27_client: M27Client,
        max_issues_per_batch: int = 20,
        context_budgeter: ContextBudgeter | None = None,
        project_path: str | None = None,
        lesson_resolver: object | None = None,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        self.m27_client = m27_client
        self.max_issues_per_batch = max_issues_per_batch
        self.context_budgeter = context_budgeter
        self.project_path = project_path or str(Path.cwd())
        self.lesson_resolver = lesson_resolver
        self.include_patterns = include_patterns or ["*"]
        default_excludes = [
            ".git",
            ".hg",
            ".svn",
            ".muscle",
            ".venv",
            "venv",
            "node_modules",
            "dist",
            "build",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
        ]
        self.exclude_patterns = list(dict.fromkeys([*default_excludes, *(exclude_patterns or [])]))

    def _should_review_file(self, file_path: Path, base_dir: Path) -> bool:
        try:
            rel_path = file_path.relative_to(base_dir)
        except ValueError:
            rel_path = file_path
        normalized = rel_path.as_posix()
        name = file_path.name
        for pattern in self.exclude_patterns:
            if pattern in file_path.parts or fnmatch(name, pattern) or fnmatch(normalized, pattern):
                return False
        return any(
            fnmatch(name, pattern) or fnmatch(normalized, pattern)
            for pattern in self.include_patterns
        )

    def _emit_schema_escalation(
        self, file_path: str, attempt_count: int, telemetry_session_id: str | None = None
    ) -> None:
        """Emit an escalation when M2.7 exhausts all retries without producing valid JSON."""
        session_id = telemetry_session_id or "unknown"
        recorder = EscalationRecorder(self.project_path)
        recorder.emit(
            EscalationRecord(
                session_id=session_id,
                reason="schema_failure",
                source_module="code_reviewer",
                issue_summary=(
                    f"M2.7 failed to produce valid JSON for {file_path} "
                    f"after {attempt_count} attempt(s)."
                ),
                attempt_count=attempt_count,
            )
        )

    @staticmethod
    def _prepare_trace_metadata(
        artifact_store: ReviewArtifactStore | None,
        *,
        prompt_envelope: Any,
        telemetry_stage: str,
        trace_reasons: list[str] | None,
    ) -> dict[str, Any]:
        if artifact_store is None or not prompt_envelope.call_id:
            return {
                "trace_capture_policy": resolve_trace_policy(*(trace_reasons or []))[0],
                "trace_capture_reasons": list(trace_reasons or []),
                "trace_pointers": {},
            }
        trace_policy, active_trace_reasons = resolve_trace_policy(*(trace_reasons or []))
        return artifact_store.prepare_llm_trace(
            call_id=prompt_envelope.call_id,
            stage=telemetry_stage,
            prompt_text=prompt_envelope.prompt,
            context_strategy=prompt_envelope.context_strategy,
            context_chars=prompt_envelope.context_chars,
            prompt_metadata=prompt_envelope.metadata,
            trace_policy=trace_policy,
            trace_reasons=active_trace_reasons,
        )

    @staticmethod
    def _finalize_trace_metadata(
        artifact_store: ReviewArtifactStore | None,
        *,
        call_id: str | None,
        telemetry_stage: str,
        trace_metadata: dict[str, Any],
        status: str,
        parse_success: bool | None,
        validation_success: bool | None,
        trace_reasons: list[str] | None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace_policy, active_trace_reasons = resolve_trace_policy(*(trace_reasons or []))
        payload = {
            "call_id": call_id,
            "stage": telemetry_stage,
            "status": status,
            "parse_success": parse_success,
            "validation_success": validation_success,
            "trace_policy": trace_policy,
            "trace_reasons": active_trace_reasons,
        }
        if details:
            payload.update(details)
        if artifact_store is not None and call_id:
            artifact_store.finalize_llm_trace(
                call_id=call_id,
                stage=telemetry_stage,
                validation_payload=payload,
            )
        return {
            "trace_capture_policy": trace_policy,
            "trace_capture_reasons": active_trace_reasons,
            "trace_pointers": dict(trace_metadata.get("trace_pointers", {})),
        }

    def review(
        self,
        target_path: str,
        issues: list[dict],
        telemetry_session_id: str | None = None,
        telemetry_stage: str = "semantic_review",
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
        supplemental_context: str = "",
        artifact_store: ReviewArtifactStore | None = None,
        trace_reasons: list[str] | None = None,
    ) -> tuple[list[ReviewIssue], dict]:
        target = Path(target_path)
        if target.is_file():
            base_dir = target.parent
        else:
            base_dir = target
        issues_by_file: dict[str, list[dict]] = {}

        for issue in issues:
            file_path = issue.get("file_path", "")
            if file_path not in issues_by_file:
                issues_by_file[file_path] = []
            issues_by_file[file_path].append(issue)

        all_reviews: list[ReviewIssue] = []
        summary = {
            "total_reviewed": 0,
            "valid_issues": 0,
            "false_positives": 0,
            "intentional": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
            "token_usage": 0,
            "files_failed": 0,
            "files_skipped": 0,
            "scope_limited": False,
        }

        if issues_by_file:
            files_to_review = {}
            for file_path, file_issues in issues_by_file.items():
                full_path = (
                    base_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
                )
                if self._should_review_file(full_path, base_dir):
                    files_to_review[file_path] = file_issues
                else:
                    summary["files_skipped"] += 1
                    summary["scope_limited"] = True
        else:
            files_to_review = {}
            if target.is_file():
                if self._should_review_file(target, base_dir):
                    files_to_review[str(target)] = []
                else:
                    summary["files_skipped"] += 1
                    summary["scope_limited"] = True
            else:
                for ext in (
                    ".py",
                    ".js",
                    ".ts",
                    ".jsx",
                    ".tsx",
                    ".go",
                    ".rs",
                    ".cpp",
                    ".cc",
                    ".c",
                    ".java",
                ):
                    for f in sorted(target.rglob(f"*{ext}")):
                        if not self._should_review_file(f, base_dir):
                            summary["files_skipped"] += 1
                            summary["scope_limited"] = True
                            continue
                        rel = str(f.relative_to(base_dir)) if f.parent != base_dir else f.name
                        files_to_review[rel] = []

        proactive = not issues_by_file

        def review_single_file(
            file_path: str, file_issues: list[dict]
        ) -> tuple[list[ReviewIssue], dict]:
            file_issues = file_issues[: self.max_issues_per_batch]
            code_content = ""
            full_path = (
                base_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)
            )
            cached_content = _read_file_cached(str(full_path))
            if cached_content is not None:
                code_content = cached_content

            return self._review_file(
                file_path,
                code_content,
                file_issues,
                proactive,
                telemetry_session_id=telemetry_session_id,
                telemetry_stage=telemetry_stage,
                workflow_name=workflow_name,
                review_mode=review_mode,
                language=language,
                complexity=complexity,
                target_type=target_type,
                supplemental_context=supplemental_context,
                artifact_store=artifact_store,
                trace_reasons=trace_reasons,
            )

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FILE_REVIEWS) as executor:
            future_to_file = {
                executor.submit(review_single_file, fp, fi): fp
                for fp, fi in files_to_review.items()
            }

            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    reviews, file_summary = future.result()
                    all_reviews.extend(reviews)

                    summary["total_reviewed"] += file_summary["total_reviewed"]
                    summary["valid_issues"] += file_summary["valid_issues"]
                    summary["false_positives"] += file_summary["false_positives"]
                    summary["intentional"] += file_summary["intentional"]
                    summary["critical"] += file_summary["critical"]
                    summary["high"] += file_summary["high"]
                    summary["medium"] += file_summary["medium"]
                    summary["low"] += file_summary["low"]
                    summary["info"] += file_summary["info"]
                    summary["token_usage"] += file_summary.get("token_usage", 0)
                except Exception as e:
                    logger.warning(f"File review failed for {file_path}: {e}")
                    summary["files_failed"] += 1

        return all_reviews, summary

    def _review_file(
        self,
        file_path: str,
        code_content: str,
        issues: list[dict],
        proactive: bool = False,
        telemetry_session_id: str | None = None,
        telemetry_stage: str = "semantic_review",
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
        supplemental_context: str = "",
        artifact_store: ReviewArtifactStore | None = None,
        trace_reasons: list[str] | None = None,
    ) -> tuple[list[ReviewIssue], dict]:
        review_budget = (
            self.context_budgeter.build_semantic_review_budget(
                file_path=file_path,
                code_content=code_content,
                issues=issues,
                proactive=proactive,
                escalate=False,
            )
            if self.context_budgeter
            else None
        )
        prompt_code = (
            review_budget.content
            if review_budget is not None
            else self._truncate_code(code_content, 500)
        )

        if proactive:
            user_prompt = f"""Proactively review this file for bugs, security vulnerabilities, and code quality issues: {file_path}

Source code:
```{self._get_lang_from_ext(file_path)}
{prompt_code}
```

No static analysis issues were found, so conduct a thorough semantic review looking for:
- Logic errors and bugs
- Security vulnerabilities (injection, authentication, authorization issues)
- Race conditions and concurrency issues
- Memory safety problems
- Error handling gaps
- Performance anti-patterns
- API misuse patterns

Provide your findings in JSON format."""
        else:
            user_prompt = f"""Review this file: {file_path}

Source code:
```{self._get_lang_from_ext(file_path)}
{prompt_code}
```

Static analysis issues found:
{json.dumps(issues, indent=2)}

Provide your review in JSON format."""
        if supplemental_context:
            user_prompt += (
                f"\n\n{supplemental_context}\n\n"
                "Note: the dependency context above is partial. Use it only when directly "
                "relevant to the issues found. Do not invent dependency internals beyond "
                "the supplied excerpts."
            )

        base_context_strategy = review_budget.strategy if review_budget else "truncated_file_slice"
        prompt_envelope = compose_prompt_envelope(
            base_prompt=user_prompt,
            lesson_resolver=self.lesson_resolver,
            query_text=f"{file_path}\n{json.dumps(issues, sort_keys=True)}",
            stage=telemetry_stage,
            base_context_strategy=base_context_strategy,
            session_id=telemetry_session_id,
            language=language or self._get_lang_from_ext(file_path),
        )
        user_prompt = prompt_envelope.prompt
        trace_metadata = self._prepare_trace_metadata(
            artifact_store,
            prompt_envelope=prompt_envelope,
            telemetry_stage=telemetry_stage,
            trace_reasons=trace_reasons,
        )

        telemetry_context = build_telemetry_context(
            project_path=self.project_path,
            session_id=telemetry_session_id,
            stage=telemetry_stage,
            prompt_envelope=prompt_envelope,
            trace_artifacts=trace_metadata["trace_pointers"],
            trace_policy=trace_metadata["trace_capture_policy"],
            trace_reasons=trace_metadata["trace_capture_reasons"],
            workflow_name=workflow_name,
            review_mode=review_mode,
            language=language or self._get_lang_from_ext(file_path),
            complexity=complexity,
            target_type=target_type,
            metadata={
                "file_path": file_path,
                "issue_count": len(issues),
                "proactive": proactive,
            },
        )
        try:
            result, metadata = self.m27_client.chat_structured(
                schema=ReviewFindings,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                telemetry_context=telemetry_context,
                include_metadata=True,
            )
            logger.info(
                "CodeReviewer used %s tokens for %s (cache_hit=%s)",
                metadata.usage.total,
                file_path,
                metadata.cache_hit,
            )
            final_trace = self._finalize_trace_metadata(
                artifact_store,
                call_id=telemetry_context.call_id if telemetry_context else prompt_envelope.call_id,
                telemetry_stage=telemetry_stage,
                trace_metadata=trace_metadata,
                status="validated",
                parse_success=True,
                validation_success=True,
                trace_reasons=trace_reasons,
                details={
                    "file_path": file_path,
                    "issue_count": len(issues),
                    "token_usage": metadata.usage.total,
                    "cache_hit": metadata.cache_hit,
                },
            )
            if telemetry_context is not None:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    metadata_updates=final_trace,
                )
            return self._structured_review_result(result, metadata, file_path, proactive)
        except M27StructuredError as exc:
            logger.error("Structured review failed for %s: %s", file_path, exc)
            final_trace = self._finalize_trace_metadata(
                artifact_store,
                call_id=telemetry_context.call_id if telemetry_context else prompt_envelope.call_id,
                telemetry_stage=telemetry_stage,
                trace_metadata=trace_metadata,
                status="schema_failure",
                parse_success=False,
                validation_success=False,
                trace_reasons=[*(trace_reasons or []), "schema_failure"],
                details={"file_path": file_path, "schema_error": str(exc)},
            )
            if telemetry_context is not None:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    metadata_updates=final_trace,
                )
            if (
                self.context_budgeter
                and not proactive
                and review_budget
                and not review_budget.escalated
            ):
                expanded_budget = self.context_budgeter.build_semantic_review_budget(
                    file_path=file_path,
                    code_content=code_content,
                    issues=issues,
                    proactive=proactive,
                    escalate=True,
                )
                retry_prompt = f"""Review this file: {file_path}

Source code:
```{self._get_lang_from_ext(file_path)}
{expanded_budget.content}
```

Static analysis issues found:
{json.dumps(issues, indent=2)}

Provide your review in JSON format."""
                retry_envelope = compose_prompt_envelope(
                    base_prompt=retry_prompt,
                    lesson_resolver=self.lesson_resolver,
                    query_text=f"{file_path}\n{json.dumps(issues, sort_keys=True)}",
                    stage=telemetry_stage,
                    base_context_strategy=expanded_budget.strategy,
                    session_id=telemetry_session_id,
                    language=language or self._get_lang_from_ext(file_path),
                )
                retry_trace_metadata = self._prepare_trace_metadata(
                    artifact_store,
                    prompt_envelope=retry_envelope,
                    telemetry_stage=telemetry_stage,
                    trace_reasons=[*(trace_reasons or []), "schema_failure"],
                )
                retry_context = build_telemetry_context(
                    project_path=self.project_path,
                    session_id=telemetry_session_id,
                    stage=telemetry_stage,
                    prompt_envelope=retry_envelope,
                    trace_artifacts=retry_trace_metadata["trace_pointers"],
                    trace_policy=retry_trace_metadata["trace_capture_policy"],
                    trace_reasons=retry_trace_metadata["trace_capture_reasons"],
                    workflow_name=workflow_name,
                    review_mode=review_mode,
                    language=language or self._get_lang_from_ext(file_path),
                    complexity=complexity,
                    target_type=target_type,
                    metadata={
                        "file_path": file_path,
                        "retry_reason": "schema_failure",
                        "proactive": proactive,
                    },
                )
                try:
                    result, metadata = self.m27_client.chat_structured(
                        schema=ReviewFindings,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": retry_envelope.prompt},
                        ],
                        telemetry_context=retry_context,
                        include_metadata=True,
                    )
                    retry_final_trace = self._finalize_trace_metadata(
                        artifact_store,
                        call_id=retry_context.call_id if retry_context is not None else None,
                        telemetry_stage=telemetry_stage,
                        trace_metadata=retry_trace_metadata,
                        status="validated_after_retry",
                        parse_success=True,
                        validation_success=True,
                        trace_reasons=[*(trace_reasons or []), "schema_failure"],
                        details={
                            "file_path": file_path,
                            "issue_count": len(issues),
                            "retry_reason": "schema_failure",
                            "token_usage": metadata.usage.total,
                            "cache_hit": metadata.cache_hit,
                        },
                    )
                    if retry_context is not None:
                        self.m27_client.update_telemetry_call(
                            retry_context.call_id,
                            metadata_updates=retry_final_trace,
                        )
                    return self._structured_review_result(result, metadata, file_path, proactive)
                except M27StructuredError as retry_exc:
                    logger.error(
                        "Escalated structured review failed for %s: %s", file_path, retry_exc
                    )
                    retry_final_trace = self._finalize_trace_metadata(
                        artifact_store,
                        call_id=retry_context.call_id if retry_context is not None else None,
                        telemetry_stage=telemetry_stage,
                        trace_metadata=retry_trace_metadata,
                        status="schema_failure",
                        parse_success=False,
                        validation_success=False,
                        trace_reasons=[*(trace_reasons or []), "schema_failure"],
                        details={
                            "file_path": file_path,
                            "retry_reason": "schema_failure",
                            "schema_error": str(retry_exc),
                        },
                    )
                    if retry_context is not None:
                        self.m27_client.update_telemetry_call(
                            retry_context.call_id,
                            metadata_updates=retry_final_trace,
                        )
                    self._emit_schema_escalation(
                        file_path=file_path,
                        attempt_count=4,
                        telemetry_session_id=telemetry_session_id,
                    )
            else:
                self._emit_schema_escalation(
                    file_path=file_path,
                    attempt_count=3,
                    telemetry_session_id=telemetry_session_id,
                )
            return self._empty_review_summary(len(issues), 0)

    def _structured_review_result(
        self,
        result: ReviewFindings,
        metadata: StructuredCallMetadata,
        default_file_path: str,
        proactive: bool,
    ) -> tuple[list[ReviewIssue], dict[str, int]]:
        reviews = self._reviews_from_structured(result, default_file_path)
        summary = result.summary.model_dump()
        summary["token_usage"] = metadata.usage.total
        summary["cache_hit"] = int(metadata.cache_hit)
        summary["proactive"] = int(proactive)
        return reviews, summary

    @classmethod
    def _reviews_from_structured(
        cls,
        payload: ReviewFindings,
        default_file_path: str,
    ) -> list[ReviewIssue]:
        reviews: list[ReviewIssue] = []
        for item in payload.reviews:
            if not item.valid:
                continue

            reviews.append(
                ReviewIssue(
                    file_path=item.file_path or default_file_path,
                    line_number=item.line_number,
                    severity=cls._parse_severity(item.severity),
                    category=cls._parse_category(item.category),
                    cwe_id=item.cwe_id,
                    title=item.title or "Code issue",
                    description=item.description,
                    code_snippet=item.code_snippet,
                    suggested_fix=item.suggested_fix,
                    auto_fixable=item.auto_fixable,
                )
            )
        return reviews

    @staticmethod
    def _empty_review_summary(
        issue_count: int,
        token_usage: int,
    ) -> tuple[list[ReviewIssue], dict[str, int]]:
        return [], {
            "total_reviewed": issue_count,
            "valid_issues": 0,
            "false_positives": issue_count,
            "intentional": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
            "token_usage": token_usage,
        }

    @staticmethod
    def _parse_severity(s: str) -> Severity:
        s = s.upper()
        mapping = {
            "CRITICAL": Severity.CRITICAL,
            "HIGH": Severity.HIGH,
            "MEDIUM": Severity.MEDIUM,
            "LOW": Severity.LOW,
            "INFO": Severity.INFO,
        }
        return mapping.get(s, Severity.MEDIUM)

    @staticmethod
    def _load_json_response(response_text: str) -> dict[str, Any]:
        json_text = response_text.strip()
        if not json_text:
            raise json.JSONDecodeError("Response is empty", response_text, 0)
        if json_text.startswith("```"):
            lines = json_text.splitlines()
            json_lines = [line for line in lines if not line.startswith("```")]
            json_text = "\n".join(json_lines).strip()
        payload = json.loads(json_text)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Response is not a JSON object", json_text, 0)
        return payload

    @classmethod
    def _reviews_from_payload(cls, payload: dict, default_file_path: str) -> list[ReviewIssue]:
        reviews: list[ReviewIssue] = []
        for item in payload.get("reviews", []):
            if not item.get("valid", False):
                continue

            reviews.append(
                ReviewIssue(
                    file_path=item.get("file_path", default_file_path),
                    line_number=item.get("line_number", 0),
                    severity=cls._parse_severity(item.get("severity", "MEDIUM")),
                    category=cls._parse_category(item.get("category", "best_practice")),
                    cwe_id=item.get("cwe_id"),
                    title=item.get("title", "Code issue"),
                    description=item.get("description", ""),
                    code_snippet=item.get("code_snippet", ""),
                    suggested_fix=item.get("suggested_fix"),
                    auto_fixable=item.get("auto_fixable", False),
                )
            )
        return reviews

    @staticmethod
    def _parse_category(s: str) -> IssueCategory:
        s = s.lower()
        mapping = {
            "security": IssueCategory.SECURITY,
            "correctness": IssueCategory.CORRECTNESS,
            "performance": IssueCategory.PERFORMANCE,
            "style": IssueCategory.STYLE,
            "documentation": IssueCategory.DOCUMENTATION,
            "best_practice": IssueCategory.BEST_PRACTICE,
        }
        return mapping.get(s, IssueCategory.BEST_PRACTICE)

    @staticmethod
    def _get_lang_from_ext(file_path: str) -> str:
        ext = Path(file_path).suffix.lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".c": "c",
            ".h": "c",
            ".java": "java",
        }
        return lang_map.get(ext, "text")

    @staticmethod
    def _truncate_code(code: str, max_lines: int) -> str:
        lines = code.split("\n")
        if len(lines) <= max_lines:
            return code
        return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"

    def pressure_review(
        self,
        target_path: str,
        code_content: str,
        pressure_focus: PressureFocus,
        artifact_store: ReviewArtifactStore | None = None,
        challenge_mode: str | None = None,
        telemetry_session_id: str | None = None,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
        trace_reasons: list[str] | None = None,
    ) -> dict:
        focus_areas = []
        if pressure_focus.design_tradeoffs:
            focus_areas.append("- Design trade-offs and alternative approaches")
        if pressure_focus.failure_modes:
            focus_areas.append("- Failure modes and error handling gaps")
        if pressure_focus.race_conditions:
            focus_areas.append("- Race conditions and concurrency issues")
        if pressure_focus.auth_security:
            focus_areas.append("- Authentication and authorization flaws")
        if pressure_focus.data_loss:
            focus_areas.append("- Data loss and corruption risks")
        if pressure_focus.rollback:
            focus_areas.append("- Rollback and recovery concerns")
        if pressure_focus.reliability:
            focus_areas.append("- Reliability and error resilience")
        if pressure_focus.custom_focus:
            focus_areas.append(f"- Custom focus: {pressure_focus.custom_focus}")

        if not focus_areas:
            focus_areas = ["- General code quality and potential issues"]

        focus_text = "\n".join(focus_areas)
        is_fragility = challenge_mode == FRAGILITY_CHALLENGE
        challenge_label = challenge_mode or "default"

        prompt_title = (
            "Perform a FRAGILITY PRE-MORTEM on this code."
            if is_fragility
            else ("Perform a PRESSURE TEST on this code. Be adversarial.")
        )
        goal_text = (
            "Assume the current code passes today, then identify the future incident most likely "
            "to appear after a plausible edit, scaling event, or timing change."
            if is_fragility
            else "Your goal is to expose weaknesses, hidden risks, and assumptions. "
            "Think like an attacker or someone who wants to break this code."
        )
        user_prompt = f"""{prompt_title}

Target file: {target_path}

Code:
```{self._get_lang_from_ext(target_path)}
{self._truncate_code(code_content, 500)}
```

Focus areas for this review:
{focus_text}

{goal_text}
"""

        prompt_envelope = compose_prompt_envelope(
            base_prompt=user_prompt,
            lesson_resolver=self.lesson_resolver,
            query_text=f"{target_path}\npressure:{challenge_label}\n{focus_text}",
            stage="pressure_review",
            base_context_strategy="pressure_prompt",
            session_id=telemetry_session_id,
            language=language or self._get_lang_from_ext(target_path),
        )
        trace_metadata = self._prepare_trace_metadata(
            artifact_store,
            prompt_envelope=prompt_envelope,
            telemetry_stage="pressure_review",
            trace_reasons=trace_reasons,
        )
        telemetry_context = build_telemetry_context(
            project_path=self.project_path,
            session_id=telemetry_session_id,
            stage="pressure_review",
            prompt_envelope=prompt_envelope,
            trace_artifacts=trace_metadata["trace_pointers"],
            trace_policy=trace_metadata["trace_capture_policy"],
            trace_reasons=trace_metadata["trace_capture_reasons"],
            workflow_name=workflow_name,
            review_mode=review_mode,
            language=language or self._get_lang_from_ext(target_path),
            complexity=complexity,
            target_type=target_type,
            metadata={
                "file_path": target_path,
                "pressure_challenge": challenge_label,
            },
        )
        system_prompt = (FRAGILITY_PRESSURE_PROMPT if is_fragility else PRESSURE_PROMPT).format(
            focus_areas=focus_text
        )
        schema = FragilityPressureReviewResponse if is_fragility else PressureReviewResponse

        try:
            result, metadata = self.m27_client.chat_structured(
                schema=schema,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_envelope.prompt},
                ],
                telemetry_context=telemetry_context,
                include_metadata=True,
            )
            data = dict(result.model_dump())
            if is_fragility:
                data = self._normalize_fragility_payload(data)
            data.setdefault("summary", {})
            if isinstance(data["summary"], dict):
                data["summary"]["token_usage"] = metadata.usage.total
                data["summary"]["cache_hit"] = int(metadata.cache_hit)
                data["summary"]["challenge_mode"] = challenge_label
            final_trace = self._finalize_trace_metadata(
                artifact_store,
                call_id=telemetry_context.call_id if telemetry_context else prompt_envelope.call_id,
                telemetry_stage="pressure_review",
                trace_metadata=trace_metadata,
                status="validated",
                parse_success=True,
                validation_success=True,
                trace_reasons=trace_reasons,
                details={
                    "file_path": target_path,
                    "pressure_challenge": challenge_label,
                    "token_usage": metadata.usage.total,
                    "cache_hit": metadata.cache_hit,
                },
            )
            if telemetry_context is not None:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    metadata_updates=final_trace,
                )
            return data
        except M27StructuredError as e:
            logger.error("Failed to parse pressure review response for %s: %s", target_path, e)
            final_trace = self._finalize_trace_metadata(
                artifact_store,
                call_id=telemetry_context.call_id if telemetry_context else prompt_envelope.call_id,
                telemetry_stage="pressure_review",
                trace_metadata=trace_metadata,
                status="pressure_review_parse_failure",
                parse_success=False,
                validation_success=False,
                trace_reasons=[*(trace_reasons or []), "pressure_review_parse_failure"],
                details={
                    "file_path": target_path,
                    "pressure_challenge": challenge_label,
                    "parse_error": str(e),
                },
            )
            if telemetry_context is not None:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    metadata_updates=final_trace,
                )
            return self._pressure_parse_failure(
                target_path=target_path,
                raw_response="",
                parse_error=str(e),
                token_usage=0,
                artifact_store=artifact_store,
            )

    @staticmethod
    def _normalize_fragility_payload(payload: dict[str, Any]) -> dict[str, Any]:
        findings = payload.get("pressure_findings", [])
        normalized_findings: list[dict[str, Any]] = []
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            hardening_suggestions = finding.get("hardening_suggestions", [])
            if isinstance(hardening_suggestions, list):
                suggestions = [
                    str(item).strip() for item in hardening_suggestions if str(item).strip()
                ]
            else:
                suggestions = [str(hardening_suggestions).strip()] if hardening_suggestions else []
            suggested_approach = str(finding.get("suggested_approach") or "").strip()
            if not suggested_approach and suggestions:
                suggested_approach = " ".join(f"{item}" for item in suggestions[:2])
            finding["suggested_approach"] = suggested_approach
            finding["hardening_suggestions"] = suggestions
            finding["finding_type"] = str(finding.get("finding_type") or "fragility")
            normalized_findings.append(finding)
        payload["pressure_findings"] = normalized_findings
        return payload

    @staticmethod
    def _pressure_parse_failure(
        target_path: str,
        raw_response: str,
        parse_error: str,
        token_usage: int,
        artifact_store: ReviewArtifactStore | None = None,
    ) -> dict[str, Any]:
        payload = {
            "pressure_findings": [],
            "summary": {
                "total": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
                "token_usage": token_usage,
                "parse_error": parse_error,
            },
        }
        if artifact_store is not None:
            artifact_store.write_diagnostic(
                "pressure-parse-failure",
                {
                    "target_path": target_path,
                    "parse_error": parse_error,
                    "token_usage": token_usage,
                },
            )
            artifact_store.write_raw_response("pressure-raw-response", raw_response)
        return payload
