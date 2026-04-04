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
from functools import lru_cache
from pathlib import Path

from ..m27_client import M27Client
from .types import IssueCategory, PressureFocus, ReviewIssue, Severity

logger = logging.getLogger(__name__)

MAX_PARALLEL_FILE_REVIEWS = 5
FILE_CONTENT_CACHE_SIZE = 100


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


class CodeReviewer:
    def __init__(
        self,
        m27_client: M27Client,
        max_issues_per_batch: int = 20,
    ):
        self.m27_client = m27_client
        self.max_issues_per_batch = max_issues_per_batch

    def review(
        self,
        target_path: str,
        issues: list[dict],
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
        }

        if issues_by_file:
            files_to_review = issues_by_file
        else:
            files_to_review = {}
            if target.is_file():
                files_to_review[str(target)] = []
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

            return self._review_file(file_path, code_content, file_issues, proactive)

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
                except Exception as e:
                    logger.warning(f"File review failed for {file_path}: {e}")

        return all_reviews, summary

    def _review_file(
        self,
        file_path: str,
        code_content: str,
        issues: list[dict],
        proactive: bool = False,
    ) -> tuple[list[ReviewIssue], dict]:
        if proactive:
            user_prompt = f"""Proactively review this file for bugs, security vulnerabilities, and code quality issues: {file_path}

Source code:
```{self._get_lang_from_ext(file_path)}
{self._truncate_code(code_content, 500)}
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
{self._truncate_code(code_content, 500)}
```

Static analysis issues found:
{json.dumps(issues, indent=2)}

Provide your review in JSON format."""

        max_retries = 3
        response_text = ""
        usage = None

        for attempt in range(max_retries):
            response_text, usage = self.m27_client.chat(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )

            logger.info(
                f"CodeReviewer used {usage.total} tokens for {file_path} (attempt {attempt + 1})"
            )

            if response_text and response_text.strip():
                break

            logger.warning(
                f"Empty response from M2.7 for {file_path}, attempt {attempt + 1}/{max_retries}"
            )

        if not response_text or not response_text.strip():
            logger.warning(f"All {max_retries} attempts returned empty response for {file_path}")
            return [], {
                "total_reviewed": len(issues),
                "valid_issues": 0,
                "false_positives": len(issues),
                "intentional": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
            }

        try:
            json_text = response_text.strip()
            if json_text.startswith("```"):
                lines = json_text.split("\n")
                json_lines = [
                    line
                    for line in lines
                    if not line.startswith("```") and not line.startswith("json")
                ]
                json_text = "\n".join(json_lines).strip()
            data = json.loads(json_text)
            reviews = []
            for item in data.get("reviews", []):
                if not item.get("valid", False):
                    continue

                severity_str = item.get("severity", "MEDIUM")
                severity = self._parse_severity(severity_str)
                category_str = item.get("category", "best_practice")
                category = self._parse_category(category_str)

                reviews.append(
                    ReviewIssue(
                        file_path=item.get("file_path", file_path),
                        line_number=item.get("line_number", 0),
                        severity=severity,
                        category=category,
                        cwe_id=item.get("cwe_id"),
                        title=item.get("title", "Code issue"),
                        description=item.get("description", ""),
                        code_snippet=item.get("code_snippet", ""),
                        suggested_fix=item.get("suggested_fix"),
                        auto_fixable=item.get("auto_fixable", False),
                    )
                )

            summary = data.get("summary", {})
            return reviews, summary

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse M2.7 response: {e}")
            return [], {
                "total_reviewed": len(issues),
                "valid_issues": 0,
                "false_positives": len(issues),
                "intentional": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "info": 0,
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

        user_prompt = f"""Perform a PRESSURE TEST on this code. Be adversarial.

Target file: {target_path}

Code:
```{self._get_lang_from_ext(target_path)}
{self._truncate_code(code_content, 500)}
```

Focus areas for this pressure test:
{focus_text}

Your goal is to expose weaknesses, hidden risks, and assumptions. Think like an attacker or someone who wants to break this code.
"""

        max_retries = 3
        response_text = ""

        for attempt in range(max_retries):
            response_text, usage = self.m27_client.chat(
                messages=[
                    {"role": "system", "content": PRESSURE_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )

            logger.info(f"Pressure review used {usage.total} tokens (attempt {attempt + 1})")

            if response_text and response_text.strip():
                break

        if not response_text or not response_text.strip():
            logger.warning("All attempts returned empty response for pressure review")
            return {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0}}

        try:
            json_text = response_text.strip()
            if json_text.startswith("```"):
                lines = json_text.split("\n")
                json_lines = [
                    line
                    for line in lines
                    if not line.startswith("```") and not line.startswith("json")
                ]
                json_text = "\n".join(json_lines).strip()
            data = json.loads(json_text)
            assert isinstance(data, dict)
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"Initial JSON parse failed: {e}, attempting to extract valid JSON")
            try:
                import re

                json_text_clean = json_text.strip()
                if json_text_clean.startswith("```"):
                    lines = json_text_clean.split("\n")
                    json_lines = [line for line in lines if not line.strip().startswith("```")]
                    json_text_clean = "\n".join(json_lines).strip()

                partial_match = re.search(r"\{[\s\S]*", json_text_clean)
                if not partial_match:
                    logger.error(f"Failed to parse pressure review response: {e}")
                    return {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0}}

                partial = partial_match.group(0)

                valid_endings = ['"}', ",'", "}]", "}}", '"]', "}"]
                for trail in valid_endings:
                    if partial.endswith(trail):
                        try:
                            data = json.loads(partial)
                            if isinstance(data, dict) and "pressure_findings" in data:
                                valid_findings = [
                                    f
                                    for f in data.get("pressure_findings", [])
                                    if isinstance(f, dict) and "title" in f
                                ]
                                data["pressure_findings"] = valid_findings
                                logger.info(
                                    f"Recovered partial JSON with {len(valid_findings)} valid findings"
                                )
                                return data
                        except json.JSONDecodeError:
                            pass

                finding_matches = re.finditer(
                    r'\{[^{}]*"title":\s*"[^"]*"[^{}]*\}',
                    partial,
                )
                valid_findings = []
                for match in finding_matches:
                    try:
                        finding_json = match.group(0)
                        finding = json.loads(finding_json)
                        valid_findings.append(finding)
                    except (json.JSONDecodeError, AttributeError):
                        pass

                if valid_findings:
                    summary_match = re.search(r'"summary":\s*\{[^}]+\}', partial)
                    summary = {
                        "total": len(valid_findings),
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 0,
                        "info": 0,
                    }
                    if summary_match:
                        try:
                            summary = json.loads("{" + summary_match.group(0) + "}")
                        except json.JSONDecodeError:
                            pass
                    for f in valid_findings:
                        sev = f.get("severity", "MEDIUM").upper()
                        if sev == "CRITICAL":
                            summary["critical"] = summary.get("critical", 0) + 1
                        elif sev == "HIGH":
                            summary["high"] = summary.get("high", 0) + 1
                        elif sev == "MEDIUM":
                            summary["medium"] = summary.get("medium", 0) + 1
                        elif sev == "LOW":
                            summary["low"] = summary.get("low", 0) + 1
                        else:
                            summary["info"] = summary.get("info", 0) + 1
                    logger.info(f"Extracted {len(valid_findings)} valid findings via regex")
                    return {"pressure_findings": valid_findings, "summary": summary}

                last_open = max(partial.rfind('{"'), partial.rfind('["'))
                if last_open > 0:
                    try_data = partial[last_open:]
                    for ending in ["]", "}", '"]', '"}']:
                        if try_data.endswith(ending):
                            try:
                                data = json.loads(try_data)
                                if isinstance(data, dict) and "pressure_findings" in data:
                                    logger.info(
                                        f"Recovered partial JSON by finding start at char {last_open}"
                                    )
                                    return data
                            except json.JSONDecodeError:
                                pass

                brace_count = partial.count("{") - partial.count("}")
                if brace_count > 0:
                    partial_fixed = partial + ("}" * brace_count)
                    try:
                        data = json.loads(partial_fixed)
                        if isinstance(data, dict) and "pressure_findings" in data:
                            valid_findings = [
                                f
                                for f in data.get("pressure_findings", [])
                                if isinstance(f, dict) and "title" in f
                            ]
                            data["pressure_findings"] = valid_findings
                            logger.info(
                                f"Recovered JSON by balancing braces, {len(valid_findings)} valid findings"
                            )
                            return data
                    except json.JSONDecodeError:
                        pass

            except Exception as ex:
                logger.debug(f"JSON extraction attempt failed: {ex}")
            logger.error(f"Failed to parse pressure review response: {e}")
            return {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0}}
