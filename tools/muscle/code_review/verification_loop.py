"""
Verification Loop - Verifies fixes worked before learning from them.

Implements the Codex-style verify-before-learn pattern:
1. Apply fix
2. Run validation (compiler, linter, tests)
3. If verification fails, revert and analyze why
4. Only record as "learned" if verification passes

Architecture Decision Record (ADR):
- Verification is mandatory before learning from a fix
- M2.7 analyzes why fixes failed when verification fails
- Reverts broken fixes automatically
- Tracks verification results for strategy evolution
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..escalation import EscalationPolicy, EscalationRecord, EscalationRecorder
from ..m27_client import M27Client
from ..optimization.prompt_context import build_telemetry_context, compose_prompt_envelope
from .review_artifacts import ReviewArtifactStore, resolve_trace_policy
from .types import ReviewIssue

logger = logging.getLogger(__name__)


class VerificationStatus(Enum):
    """Strict semantic verification statuses accepted from M2.7."""

    VERIFIED = "VERIFIED"
    BREAKS = "BREAKS"
    NEEDS_WORK = "NEEDS_WORK"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class VerificationResult:
    issue: ReviewIssue
    fix_applied: bool
    fix_verified: bool
    verification_details: str
    reverted: bool
    failure_analysis: str | None = None
    tokens_spent: int = 0


@dataclass
class VerificationLoop:
    m27_client: M27Client | None
    verify_compile: bool = True
    verify_linter: bool = True
    verify_tests: bool = True
    auto_revert: bool = True
    _verified_fixes: list[VerificationResult] = field(default_factory=list)
    _failed_fixes: list[VerificationResult] = field(default_factory=list)
    _runtime_context: dict[str, Any] = field(default_factory=dict)

    def configure_runtime(
        self,
        project_path: str,
        session_id: str,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
        artifact_store: ReviewArtifactStore | None = None,
        trace_reasons: list[str] | None = None,
    ) -> None:
        """Attach runtime metadata used for telemetry on verification calls."""
        self._runtime_context = {
            "project_path": project_path,
            "session_id": session_id,
            "workflow_name": workflow_name,
            "review_mode": review_mode,
            "language": language,
            "complexity": complexity,
            "target_type": target_type,
            "artifact_store": artifact_store,
            "trace_reasons": list(trace_reasons or []),
        }

    def _check_escalation(self, result: VerificationResult) -> None:
        """Emit escalation if verification failures exceed the policy threshold."""
        project_path = self._runtime_context.get("project_path")
        session_id = self._runtime_context.get("session_id")
        if not project_path or not session_id:
            return

        policy = EscalationPolicy()
        attempt_count = len(self._failed_fixes)
        recorder = EscalationRecorder(project_path, policy)
        if recorder.should_escalate("verification_failure", attempt_count):
            recorder.emit(
                EscalationRecord(
                    session_id=session_id,
                    reason="verification_failure",
                    source_module="verification_loop",
                    issue_summary=(
                        f"Fix verification failed for {result.issue.file_path}:"
                        f"{result.issue.line_number} — {result.issue.title}."
                        f" {attempt_count} cumulative failure(s)."
                    ),
                    attempt_count=attempt_count,
                )
            )

    def verify_fix(self, issue: ReviewIssue, fixed_content: str) -> VerificationResult:
        """Verify a fix is valid before learning from it."""
        file_path = Path(issue.file_path)
        backup_path = file_path.with_suffix(file_path.suffix + ".muscle.bak")

        result = VerificationResult(
            issue=issue,
            fix_applied=False,
            fix_verified=False,
            verification_details="",
            reverted=False,
        )

        original_content = file_path.read_text(encoding="utf-8")
        fix_already_applied = original_content == fixed_content

        try:
            if not fix_already_applied:
                shutil.copy2(file_path, backup_path)
                file_path.write_text(fixed_content, encoding="utf-8")
            result.fix_applied = True

            if self.m27_client:
                verification_text, usage = self._m27_verify(issue, fixed_content)
                result.verification_details = verification_text
                result.tokens_spent = usage.total if usage else 0

                verification_status = self._parse_verification_status(verification_text)
                if verification_status is not VerificationStatus.VERIFIED:
                    if self.auto_revert and not fix_already_applied:
                        self._revert_fix(file_path, backup_path, original_content)
                        result.reverted = True
                    result.fix_verified = False
                    result.failure_analysis = self._m27_analyze_failure(issue, verification_text)
                    return result

            verification_passed = self._run_validation(file_path, issue)
            result.fix_verified = verification_passed

            if not verification_passed:
                if self.auto_revert and not fix_already_applied:
                    self._revert_fix(file_path, backup_path, original_content)
                    result.reverted = True
                    result.verification_details += "\nValidation failed - reverted"
                else:
                    result.verification_details += "\nValidation failed"
            else:
                result.verification_details += "\nAll validations passed"

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            result.verification_details = f"Exception during verification: {e}"
            if self.auto_revert and not fix_already_applied and backup_path.exists():
                self._revert_fix(file_path, backup_path, original_content)
                result.reverted = True
        finally:
            if backup_path.exists():
                backup_path.unlink()

        if result.fix_verified:
            self._verified_fixes.append(result)
        else:
            self._failed_fixes.append(result)
            self._check_escalation(result)

        return result

    @staticmethod
    def _parse_verification_status(verification_text: str) -> VerificationStatus:
        """Parse the first verifier status token and fail closed on ambiguity."""
        normalized = verification_text.strip().upper()
        if not normalized:
            return VerificationStatus.UNKNOWN
        first_line = normalized.splitlines()[0].strip()
        if first_line.startswith("VERIFIED"):
            return VerificationStatus.VERIFIED
        if first_line.startswith("BREAKS") or first_line.startswith("FAILS"):
            return VerificationStatus.BREAKS
        if first_line.startswith("NEEDS_WORK"):
            return VerificationStatus.NEEDS_WORK
        if first_line.startswith("VERIFICATION_ERROR"):
            return VerificationStatus.ERROR
        return VerificationStatus.UNKNOWN

    def _m27_verify(self, issue: ReviewIssue, fixed_content: str) -> tuple[str, Any]:
        """Use M2.7 to verify the fix doesn't break anything."""
        if not self.m27_client:
            return "M27 not available for verification", None

        prompt = f"""Verify this code fix is correct and doesn't break anything.

Original Issue:
- File: {issue.file_path}
- Line: {issue.line_number}
- Issue: {issue.title}
- Description: {issue.description}

Original Code:
```
{issue.code_snippet}
```

Fixed Code:
```
{fixed_content}
```

Check for:
1. Does the fix actually address the issue?
2. Could the fix introduce new bugs or break existing functionality?
3. Are there any syntax errors?
4. Does the fix maintain the same API/signature if applicable?

Respond with:
- "VERIFIED" if the fix is correct
- "BREAKS: <reason>" if the fix breaks something
- "NEEDS_WORK: <reason>" if the fix doesn't fully address the issue

Be conservative - if you're not sure, say NEEDS_WORK."""

        prompt_envelope = compose_prompt_envelope(
            base_prompt=prompt,
            lesson_resolver=None,
            query_text=f"{issue.file_path}\n{issue.title}",
            stage="verification",
            base_context_strategy="verification_issue_context",
            session_id=str(self._runtime_context.get("session_id") or ""),
            language=self._runtime_context.get("language"),
        )
        trace_reasons = list(self._runtime_context.get("trace_reasons", []) or [])
        artifact_store = self._runtime_context.get("artifact_store")
        trace_policy, active_trace_reasons = resolve_trace_policy(*trace_reasons)
        trace_metadata: dict[str, Any] = {
            "trace_capture_policy": trace_policy,
            "trace_capture_reasons": active_trace_reasons,
            "trace_pointers": {},
        }
        if isinstance(artifact_store, ReviewArtifactStore) and prompt_envelope.call_id:
            trace_metadata = artifact_store.prepare_llm_trace(
                call_id=prompt_envelope.call_id,
                stage="verification",
                prompt_text=prompt_envelope.prompt,
                context_strategy=prompt_envelope.context_strategy,
                context_chars=prompt_envelope.context_chars,
                prompt_metadata=prompt_envelope.metadata,
                trace_policy=trace_policy,
                trace_reasons=active_trace_reasons,
            )
        telemetry_context = build_telemetry_context(
            project_path=str(self._runtime_context.get("project_path") or Path.cwd()),
            session_id=str(self._runtime_context.get("session_id") or ""),
            stage="verification",
            prompt_envelope=prompt_envelope,
            trace_artifacts=trace_metadata["trace_pointers"],
            trace_policy=trace_metadata["trace_capture_policy"],
            trace_reasons=trace_metadata["trace_capture_reasons"],
            workflow_name=self._runtime_context.get("workflow_name"),
            review_mode=self._runtime_context.get("review_mode"),
            language=self._runtime_context.get("language"),
            complexity=self._runtime_context.get("complexity"),
            target_type=self._runtime_context.get("target_type"),
            metadata={"file_path": issue.file_path, "line_number": issue.line_number},
        )

        try:
            response_text, usage = self.m27_client.chat(
                messages=[{"role": "user", "content": prompt_envelope.prompt}],
                system="You are a code verification expert. Be thorough and conservative.",
                max_tokens=1024,
                temperature=0.3,
                telemetry_context=telemetry_context,
            )
            verification_status = self._parse_verification_status(response_text)
            verification_failed = verification_status is not VerificationStatus.VERIFIED
            final_reasons = trace_reasons + (
                ["verification_failure"] if verification_failed else []
            )
            final_policy, final_active_reasons = resolve_trace_policy(*final_reasons)
            if isinstance(artifact_store, ReviewArtifactStore) and telemetry_context is not None:
                artifact_store.finalize_llm_trace(
                    call_id=telemetry_context.call_id,
                    stage="verification",
                    validation_payload={
                        "call_id": telemetry_context.call_id,
                        "stage": "verification",
                        "status": (
                            "verified"
                            if verification_status is VerificationStatus.VERIFIED
                            else f"verification_{verification_status.value.lower()}"
                        ),
                        "parse_success": bool(response_text.strip()),
                        "validation_success": not verification_failed,
                        "trace_policy": final_policy,
                        "trace_reasons": final_active_reasons,
                        "file_path": issue.file_path,
                        "line_number": issue.line_number,
                        "verification_text": (
                            response_text.strip() if final_policy == "thick" else None
                        ),
                    },
                )
            if telemetry_context:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    parse_success=bool(response_text.strip()),
                    validation_success=not verification_failed,
                    metadata_updates={
                        "trace_capture_policy": final_policy,
                        "trace_capture_reasons": final_active_reasons,
                        "trace_pointers": trace_metadata["trace_pointers"],
                    },
                )
            return response_text.strip(), usage
        except Exception as e:
            logger.warning(f"M27 verification failed: {e}")
            if isinstance(artifact_store, ReviewArtifactStore) and telemetry_context is not None:
                final_policy, final_active_reasons = resolve_trace_policy(
                    *trace_reasons,
                    "verification_failure",
                )
                artifact_store.finalize_llm_trace(
                    call_id=telemetry_context.call_id,
                    stage="verification",
                    validation_payload={
                        "call_id": telemetry_context.call_id,
                        "stage": "verification",
                        "status": "verification_error",
                        "parse_success": False,
                        "validation_success": False,
                        "trace_policy": final_policy,
                        "trace_reasons": final_active_reasons,
                        "file_path": issue.file_path,
                        "line_number": issue.line_number,
                        "error": str(e),
                    },
                )
            return f"VERIFICATION_ERROR: {e}", None

    def _m27_analyze_failure(self, issue: ReviewIssue, verification_text: str) -> str:
        """Use M2.7 to analyze why a fix failed verification."""
        if not self.m27_client:
            return "M27 not available for analysis"

        prompt = f"""Analyze why this code fix failed verification.

Original Issue:
- File: {issue.file_path}
- Line: {issue.line_number}
- Issue: {issue.title}

Original Code:
```
{issue.code_snippet}
```

Suggested Fix:
```
{issue.suggested_fix or "N/A"}
```

Verification Result:
{verification_text}

Why did the fix fail? What should be done differently?

Return a brief analysis (2-3 sentences)."""

        prompt_envelope = compose_prompt_envelope(
            base_prompt=prompt,
            lesson_resolver=None,
            query_text=f"{issue.file_path}\n{issue.title}\nverification_failure_analysis",
            stage="verification",
            base_context_strategy="verification_failure_analysis",
            session_id=str(self._runtime_context.get("session_id") or ""),
            language=self._runtime_context.get("language"),
        )
        telemetry_context = build_telemetry_context(
            project_path=str(self._runtime_context.get("project_path") or Path.cwd()),
            session_id=str(self._runtime_context.get("session_id") or ""),
            stage="verification",
            prompt_envelope=prompt_envelope,
            workflow_name=self._runtime_context.get("workflow_name"),
            review_mode=self._runtime_context.get("review_mode"),
            language=self._runtime_context.get("language"),
            complexity=self._runtime_context.get("complexity"),
            target_type=self._runtime_context.get("target_type"),
            metadata={"file_path": issue.file_path, "line_number": issue.line_number},
        )

        try:
            response_text, _ = self.m27_client.chat(
                messages=[{"role": "user", "content": prompt_envelope.prompt}],
                system="You are a code debugging expert.",
                max_tokens=512,
                temperature=0.5,
                telemetry_context=telemetry_context,
            )
            if telemetry_context:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    parse_success=bool(response_text.strip()),
                )
            return response_text.strip()
        except Exception as e:
            logger.warning(f"M27 analysis failed: {e}")
            return f"Analysis failed: {e}"

    def _run_validation(self, file_path: Path, issue: ReviewIssue) -> bool:
        """Run basic validation checks on the fixed file."""
        language = self._detect_language(file_path)

        if self.verify_compile and language:
            if not self._check_compilation(file_path, language):
                return False

        if self.verify_linter and language:
            if not self._check_linter(file_path, language):
                return False

        if self.verify_tests:
            if not self._check_tests(file_path):
                return False

        return True

    def _detect_language(self, file_path: Path) -> str | None:
        ext = file_path.suffix.lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
        }
        return lang_map.get(ext)

    def _check_compilation(self, file_path: Path, language: str) -> bool:
        import subprocess

        cmd_map = {
            "python": ["python", "-m", "py_compile", str(file_path)],
            "javascript": ["node", "--check", str(file_path)],
            "typescript": ["npx", "tsc", "--noEmit", str(file_path)],
            "go": ["go", "build", "-o", "/dev/null", str(file_path)],
            "rust": ["rustc", "--edition", "2021", "--emit=metadata", str(file_path)],
        }

        cmd = cmd_map.get(language)
        if not cmd:
            return True

        try:
            # Fix: VL-01. 10s per step keeps the global verification loop
            # responsive. Large codebases that legitimately need longer should
            # override via config rather than block the review loop.
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.warning(f"Compilation check failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.warning(f"Compilation check error: {e}")
            return False

    def _check_linter(self, file_path: Path, language: str) -> bool:
        import subprocess

        cmd_map = {
            "python": ["ruff", "check", str(file_path)],
            "javascript": ["eslint", str(file_path)],
            "typescript": ["eslint", str(file_path)],
        }

        cmd = cmd_map.get(language)
        if not cmd:
            return True

        try:
            # Fix: VL-01. 10s per step keeps the global verification loop
            # responsive. Large codebases that legitimately need longer should
            # override via config rather than block the review loop.
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.warning(f"Linter check failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.warning(f"Linter check error: {e}")
            return False

    def _check_tests(self, file_path: Path) -> bool:
        import subprocess

        test_patterns = {
            ".py": ["python", "-m", "pytest", str(file_path), "-x", "-q"],
        }

        cmd = test_patterns.get(file_path.suffix.lower())
        if not cmd:
            return True

        try:
            # Fix: VL-01. Cap test check at 15s to avoid blocking the loop on
            # a single slow test; dedicated test runs belong in ``muscle run``.
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                logger.warning(f"Test check failed: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.warning(f"Test check error: {e}")
            return False

    def _revert_fix(self, file_path: Path, backup_path: Path, original_content: str) -> None:
        """Revert the fix by restoring original content."""
        try:
            if backup_path.exists():
                shutil.move(str(backup_path), str(file_path))
            else:
                file_path.write_text(original_content, encoding="utf-8")
            logger.info(f"Reverted fix for {file_path}")
        except Exception as e:
            logger.error(f"Failed to revert fix: {e}")

    def get_verification_stats(self) -> dict[str, Any]:
        """Get statistics about verification results."""
        return {
            "total_verified": len(self._verified_fixes),
            "total_failed": len(self._failed_fixes),
            "success_rate": (
                len(self._verified_fixes) / (len(self._verified_fixes) + len(self._failed_fixes))
                if (self._verified_fixes + self._failed_fixes)
                else 0.0
            ),
            "verified_issues": [
                {
                    "file": r.issue.file_path,
                    "line": r.issue.line_number,
                    "title": r.issue.title,
                }
                for r in self._verified_fixes
            ],
            "failed_issues": [
                {
                    "file": r.issue.file_path,
                    "line": r.issue.line_number,
                    "title": r.issue.title,
                    "failure_analysis": r.failure_analysis,
                }
                for r in self._failed_fixes
            ],
        }

    def get_failed_fixes_for_learning(self) -> list[dict[str, Any]]:
        """Get failed fixes formatted for StrategyEvolver."""
        return [
            {
                "issue": {
                    "file": r.issue.file_path,
                    "line": r.issue.line_number,
                    "title": r.issue.title,
                    "description": r.issue.description,
                    "code_snippet": r.issue.code_snippet,
                },
                "verification_result": r.verification_details,
                "failure_analysis": r.failure_analysis,
                "tokens_spent": r.tokens_spent,
            }
            for r in self._failed_fixes
        ]
