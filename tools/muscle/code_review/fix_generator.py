"""
Fix Generator - Generates and applies code fixes.

Uses M2.7 to generate specific code fixes for identified issues and
applies them to the codebase atomically (backup + apply).  Pre-apply
syntax validation is performed by ``_validate_staged_file``; post-apply
semantic verification is handled by ``VerificationLoop`` in
``review_controller.py``.

Architecture Decision Record (ADR):
- Generate targeted fixes for specific issues
- Apply fixes atomically (backup + apply)
- Validate syntax before committing; reject invalid fixes before write
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..m27_client import M27Client
from ..optimization.prompt_context import build_telemetry_context, compose_prompt_envelope
from .types import ReviewIssue

if TYPE_CHECKING:
    from ..optimization.context_budgeter import ContextBudgeter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert code fixer. You receive:
1. A specific code issue with file path, line number, and description
2. The original code snippet
3. A suggested fix

Your task is to:
1. Generate the complete fixed code for the file
2. Apply ONLY the necessary changes to fix the issue
3. Preserve all other code exactly as-is
4. Ensure the fix is syntactically correct

Output MUST be a JSON object:
{
  "file_path": "src/auth.py",
  "original_lines": "15-25",
  "fixed_code": "def authenticate(user_id):\\n    query = 'SELECT * FROM users WHERE id = ?'\\n    cursor.execute(query, (user_id,))\\n    ...",
  "explanation": "Changed string interpolation to parameterized query..."
}
"""


@dataclass
class FixResult:
    success: bool
    file_path: str
    original_content: str
    fixed_content: str
    applied: bool
    verified: bool
    error: str | None = None


@dataclass
class GeneratedFix:
    ok: bool
    file_path: str
    code: str
    error: str | None = None

    def __iter__(self) -> Iterator[str]:
        """Allow tuple-style unpacking for legacy call sites."""
        yield "" if not self.ok and not self.code else self.file_path
        yield self.code


class FixGenerator:
    def __init__(
        self,
        m27_client: M27Client,
        verify_compile: bool = True,
        context_budgeter: ContextBudgeter | None = None,
        project_path: str | None = None,
        lesson_resolver: object | None = None,
    ):
        self.m27_client = m27_client
        self.verify_compile = verify_compile
        self.context_budgeter = context_budgeter
        self.project_path = project_path or str(Path.cwd())
        self.lesson_resolver = lesson_resolver

    def generate_fix(
        self,
        issue: ReviewIssue,
        session_id: str | None = None,
        workflow_name: str | None = None,
        review_mode: str | None = None,
        language: str | None = None,
        complexity: str | None = None,
        target_type: str | None = None,
    ) -> GeneratedFix:
        if not issue.suggested_fix:
            return GeneratedFix(
                ok=False,
                file_path=issue.file_path,
                code="",
                error="No suggested fix available",
            )

        file_content = ""
        file_path = Path(issue.file_path)
        if file_path.exists():
            try:
                file_content = file_path.read_text(encoding="utf-8")
            except OSError:
                file_content = ""

        fix_budget = (
            self.context_budgeter.build_fix_budget(issue.line_number, file_content)
            if self.context_budgeter and file_content
            else None
        )

        user_prompt = f"""Generate a fix for this code issue:

File: {issue.file_path}
Line: {issue.line_number}
Issue: {issue.title}
Description: {issue.description}

Original code snippet:
```
{issue.code_snippet}
```

Suggested fix approach:
{issue.suggested_fix}

File context:
```
{fix_budget.content if fix_budget else file_content[:4000]}
```

Provide the JSON output with the fixed code."""
        prompt_envelope = compose_prompt_envelope(
            base_prompt=user_prompt,
            lesson_resolver=self.lesson_resolver,
            query_text=f"{issue.title}\n{issue.description}\n{issue.suggested_fix or ''}",
            stage="fix_generation",
            base_context_strategy=fix_budget.strategy if fix_budget else "full_file_patch_context",
            session_id=session_id,
            language=language,
        )
        user_prompt = prompt_envelope.prompt

        telemetry_context = build_telemetry_context(
            project_path=self.project_path,
            session_id=session_id,
            stage="fix_generation",
            prompt_envelope=prompt_envelope,
            workflow_name=workflow_name,
            review_mode=review_mode,
            language=language,
            complexity=complexity,
            target_type=target_type,
            metadata={
                "file_path": issue.file_path,
                "line_number": issue.line_number,
            },
        )

        response_text, _ = self.m27_client.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            telemetry_context=telemetry_context,
        )

        try:
            data = self._load_json_response(response_text)
            if telemetry_context:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    parse_success=True,
                )
            fixed_code = data.get("fixed_code", "")
            if not isinstance(fixed_code, str) or not fixed_code.strip():
                return GeneratedFix(
                    ok=False,
                    file_path=str(data.get("file_path") or issue.file_path),
                    code="",
                    error="Fix response did not include fixed_code",
                )
            return GeneratedFix(
                ok=True,
                file_path=str(data.get("file_path") or issue.file_path),
                code=fixed_code,
            )
        except json.JSONDecodeError:
            logger.error("Failed to parse fix response")
            if telemetry_context:
                self.m27_client.update_telemetry_call(
                    telemetry_context.call_id,
                    parse_success=False,
                )
            return GeneratedFix(
                ok=False,
                file_path=issue.file_path,
                code="",
                error="Failed to parse fix response",
            )

    @staticmethod
    def _sweep_stale_baks(directory: Path) -> None:
        """Delete ``*.muscle.bak`` files older than 1 hour in *directory*.

        Called at the start of :meth:`apply_fix` so that bak files left by
        previously interrupted apply operations are cleaned up before the next
        fix attempt.  Errors are logged but never raised — the sweep is
        best-effort.
        """
        stale_cutoff = time.time() - 3600
        try:
            for bak in directory.glob("*.muscle.bak"):
                try:
                    if bak.stat().st_mtime < stale_cutoff:
                        bak.unlink(missing_ok=True)
                        logger.debug("Removed stale bak file: %s", bak)
                except Exception as exc:
                    logger.debug("Could not remove stale bak file %s: %s", bak, exc)
        except Exception as exc:
            logger.debug("Stale-bak sweep failed for %s: %s", directory, exc)

    def apply_fix(self, issue: ReviewIssue, fixed_code: str) -> FixResult:
        file_path = Path(issue.file_path)

        self._sweep_stale_baks(file_path.parent)

        if not file_path.exists():
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content=fixed_code,
                applied=False,
                verified=False,
                error="File not found",
            )

        try:
            original_content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content=fixed_code,
                applied=False,
                verified=False,
                error=f"Cannot read file: {e}",
            )
        return self._commit_fix(file_path, original_content, fixed_code)

    def apply_fix_from_suggestion(self, issue: ReviewIssue) -> FixResult:
        if not issue.suggested_fix:
            return FixResult(
                success=False,
                file_path=issue.file_path,
                original_content="",
                fixed_content="",
                applied=False,
                verified=False,
                error="No suggested fix available",
            )

        file_path = Path(issue.file_path)
        if not file_path.exists():
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content="",
                applied=False,
                verified=False,
                error="File not found",
            )

        try:
            original_content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content="",
                fixed_content="",
                applied=False,
                verified=False,
                error=f"Cannot read file: {e}",
            )

        lines = original_content.split("\n")
        line_idx = issue.line_number - 1

        if line_idx < 0 or line_idx >= len(lines):
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content=original_content,
                fixed_content="",
                applied=False,
                verified=False,
                error=f"Line number {issue.line_number} out of range",
            )

        snippet_lines = issue.code_snippet.split("\n")
        fixed_lines = issue.suggested_fix.split("\n")

        if len(snippet_lines) == 1 and len(fixed_lines) == 1:
            lines[line_idx] = fixed_lines[0]
        else:
            start = line_idx
            end = line_idx + len(snippet_lines)
            if end <= len(lines):
                lines[start:end] = fixed_lines
            else:
                lines[line_idx] = "\n".join(fixed_lines)

        fixed_content = "\n".join(lines)
        return self._commit_fix(file_path, original_content, fixed_content)

    def rollback_fix(self, fix_result: FixResult) -> bool:
        if not fix_result.original_content:
            return False

        try:
            Path(fix_result.file_path).write_text(fix_result.original_content, encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False

    def reject_fix(self, issue: ReviewIssue) -> None:
        """
        Record that a proposed fix was rejected or dismissed by the user.

        This is called when a user explicitly rejects or undoes a fix that was
        applied. The rejection signal is recorded via the correction_signal_callback
        on ReviewController if one is configured.

        Args:
            issue: The ReviewIssue whose fix was rejected.
        """
        logger.info(f"Fix rejected by user: {issue.file_path}:{issue.line_number} - {issue.title}")
        # The actual signal recording is done via the correction_signal_callback
        # wired through ReviewController. This method exists to provide a hook
        # for the CLI to report user rejections.
        # Callers should also invoke the callback directly if they have access to it.

    @staticmethod
    def _load_json_response(response_text: str) -> dict:
        payload = response_text.strip()
        if payload.startswith("```"):
            lines = payload.splitlines()
            payload = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise json.JSONDecodeError("Response is not a JSON object", payload, 0)
        return data

    def _commit_fix(
        self,
        file_path: Path,
        original_content: str,
        fixed_content: str,
    ) -> FixResult:
        backup_path = file_path.with_suffix(file_path.suffix + ".muscle.bak")
        staged_path = file_path.with_name(f"{file_path.stem}.muscle.tmp{file_path.suffix}")
        safe_content = fixed_content.encode("utf-8", errors="replace").decode("utf-8")
        backup_created = False

        try:
            staged_path.write_text(safe_content, encoding="utf-8")
            validation_error = self._validate_staged_file(
                staged_path,
                language=self._detect_language(file_path),
            )
            if validation_error is not None:
                return FixResult(
                    success=False,
                    file_path=str(file_path),
                    original_content=original_content,
                    fixed_content=safe_content,
                    applied=False,
                    verified=False,
                    error=validation_error,
                )

            shutil.copy2(file_path, backup_path)
            backup_created = True
            os.replace(staged_path, file_path)
            return FixResult(
                success=True,
                file_path=str(file_path),
                original_content=original_content,
                fixed_content=safe_content,
                applied=True,
                verified=False,
            )
        except Exception as e:
            if backup_created and backup_path.exists():
                try:
                    shutil.move(str(backup_path), str(file_path))
                except Exception as restore_exc:
                    logger.error("Failed to restore %s from backup: %s", file_path, restore_exc)
            return FixResult(
                success=False,
                file_path=str(file_path),
                original_content=original_content,
                fixed_content=safe_content,
                applied=False,
                verified=False,
                error=f"Cannot write file: {e}",
            )
        finally:
            if staged_path.exists():
                staged_path.unlink(missing_ok=True)
            if backup_path.exists():
                backup_path.unlink(missing_ok=True)

    def _validate_staged_file(self, staged_path: Path, language: str | None = None) -> str | None:
        if not self.verify_compile:
            return None

        detected_language = language or self._detect_language(staged_path)
        if detected_language == "python":
            try:
                compile(staged_path.read_text(encoding="utf-8"), str(staged_path), "exec")
            except SyntaxError as exc:
                return f"Python syntax validation failed: {exc}"
            return None

        if detected_language == "json":
            try:
                json.loads(staged_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return f"JSON validation failed: {exc}"
            return None

        cmd_map = {
            "javascript": ["node", "--check", str(staged_path)],
            "typescript": ["npx", "tsc", "--noEmit", "--pretty", "false", str(staged_path)],
        }
        cmd = cmd_map.get(detected_language or "")
        if cmd is None:
            logger.info(
                "No local validator available for %s; skipping compile validation", staged_path
            )
            return None

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as exc:
            return f"Required validator command not found: {exc}"
        except Exception as exc:
            return f"Validation failed to run: {exc}"

        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown validator error"
            return f"Validation failed: {stderr[:500]}"
        return None

    @staticmethod
    def _detect_language(file_path: Path) -> str | None:
        ext = file_path.suffix.lower()
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".mjs": "javascript",
            ".cjs": "javascript",
            ".ts": "typescript",
            ".json": "json",
        }
        return lang_map.get(ext)
