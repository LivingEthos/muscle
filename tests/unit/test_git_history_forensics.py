"""
Unit tests for git history forensics.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.muscle.git_history_forensics import GitHistoryForensics


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def test_git_history_forensics_collects_commit_attribution(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "muscle@example.com")
    _git(repo, "config", "user.name", "MUSCLE Test")

    target = repo / "app.py"
    target.write_text("VALUE = 'stable'\n", encoding="utf-8")
    _commit(repo, "initial stable implementation")

    target.write_text("VALUE = 'broken'\n", encoding="utf-8")
    _commit(repo, "introduce regression")

    report = GitHistoryForensics(str(repo)).analyze(str(target))

    assert report["available"] is True
    assert report["likely_introducing_commits"]
    subjects = [item["subject"] for item in report["recent_commits"]]
    assert "introduce regression" in subjects
    assert Path(report["report_paths"]["json"]).exists()


def test_git_history_forensics_optional_bisect_identifies_first_bad_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "muscle@example.com")
    _git(repo, "config", "user.name", "MUSCLE Test")

    target = repo / "app.py"
    target.write_text("VALUE = 'stable'\n", encoding="utf-8")
    _commit(repo, "initial stable implementation")

    target.write_text("VALUE = 'broken'\n", encoding="utf-8")
    _commit(repo, "introduce regression")

    target.write_text("VALUE = 'broken'\nFLAG = True\n", encoding="utf-8")
    _commit(repo, "follow-up cleanup")

    bisect_cmd = (
        f"{sys.executable} -c "
        '"import pathlib,sys;'
        "sys.exit(1 if 'broken' in pathlib.Path('app.py').read_text() else 0)\""
    )
    report = GitHistoryForensics(str(repo)).analyze(str(target), bisect_cmd=bisect_cmd)

    assert report["bisect"]["status"] == "identified"
    assert report["bisect"]["subject"] == "introduce regression"
