"""
Git history forensics helpers for MUSCLE lifeline investigations.

Architecture Decision Record (ADR):
- Collect targeted blame/log evidence instead of dumping large code snapshots into prompts
- Keep optional bisect runs isolated inside a temporary clone
- Persist a separate history artifact so investigations can reference precise commit evidence
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .io_safety import atomic_write_json, atomic_write_text

logger = logging.getLogger(__name__)

REPORT_PREFIX = "lifeline_history"
MAX_FILES = 5
MAX_COMMITS = 8


@dataclass(frozen=True)
class GitCommandResult:
    stdout: str
    stderr: str
    returncode: int


class GitHistoryForensics:
    """Collect git blame, log, and optional bisect evidence for a target."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        self.reports_dir = self.project_path / ".muscle" / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def analyze(
        self,
        target_path: str,
        *,
        bisect_cmd: str | None = None,
    ) -> dict[str, Any]:
        """Return structured git-history evidence for the requested target."""
        target = Path(target_path).resolve()
        repo_root = self._repo_root(target)
        if repo_root is None:
            return {
                "available": False,
                "target_path": str(target),
                "reason": "Target is not inside a git repository.",
            }

        files = self._tracked_files(repo_root, target)
        blame_summary = self._blame_summary(repo_root, files)
        recent_commits = self._recent_commits(repo_root, target)
        report: dict[str, Any] = {
            "available": True,
            "target_path": str(target),
            "repo_root": str(repo_root),
            "files_analyzed": [str(path.relative_to(repo_root)) for path in files],
            "likely_introducing_commits": blame_summary,
            "recent_commits": recent_commits,
            "regression_window": self._regression_window(recent_commits),
            "bisect": self._run_bisect(repo_root, target, bisect_cmd) if bisect_cmd else None,
        }
        report["summary"] = self.render_summary(report)
        report["report_paths"] = self._write_report(report)
        return report

    def render_summary(self, report: dict[str, Any]) -> str:
        """Render a concise summary for lifeline prompts."""
        if not report.get("available"):
            return "Git history forensics unavailable."

        lines = [
            "Git history forensics:",
            f"- Repo root: {report['repo_root']}",
            f"- Files analyzed: {', '.join(report.get('files_analyzed', []) or ['none'])}",
        ]
        likely = report.get("likely_introducing_commits", [])
        if likely:
            lines.append("- Likely introducing commits:")
            for commit in likely[:3]:
                lines.append(
                    f"  - {commit['sha'][:10]} ({commit['date']}): {commit['subject']} "
                    f"[blamed_lines={commit['blamed_lines']}]"
                )
        recent = report.get("recent_commits", [])
        if recent:
            lines.append("- Recent evolution:")
            for commit in recent[:5]:
                lines.append(f"  - {commit['sha'][:10]} ({commit['date']}): {commit['subject']}")
        regression_window = report.get("regression_window")
        if isinstance(regression_window, dict) and regression_window:
            lines.append(
                "- Regression window: "
                f"{regression_window.get('start_date')} ({regression_window.get('start_sha', '')[:10]})"
                f" -> {regression_window.get('end_date')} ({regression_window.get('end_sha', '')[:10]})"
            )
        bisect = report.get("bisect")
        if isinstance(bisect, dict):
            if bisect.get("status") == "identified":
                lines.append(
                    f"- Bisect suspect: {bisect['first_bad_commit'][:10]} ({bisect['date']}): "
                    f"{bisect['subject']}"
                )
            elif bisect.get("status"):
                lines.append(f"- Bisect: {bisect['status']} ({bisect.get('reason', 'no details')})")
        return "\n".join(lines)

    def _repo_root(self, target: Path) -> Path | None:
        probe_dir = target if target.is_dir() else target.parent
        result = self._run_git(["rev-parse", "--show-toplevel"], cwd=probe_dir, check=False)
        if result.returncode != 0:
            return None
        root = result.stdout.strip()
        return Path(root).resolve() if root else None

    def _tracked_files(self, repo_root: Path, target: Path) -> list[Path]:
        relative_target = self._relative_target(repo_root, target)
        result = self._run_git(["ls-files", "--", relative_target], cwd=repo_root, check=False)
        files = [repo_root / line for line in result.stdout.splitlines() if line.strip()]
        if target.is_file() and target not in files:
            files.insert(0, target)
        unique_files = []
        seen: set[Path] = set()
        for file_path in files:
            resolved = file_path.resolve()
            if resolved in seen or not resolved.exists():
                continue
            seen.add(resolved)
            unique_files.append(resolved)
            if len(unique_files) >= MAX_FILES:
                break
        return unique_files

    def _blame_summary(self, repo_root: Path, files: list[Path]) -> list[dict[str, Any]]:
        counts: Counter[str] = Counter()
        for file_path in files:
            result = self._run_git(
                ["blame", "--line-porcelain", "--", str(file_path.relative_to(repo_root))],
                cwd=repo_root,
                check=False,
            )
            for line in result.stdout.splitlines():
                if re.match(r"^[0-9a-f]{40}\s", line):
                    sha = line.split()[0]
                    counts[sha] += 1

        summaries: list[dict[str, Any]] = []
        for sha, blamed_lines in counts.most_common(5):
            show = self._run_git(
                ["show", "-s", "--format=%H%x1f%ad%x1f%s", "--date=short", sha],
                cwd=repo_root,
                check=False,
            )
            parts = show.stdout.strip().split("\x1f")
            summaries.append(
                {
                    "sha": parts[0] if len(parts) > 0 else sha,
                    "date": parts[1] if len(parts) > 1 else "unknown",
                    "subject": parts[2] if len(parts) > 2 else "unknown",
                    "blamed_lines": blamed_lines,
                }
            )
        return summaries

    def _recent_commits(self, repo_root: Path, target: Path) -> list[dict[str, Any]]:
        relative_target = self._relative_target(repo_root, target)
        result = self._run_git(
            [
                "log",
                f"-n{MAX_COMMITS}",
                "--date=short",
                "--format=%H%x1f%ad%x1f%s",
                "--",
                relative_target,
            ],
            cwd=repo_root,
            check=False,
        )
        commits: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 3:
                continue
            commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
        return commits

    def _regression_window(self, recent_commits: list[dict[str, Any]]) -> dict[str, str] | None:
        if len(recent_commits) < 2:
            return None
        oldest = recent_commits[-1]
        newest = recent_commits[0]
        return {
            "start_sha": oldest["sha"],
            "start_date": oldest["date"],
            "end_sha": newest["sha"],
            "end_date": newest["date"],
        }

    def _run_bisect(self, repo_root: Path, target: Path, bisect_cmd: str) -> dict[str, Any]:
        relative_target = self._relative_target(repo_root, target)
        revisions = self._run_git(
            ["rev-list", "--reverse", "HEAD", "--", relative_target],
            cwd=repo_root,
            check=False,
        )
        commits = [line.strip() for line in revisions.stdout.splitlines() if line.strip()]
        if len(commits) < 2:
            return {"status": "skipped", "reason": "Not enough target-specific history for bisect."}

        with tempfile.TemporaryDirectory(prefix="muscle-bisect-") as temp_dir:
            clone_path = Path(temp_dir) / repo_root.name
            clone_result = subprocess.run(
                ["git", "clone", "--quiet", "--no-hardlinks", str(repo_root), str(clone_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if clone_result.returncode != 0:
                return {
                    "status": "failed",
                    "reason": clone_result.stderr.strip() or "Failed to create temporary clone.",
                }

            try:
                self._run_git(["bisect", "start"], cwd=clone_path)
                self._run_git(["bisect", "bad"], cwd=clone_path)
                self._run_git(["bisect", "good", commits[0]], cwd=clone_path)
                bisect_run = subprocess.run(
                    ["git", "bisect", "run", "/bin/sh", "-lc", bisect_cmd],
                    cwd=str(clone_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                combined_output = f"{bisect_run.stdout}\n{bisect_run.stderr}".strip()
                match = re.search(
                    r"([0-9a-f]{7,40}) is the first bad commit",
                    combined_output,
                )
                if match is None:
                    return {
                        "status": "inconclusive",
                        "reason": combined_output.splitlines()[-1]
                        if combined_output
                        else "No culprit identified.",
                    }
                sha = match.group(1)
                show = self._run_git(
                    ["show", "-s", "--format=%H%x1f%ad%x1f%s", "--date=short", sha],
                    cwd=clone_path,
                    check=False,
                )
                parts = show.stdout.strip().split("\x1f")
                return {
                    "status": "identified",
                    "first_bad_commit": parts[0] if len(parts) > 0 else sha,
                    "date": parts[1] if len(parts) > 1 else "unknown",
                    "subject": parts[2] if len(parts) > 2 else "unknown",
                }
            finally:
                self._run_git(["bisect", "reset"], cwd=clone_path, check=False)

    def _relative_target(self, repo_root: Path, target: Path) -> str:
        return str(target.relative_to(repo_root)) if target != repo_root else "."

    def _write_report(self, report: dict[str, Any]) -> dict[str, str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.reports_dir / f"{REPORT_PREFIX}_{timestamp}.json"
        md_path = self.reports_dir / f"{REPORT_PREFIX}_{timestamp}.md"
        atomic_write_json(json_path, report, indent=2, sort_keys=True)
        atomic_write_text(md_path, report["summary"] + "\n")
        return {"json": str(json_path), "markdown": str(md_path)}

    def _run_git(
        self,
        args: list[str],
        *,
        cwd: Path,
        check: bool = True,
    ) -> GitCommandResult:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and completed.returncode != 0:
            msg = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
            raise RuntimeError(msg)
        return GitCommandResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
