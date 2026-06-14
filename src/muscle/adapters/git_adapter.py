"""
Git Adapter - Auto-commit successful generations.

Architecture Decision Record (ADR):
- Auto-commits on success only (not on failures)
- Creates feature branch per session
- Uses conventional commit messages
- Supports GitHub/GitLab remote integration
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitAdapterError(RuntimeError):
    """Raised when an unexpected git command failure should not be swallowed.

    Fix: AD-05. Distinguishes a legitimate empty diff from a crashed/denied
    git invocation so callers can surface real errors.
    """


class GitAdapter:
    def __init__(self, repo_path: str = "."):
        self.repo_path = Path(repo_path)

    def is_git_repo(self) -> bool:
        """Check if directory is a git repository."""
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=self.repo_path, capture_output=True, text=True
        )
        return result.returncode == 0

    def get_current_branch(self) -> str:
        """Get current branch name."""
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=self.repo_path, capture_output=True, text=True
        )
        return result.stdout.strip() if result.returncode == 0 else "main"

    def create_branch(self, branch_name: str) -> bool:
        """Create a new branch."""
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def add_files(self, files: list[str]) -> bool:
        """Stage files for commit."""
        result = subprocess.run(
            ["git", "add"] + files, cwd=self.repo_path, capture_output=True, text=True
        )
        return result.returncode == 0

    def commit(self, message: str) -> str | None:
        """Commit staged files. Returns commit hash or None."""
        result = subprocess.run(
            ["git", "commit", "-m", message], cwd=self.repo_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.repo_path, capture_output=True, text=True
            )
            return hash_result.stdout.strip()[:8]
        return None

    def push(self, remote: str = "origin", branch: str | None = None) -> bool:
        """Push branch to remote."""
        if branch is None:
            branch = self.get_current_branch()
        result = subprocess.run(
            ["git", "push", "-u", remote, branch],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def get_changed_files(self) -> list[str]:
        """Return changed files, including untracked files."""
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []

        files: list[str] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", maxsplit=1)[1].strip()
            if path:
                files.append(path)
        return files

    def get_diff(self, files: list[str] | None = None) -> str:
        """Get diff of files or all changes.

        Fix: AD-05. On non-zero git exit, raise ``GitAdapterError`` carrying
        stderr so callers can distinguish "no changes" (returns empty string)
        from a broken repo state.
        """
        cmd = ["git", "diff"]
        if files:
            cmd += files
        result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.error("git diff failed: %s", stderr)
            raise GitAdapterError(f"git diff failed: {stderr}")
        return result.stdout

    def checkout(self, branch: str) -> bool:
        """Checkout a branch."""
        result = subprocess.run(
            ["git", "checkout", branch], cwd=self.repo_path, capture_output=True, text=True
        )
        return result.returncode == 0
