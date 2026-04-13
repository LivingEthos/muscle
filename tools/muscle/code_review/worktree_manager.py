"""
Worktree Manager - Isolated git worktrees for review execution.

Architecture Decision Record (ADR):
- Use git worktrees instead of copying full repositories for mutating review flows
- Sync the user's current in-scope working tree state into the worktree before review
- Apply back only the verified post-sync delta so unrelated local edits remain untouched
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WorktreeSession:
    repo_root: str
    worktree_path: str
    branch_name: str
    base_branch: str


@dataclass(frozen=True)
class WorktreeSyncResult:
    relative_target: str
    tracked_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_target": self.relative_target,
            "tracked_files": self.tracked_files,
            "untracked_files": self.untracked_files,
        }


@dataclass(frozen=True)
class WorktreeDelta:
    modified_files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.modified_files or self.new_files or self.deleted_files)

    def to_dict(self) -> dict[str, object]:
        return {
            "modified_files": self.modified_files,
            "new_files": self.new_files,
            "deleted_files": self.deleted_files,
        }


class GitWorktreeManager:
    """Create, sync, diff, and clean up isolated git worktrees."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        self.repo_root = self._detect_repo_root()

    def is_available(self) -> bool:
        return self.repo_root is not None

    def create(self, session_id: str) -> WorktreeSession | None:
        if self.repo_root is None:
            return None

        base_branch = self._current_branch(self.repo_root)
        branch_name = f"muscle/review-{session_id}"
        worktree_base = Path(tempfile.gettempdir()) / "muscle-worktrees" / self.repo_root.name
        worktree_base.mkdir(parents=True, exist_ok=True)
        worktree_path = worktree_base / session_id

        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

        result = self._run_git(
            self.repo_root,
            "worktree",
            "add",
            "--force",
            "-b",
            branch_name,
            str(worktree_path),
            "HEAD",
        )
        if result.returncode != 0:
            return None

        return WorktreeSession(
            repo_root=str(self.repo_root),
            worktree_path=str(worktree_path),
            branch_name=branch_name,
            base_branch=base_branch,
        )

    def map_target(self, session: WorktreeSession, target_path: str) -> str:
        if self.repo_root is None:
            return target_path
        target = Path(target_path).resolve()
        try:
            relative = target.relative_to(self.repo_root)
        except ValueError:
            return target_path
        return str(Path(session.worktree_path) / relative)

    def map_back_path(self, session: WorktreeSession, path: str) -> str:
        worktree_root = Path(session.worktree_path).resolve()
        candidate = Path(path).resolve()
        try:
            relative = candidate.relative_to(worktree_root)
        except ValueError:
            return path
        return str(Path(session.repo_root) / relative)

    def sync_local_changes(self, session: WorktreeSession, target_path: str) -> WorktreeSyncResult:
        if self.repo_root is None:
            msg = "Git worktrees are unavailable outside a repository"
            raise RuntimeError(msg)

        relative_target = self._relative_to_repo(target_path)
        tracked_files = self._list_changed_tracked_files(relative_target)
        diff = self._run_git(
            self.repo_root,
            "diff",
            "--binary",
            "HEAD",
            "--",
            relative_target,
            text=False,
        )
        if diff.returncode != 0:
            msg = f"Failed to build worktree sync patch for {relative_target}"
            raise RuntimeError(msg)

        if diff.stdout:
            apply_result = subprocess.run(
                [
                    "git",
                    "-C",
                    session.worktree_path,
                    "apply",
                    "--binary",
                    "--allow-empty",
                    "--whitespace=nowarn",
                    "-",
                ],
                input=diff.stdout,
                capture_output=True,
                check=False,
            )
            if apply_result.returncode != 0:
                stderr = apply_result.stderr.decode("utf-8", errors="replace").strip()
                msg = f"Failed to apply synced changes into worktree: {stderr or 'unknown error'}"
                raise RuntimeError(msg)

        untracked_files = self._list_untracked_files(relative_target)
        for rel_path in untracked_files:
            source = self.repo_root / rel_path
            destination = Path(session.worktree_path) / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        return WorktreeSyncResult(
            relative_target=relative_target,
            tracked_files=tracked_files,
            untracked_files=untracked_files,
        )

    def capture_snapshot(self, session: WorktreeSession, target_path: str) -> dict[str, str]:
        relative_target = self._relative_to_repo(target_path)
        scope_root = Path(session.worktree_path) / relative_target
        snapshot: dict[str, str] = {}

        if scope_root.is_file():
            snapshot[relative_target] = self._hash_file(scope_root)
            return snapshot

        if not scope_root.exists():
            return snapshot

        for path in sorted(scope_root.rglob("*")):
            if not path.is_file():
                continue
            rel_path = str(path.relative_to(session.worktree_path))
            snapshot[rel_path] = self._hash_file(path)

        return snapshot

    def collect_delta(
        self,
        session: WorktreeSession,
        target_path: str,
        baseline_snapshot: dict[str, str],
    ) -> WorktreeDelta:
        current_snapshot = self.capture_snapshot(session, target_path)
        modified_files: list[str] = []
        new_files: list[str] = []
        deleted_files: list[str] = []

        for rel_path, current_hash in current_snapshot.items():
            baseline_hash = baseline_snapshot.get(rel_path)
            if baseline_hash is None:
                new_files.append(rel_path)
            elif baseline_hash != current_hash:
                modified_files.append(rel_path)

        for rel_path in baseline_snapshot:
            if rel_path not in current_snapshot:
                deleted_files.append(rel_path)

        return WorktreeDelta(
            modified_files=sorted(modified_files),
            new_files=sorted(new_files),
            deleted_files=sorted(deleted_files),
        )

    def apply_delta(self, session: WorktreeSession, delta: WorktreeDelta) -> list[str]:
        applied_paths: list[str] = []

        for rel_path in [*delta.modified_files, *delta.new_files]:
            source = Path(session.worktree_path) / rel_path
            destination = Path(session.repo_root) / rel_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            applied_paths.append(str(destination))

        for rel_path in delta.deleted_files:
            destination = Path(session.repo_root) / rel_path
            if destination.exists():
                destination.unlink()
            applied_paths.append(str(destination))

        return applied_paths

    def cleanup(self, session: WorktreeSession) -> None:
        self._run_git(
            Path(session.repo_root),
            "worktree",
            "remove",
            "--force",
            session.worktree_path,
        )
        self._run_git(
            Path(session.repo_root),
            "branch",
            "-D",
            session.branch_name,
        )
        shutil.rmtree(session.worktree_path, ignore_errors=True)

    def _relative_to_repo(self, target_path: str) -> str:
        if self.repo_root is None:
            msg = "Git worktrees are unavailable outside a repository"
            raise RuntimeError(msg)

        target = Path(target_path).resolve()
        try:
            return str(target.relative_to(self.repo_root))
        except ValueError as exc:
            msg = f"Target path {target} is outside git repository {self.repo_root}"
            raise RuntimeError(msg) from exc

    def _list_changed_tracked_files(self, relative_target: str) -> list[str]:
        if self.repo_root is None:
            return []
        result = self._run_git(
            self.repo_root,
            "diff",
            "--name-only",
            "HEAD",
            "--",
            relative_target,
        )
        if result.returncode != 0:
            return []
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8")
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    def _list_untracked_files(self, relative_target: str) -> list[str]:
        if self.repo_root is None:
            return []
        result = self._run_git(
            self.repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            relative_target,
        )
        if result.returncode != 0:
            return []
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8")
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    def _detect_repo_root(self) -> Path | None:
        result = self._run_git(self.project_path, "rev-parse", "--show-toplevel")
        if result.returncode != 0:
            return None
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.decode("utf-8")
        return Path(stdout.strip()).resolve()

    @staticmethod
    def _current_branch(repo_root: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        branch = result.stdout.strip()
        return branch or "HEAD"

    @staticmethod
    def _run_git(
        cwd: Path,
        *args: str,
        text: bool = True,
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=text,
            check=False,
        )

    @staticmethod
    def _hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
