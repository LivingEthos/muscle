"""Auto-fix application with git backup.

Architecture Decision Record (ADR):
- Git-first backup (stash + branch) with .muscle.bak fallback keeps history clean.
- Path-traversal validation via ``resolve().is_relative_to()`` blocks escapes.
- AST validation for Python files prevents syntax-breaking patches.
- Regex length cap (200 chars) mitigates ReDoS on fix application.
- Fixes are applied in descending line order so earlier edits don't shift later ones.
"""

from __future__ import annotations

import ast as pyast
import re
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FixResult:
    """Result of applying a fix."""

    success: bool
    file_path: str
    original_content: str
    new_content: str
    suggestion_id: str
    error_message: str = ""


@dataclass
class OperationMetrics:
    """Metrics for a single operation type."""

    count: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successes / self.count if self.count > 0 else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.count if self.count > 0 else 0.0


class MetricsCollector:
    """Collects and reports metrics for MUSCLE operations."""

    def __init__(self) -> None:
        self._metrics: dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._operation_start_times: dict[str, float] = {}

    def start_operation(self, operation: str) -> None:
        """Record the start time of an operation."""
        self._operation_start_times[operation] = time.perf_counter()

    def record_success(self, operation: str, duration_ms: float | None = None) -> None:
        """Record a successful operation."""
        metrics = self._metrics[operation]
        metrics.count += 1
        metrics.successes += 1
        if duration_ms is not None:
            metrics.total_duration_ms += duration_ms
        elif operation in self._operation_start_times:
            elapsed = (time.perf_counter() - self._operation_start_times[operation]) * 1000
            metrics.total_duration_ms += elapsed
            del self._operation_start_times[operation]

    def record_failure(self, operation: str, error: str, duration_ms: float | None = None) -> None:
        """Record a failed operation."""
        metrics = self._metrics[operation]
        metrics.count += 1
        metrics.failures += 1
        metrics.errors.append(error)
        if duration_ms is not None:
            metrics.total_duration_ms += duration_ms
        elif operation in self._operation_start_times:
            elapsed = (time.perf_counter() - self._operation_start_times[operation]) * 1000
            metrics.total_duration_ms += elapsed
            del self._operation_start_times[operation]

    def get_metrics(self, operation: str | None = None) -> dict[str, Any]:
        """Get metrics for all or a specific operation."""
        if operation:
            m = self._metrics.get(operation, OperationMetrics())
            return {
                "operation": operation,
                "count": m.count,
                "successes": m.successes,
                "failures": m.failures,
                "success_rate": m.success_rate,
                "avg_duration_ms": m.avg_duration_ms,
                "recent_errors": m.errors[-5:],
            }
        return {
            op: {
                "count": m.count,
                "successes": m.successes,
                "failures": m.failures,
                "success_rate": m.success_rate,
                "avg_duration_ms": m.avg_duration_ms,
            }
            for op, m in self._metrics.items()
        }

    def get_summary(self) -> dict[str, Any]:
        """Get overall summary."""
        total_ops = sum(m.count for m in self._metrics.values())
        total_successes = sum(m.successes for m in self._metrics.values())
        return {
            "total_operations": total_ops,
            "total_successes": total_successes,
            "total_failures": total_ops - total_successes,
            "overall_success_rate": (total_successes / total_ops if total_ops > 0 else 0.0),
            "operations": list(self._metrics.keys()),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self._metrics.clear()
        self._operation_start_times.clear()


class GitBackup:
    """Creates git backups before applying fixes."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._has_git = (project_root / ".git").exists()

    def create_backup(self, files: list[Path]) -> bool:
        """Create a git stash or backup branch before fixing."""
        if not self._has_git:
            return self._create_file_backup(files)

        try:
            # Check if there are uncommitted changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )

            if result.stdout.strip():
                # Stash uncommitted changes
                subprocess.run(
                    ["git", "stash", "push", "-m", "muscle-auto-fix-backup"],
                    cwd=self.project_root,
                    capture_output=True,
                    check=True,
                    timeout=30,
                )

            # Create a backup branch
            short_sha = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=self.project_root,
                    timeout=10,
                )
                .decode()
                .strip()
            )
            branch_name = f"muscle-backup-{short_sha}"
            subprocess.run(
                ["git", "branch", "-f", branch_name],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                timeout=30,
            )

            return True
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ):
            return self._create_file_backup(files)

    def _create_file_backup(self, files: list[Path]) -> bool:
        """Create .bak file backups when git is not available."""
        for file_path in files:
            if file_path.exists():
                backup_path = Path(str(file_path) + ".muscle.bak")
                shutil.copy2(file_path, backup_path)
        return True

    def restore_backup(self) -> bool:
        """Restore from backup."""
        return self._restore_file_backup()

    def _restore_file_backup(self) -> bool:
        """Restore from .bak files."""
        for bak_file in self.project_root.rglob("*.muscle.bak"):
            original = Path(str(bak_file)[: -len(".muscle.bak")])
            # Validate the resolved original path is inside project root
            try:
                if not original.resolve().is_relative_to(self.project_root.resolve()):
                    continue
            except (OSError, ValueError):
                continue
            shutil.copy2(bak_file, original)
            bak_file.unlink()
        return True


@dataclass
class Suggestion:
    """Minimal suggestion dataclass for auto-fixer.

    Mirrors the v2 Suggestion entity but uses plain types so the fixer
    can operate without importing the full domain layer.
    """

    id: str
    review_id: str
    message: str
    severity: str
    category: str = "general"
    fix: str | None = None
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    chunk_content: str | None = None


class AutoFixer:
    """Applies automated fixes to code based on suggestions."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.backup = GitBackup(project_root)
        self.results: list[FixResult] = []
        self.metrics = MetricsCollector()

    def apply_fixes(
        self,
        suggestions: list[Suggestion],
        dry_run: bool = False,
    ) -> list[FixResult]:
        """Apply fixes for suggestions that have fix instructions."""
        # Group suggestions by file
        by_file: dict[str, list[Suggestion]] = {}
        for s in suggestions:
            if s.fix and s.file_path:
                by_file.setdefault(s.file_path, []).append(s)

        if not by_file:
            return []

        # Create backup (only for files inside project root)
        if not dry_run:
            files_to_backup = []
            for p in by_file:
                fp = self.project_root / p
                try:
                    if fp.resolve().is_relative_to(self.project_root.resolve()):
                        files_to_backup.append(fp)
                except (OSError, ValueError):
                    pass
            if files_to_backup:
                self.backup.create_backup(files_to_backup)

        # Apply fixes
        for file_path, file_suggestions in by_file.items():
            self.metrics.start_operation("fix_file")
            result = self._apply_file_fixes(file_path, file_suggestions, dry_run)
            self.results.extend(result)
            all_success = all(r.success for r in result)
            if all_success:
                self.metrics.record_success("fix_file")
            else:
                errors = [r.error_message for r in result if not r.success]
                self.metrics.record_failure("fix_file", "; ".join(errors[:3]))

        return self.results

    def _apply_file_fixes(
        self,
        file_path: str,
        suggestions: list[Suggestion],
        dry_run: bool,
    ) -> list[FixResult]:
        """Apply fixes to a single file."""
        # Reject any path containing ".." components before joining
        if ".." in Path(file_path).parts:
            return [
                FixResult(
                    success=False,
                    file_path=file_path,
                    original_content="",
                    new_content="",
                    suggestion_id=s.id,
                    error_message=f"Path traversal blocked: {file_path}",
                )
                for s in suggestions
            ]

        full_path = self.project_root / file_path
        # Validate path traversal
        try:
            resolved = full_path.resolve()
            root_resolved = self.project_root.resolve()
            if not resolved.is_relative_to(root_resolved):
                return [
                    FixResult(
                        success=False,
                        file_path=file_path,
                        original_content="",
                        new_content="",
                        suggestion_id=s.id,
                        error_message=f"Path traversal blocked: {file_path}",
                    )
                    for s in suggestions
                ]
        except (OSError, ValueError) as exc:
            return [
                FixResult(
                    success=False,
                    file_path=file_path,
                    original_content="",
                    new_content="",
                    suggestion_id=s.id,
                    error_message=f"Invalid path: {exc}",
                )
                for s in suggestions
            ]

        if not full_path.exists():
            return [
                FixResult(
                    success=False,
                    file_path=file_path,
                    original_content="",
                    new_content="",
                    suggestion_id=s.id,
                    error_message=f"File not found: {file_path}",
                )
                for s in suggestions
            ]

        try:
            content = full_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [
                FixResult(
                    success=False,
                    file_path=file_path,
                    original_content="",
                    new_content="",
                    suggestion_id=s.id,
                    error_message=f"Cannot read file: {exc}",
                )
                for s in suggestions
            ]

        original_content = content
        results = []

        # Sort suggestions by start_line descending to preserve offsets
        sorted_suggestions = sorted(
            [s for s in suggestions if s.fix],
            key=lambda s: s.start_line if s.start_line is not None else 0,
            reverse=True,
        )

        for suggestion in sorted_suggestions:
            fix = suggestion.fix
            if not fix:
                continue

            try:
                new_content = self._apply_single_fix(content, suggestion)

                # Validate the fix doesn't introduce syntax errors for Python files
                # Only validate if the original content was already valid Python
                if full_path.suffix == ".py":
                    try:
                        pyast.parse(original_content)
                        original_was_valid = True
                    except SyntaxError:
                        original_was_valid = False

                    if original_was_valid:
                        try:
                            pyast.parse(new_content)
                        except SyntaxError as se:
                            results.append(
                                FixResult(
                                    success=False,
                                    file_path=file_path,
                                    original_content=content,
                                    new_content=new_content,
                                    suggestion_id=suggestion.id,
                                    error_message=f"Fix introduces syntax error: {se}",
                                )
                            )
                            continue

                if dry_run:
                    results.append(
                        FixResult(
                            success=True,
                            file_path=file_path,
                            original_content=original_content,
                            new_content=new_content,
                            suggestion_id=suggestion.id,
                        )
                    )
                else:
                    content = new_content
                    results.append(
                        FixResult(
                            success=True,
                            file_path=file_path,
                            original_content=original_content,
                            new_content=new_content,
                            suggestion_id=suggestion.id,
                        )
                    )
            except Exception as exc:
                results.append(
                    FixResult(
                        success=False,
                        file_path=file_path,
                        original_content=content,
                        new_content=content,
                        suggestion_id=suggestion.id,
                        error_message=str(exc),
                    )
                )

        # Write final content if not dry run
        if not dry_run and content != original_content:
            full_path.write_text(content, encoding="utf-8")

        return results

    def _apply_single_fix(self, content: str, suggestion: Suggestion) -> str:
        """Apply a single fix to content."""
        fix = suggestion.fix
        if not fix:
            return content

        # Strategy 1: Direct line replacement (most precise)
        if (
            suggestion.start_line is not None
            and suggestion.end_line is not None
            and "REPLACE WITH:" in fix
        ):
            lines = content.split("\n")
            start = suggestion.start_line - 1  # 0-indexed
            end = suggestion.end_line

            if 0 <= start < len(lines) and 0 <= end <= len(lines):
                replacement = fix.split("REPLACE WITH:", 1)[1].strip()
                lines[start:end] = [replacement]
                return "\n".join(lines)

        # Strategy 2: Pattern-based replacement with line validation
        if "FIND:" in fix and "REPLACE:" in fix:
            parts = fix.split("REPLACE:", 1)
            find_part = parts[0].replace("FIND:", "").strip()
            replace_part = parts[1].strip()
            # Validate the find text exists on the expected line
            if suggestion.start_line is not None:
                lines = content.split("\n")
                line_idx = suggestion.start_line - 1
                if 0 <= line_idx < len(lines) and find_part in lines[line_idx]:
                    lines[line_idx] = lines[line_idx].replace(find_part, replace_part, 1)
                    return "\n".join(lines)
            return content.replace(find_part, replace_part, 1)

        # Strategy 3: Regex replacement (with length limit for safety)
        if fix.startswith("regex:"):
            pattern, replacement = fix[6:].split("->", 1)
            pattern_str = pattern.strip()
            # Limit regex to prevent ReDoS on fix application
            if len(pattern_str) > 200:
                raise ValueError(f"Regex pattern too long: {len(pattern_str)} chars")
            return re.sub(pattern_str, replacement.strip(), content, count=1)

        # Strategy 4: Line-aware string replacement (fallback)
        if suggestion.chunk_content and suggestion.start_line is not None:
            lines = content.split("\n")
            line_idx = suggestion.start_line - 1
            if 0 <= line_idx < len(lines) and suggestion.chunk_content in lines[line_idx]:
                lines[line_idx] = lines[line_idx].replace(suggestion.chunk_content, fix, 1)
                return "\n".join(lines)
            # Fallback to global replace if line-specific fails
            return content.replace(suggestion.chunk_content, fix, 1)

        return content

    def get_summary(self) -> dict[str, object]:
        """Get summary of fix results."""
        total = len(self.results)
        successful = sum(1 for r in self.results if r.success)
        by_file: dict[str, int] = {}
        for r in self.results:
            by_file[r.file_path] = by_file.get(r.file_path, 0) + (1 if r.success else 0)

        return {
            "total_attempts": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": successful / total if total > 0 else 0.0,
            "files_modified": len(by_file),
            "metrics": self.metrics.get_summary(),
        }
