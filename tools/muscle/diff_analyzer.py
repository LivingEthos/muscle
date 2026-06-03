"""Diff analyzer for incremental code reviews.

Extracts changed files and hunks from git diff output,
enabling MUSCLE to review only modified code instead of entire files.

Architecture Decision Record (ADR):
- Unified-diff parser avoids external dependencies (no ``unidiff`` library).
- Frozen dataclasses make hunks hashable and safe to use in sets/dicts.
- ``DiffReviewScopeBuilder`` is async so it can read files via an injected FS abstraction.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Awaitable


@dataclass(frozen=True)
class DiffHunk:
    """A single hunk of changes within a file."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str] = field(default_factory=list)

    @property
    def is_pure_addition(self) -> bool:
        """True if this hunk only adds lines (no deletions)."""
        has_adds = any(ln.startswith("+") and not ln.startswith("+++") for ln in self.lines)
        has_dels = any(ln.startswith("-") and not ln.startswith("---") for ln in self.lines)
        return has_adds and not has_dels

    @property
    def changed_line_numbers(self) -> list[int]:
        """Return line numbers in the new file that were changed."""
        line_nums: list[int] = []
        current = self.new_start
        for line in self.lines:
            if line.startswith("+") and not line.startswith("+++"):
                line_nums.append(current)
                current += 1
            elif line.startswith("-") and not line.startswith("---"):
                continue
            elif line.startswith(" "):
                current += 1
        return line_nums


@dataclass(frozen=True)
class FileDiff:
    """Changes for a single file."""

    path: Path
    old_path: Path | None
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def is_new_file(self) -> bool:
        """True if this is a newly added file."""
        return self.old_path is None or str(self.old_path) == "/dev/null"

    @property
    def is_deleted(self) -> bool:
        """True if this file was deleted."""
        return str(self.path) == "/dev/null"

    @property
    def changed_lines(self) -> list[int]:
        """All changed line numbers across all hunks."""
        result: list[int] = []
        for hunk in self.hunks:
            result.extend(hunk.changed_line_numbers)
        return result

    @property
    def context_line_start(self) -> int:
        """First line number with context (for review focus)."""
        if not self.hunks:
            return 1
        return max(1, self.hunks[0].new_start - 3)

    @property
    def context_line_end(self) -> int:
        """Last line number with context (for review focus)."""
        if not self.hunks:
            return 1
        last_hunk = self.hunks[-1]
        return last_hunk.new_start + last_hunk.new_lines + 3


class DiffAnalyzer:
    """Analyze git diffs to extract changed code for targeted review."""

    HUNK_HEADER_RE: Final = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    @classmethod
    def from_git(
        cls,
        repo_path: Path,
        base_ref: str = "HEAD",
        target_ref: str | None = None,
    ) -> list[FileDiff]:
        """Get diff from git between two refs.

        Args:
            repo_path: Path to git repository.
            base_ref: Base commit/branch (default: HEAD).
            target_ref: Target commit/branch (default: working tree).

        Returns:
            List of FileDiff objects representing changed files.
        """
        import re

        ref_re = re.compile(r"^[a-zA-Z0-9_./:-]+$")

        def _validate_ref(ref: str) -> str:
            if ref.startswith("-"):
                raise ValueError(f"Invalid git ref (starts with '-'): {ref}")
            if not ref_re.match(ref):
                raise ValueError(f"Invalid git ref: {ref}")
            return ref

        _validate_ref(base_ref)
        if target_ref:
            _validate_ref(target_ref)

        cmd = ["git", "-C", str(repo_path), "diff", base_ref]
        if target_ref:
            cmd.append(target_ref)
        else:
            cmd.append("--")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git diff failed: {exc.stderr}") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("git not found in PATH") from exc

        return cls.parse_diff(result.stdout)

    @classmethod
    def from_string(cls, diff_text: str) -> list[FileDiff]:
        """Parse diff from a string."""
        return cls.parse_diff(diff_text)

    @classmethod
    def parse_diff(cls, diff_text: str) -> list[FileDiff]:
        """Parse unified diff format into structured FileDiff objects."""
        file_diffs: list[FileDiff] = []
        current_file: FileDiff | None = None
        current_hunk: DiffHunk | None = None

        for line in diff_text.splitlines():
            # New file diff header
            if line.startswith("diff --git"):
                if current_file:
                    file_diffs.append(current_file)
                current_file = None
                current_hunk = None
                continue

            # File path lines
            if line.startswith("--- "):
                old_path = line[4:].split("\t")[0].strip()
                if old_path == "/dev/null":
                    old_path_obj = None
                else:
                    # Remove a/ or b/ prefix
                    old_path_obj = Path(old_path.lstrip("ab/"))
                if current_file:
                    current_file = FileDiff(
                        path=current_file.path,
                        old_path=old_path_obj,
                        hunks=current_file.hunks,
                    )
                continue

            if line.startswith("+++ "):
                new_path = line[4:].split("\t")[0].strip()
                if new_path == "/dev/null":
                    new_path_obj = Path("/dev/null")
                else:
                    new_path_obj = Path(new_path.lstrip("ab/"))
                if current_file is None:
                    current_file = FileDiff(path=new_path_obj, old_path=None)
                else:
                    current_file = FileDiff(
                        path=new_path_obj,
                        old_path=current_file.old_path,
                        hunks=current_file.hunks,
                    )
                continue

            # Hunk header
            match = cls.HUNK_HEADER_RE.match(line)
            if match and current_file is not None:
                if current_hunk:
                    current_file.hunks.append(current_hunk)
                old_start = int(match.group(1))
                old_lines = int(match.group(2)) if match.group(2) else 1
                new_start = int(match.group(3))
                new_lines = int(match.group(4)) if match.group(4) else 1
                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_lines=old_lines,
                    new_start=new_start,
                    new_lines=new_lines,
                    lines=[],
                )
                continue

            # Hunk content
            if current_hunk is not None:
                current_hunk.lines.append(line)

        # Finalize last hunk and file
        if current_hunk and current_file:
            current_file.hunks.append(current_hunk)
        if current_file:
            file_diffs.append(current_file)

        return file_diffs

    @classmethod
    def extract_changed_context(
        cls,
        file_path: Path,
        file_content: str,
        file_diff: FileDiff,
        context_lines: int = 5,
    ) -> str:
        """Extract changed lines with surrounding context from file content.

        Args:
            file_path: Path to the file (for header).
            file_content: Full file content.
            file_diff: Parsed diff for this file.
            context_lines: Lines of context around changes.

        Returns:
            Formatted string with changes and context.
        """
        lines = file_content.splitlines()
        changed = set(file_diff.changed_lines)

        # Expand to include context
        context_set: set[int] = set()
        for line_num in changed:
            for ctx in range(line_num - context_lines, line_num + context_lines + 1):
                if 1 <= ctx <= len(lines):
                    context_set.add(ctx)

        if not context_set:
            return f"--- {file_path}\n{file_content}"

        # Build output with change markers
        result_lines = [f"--- {file_path}"]
        sorted_lines = sorted(context_set)

        # Group contiguous lines
        groups: list[list[int]] = []
        current_group: list[int] = []
        for line_num in sorted_lines:
            if not current_group or line_num == current_group[-1] + 1:
                current_group.append(line_num)
            else:
                groups.append(current_group)
                current_group = [line_num]
        if current_group:
            groups.append(current_group)

        for group in groups:
            result_lines.append("")
            for line_num in group:
                prefix = ">>> " if line_num in changed else "    "
                result_lines.append(f"{prefix}{line_num:4d}: {lines[line_num - 1]}")

        return "\n".join(result_lines)


class DiffReviewScopeBuilder:
    """Build review scope from git diff for incremental reviews."""

    def __init__(self, repo_path: Path, fs: object) -> None:
        self.repo_path = repo_path
        self.fs = fs

    async def build_scope(
        self,
        base_ref: str = "HEAD",
        target_ref: str | None = None,
        context_lines: int = 5,
    ) -> tuple[list[Path], str]:
        """Build review scope from git diff.

        Returns:
            Tuple of (file_paths, formatted_diff_content).
        """
        file_diffs = DiffAnalyzer.from_git(self.repo_path, base_ref, target_ref)

        file_paths: list[Path] = []
        contents: list[str] = []

        for fd in file_diffs:
            if fd.is_deleted:
                continue

            file_paths.append(fd.path)

            try:
                content = await self._read_file(fd.path)
                context = DiffAnalyzer.extract_changed_context(fd.path, content, fd, context_lines)
                contents.append(context)
            except Exception:
                # If we can't read the file, include the diff itself
                hunk_text = "\n".join("\n".join(h.lines) for h in fd.hunks)
                contents.append(f"--- {fd.path}\n{hunk_text}")

        return file_paths, "\n\n".join(contents)

    async def _read_file(self, path: Path) -> str:
        """Read file text via the injected FS abstraction."""
        # Support both sync and async read_text methods
        read_fn = getattr(self.fs, "read_text", None)
        if read_fn is None:
            raise RuntimeError("FS object has no read_text method")
        result = read_fn(path)
        if isinstance(result, Awaitable):
            return await result  # type: ignore[no-any-return]
        return result  # type: ignore[no-any-return]
