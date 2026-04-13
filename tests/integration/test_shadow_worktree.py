from __future__ import annotations

import subprocess
from pathlib import Path

from tools.muscle.code_review.shadow_broker import ShadowBroker
from tools.muscle.code_review.types import Intensity, ReviewMode
from tools.muscle.code_review.worktree_manager import GitWorktreeManager


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class TestGitWorktreeManager:
    def test_create_and_cleanup_worktree(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "muscle@example.com")
        _git(repo, "config", "user.name", "MUSCLE")
        (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")
        _git(repo, "add", "app.py")
        _git(repo, "commit", "-m", "init")

        manager = GitWorktreeManager(str(repo))
        session = manager.create("job12345")

        assert session is not None
        mapped = manager.map_target(session, str(repo / "app.py"))
        assert Path(mapped).exists()

        manager.cleanup(session)
        assert not Path(session.worktree_path).exists()

    def test_sync_and_apply_back_only_post_sync_delta(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "muscle@example.com")
        _git(repo, "config", "user.name", "MUSCLE")
        (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
        (repo / "notes.txt").write_text("outside\n", encoding="utf-8")
        _git(repo, "add", "app.py", "notes.txt")
        _git(repo, "commit", "-m", "init")

        (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
        (repo / "scratch.py").write_text("scratch = True\n", encoding="utf-8")
        (repo / "notes.txt").write_text("outside local edit\n", encoding="utf-8")

        manager = GitWorktreeManager(str(repo))
        session = manager.create("job-sync")
        assert session is not None

        sync = manager.sync_local_changes(session, str(repo))
        assert "app.py" in sync.tracked_files
        assert "scratch.py" in sync.untracked_files

        baseline = manager.capture_snapshot(session, str(repo))
        mapped_app = Path(manager.map_target(session, str(repo / "app.py")))
        mapped_app.write_text("value = 3\n", encoding="utf-8")
        mapped_new = Path(session.worktree_path) / "generated.py"
        mapped_new.write_text("generated = True\n", encoding="utf-8")

        delta = manager.collect_delta(session, str(repo), baseline)
        applied = manager.apply_delta(session, delta)

        assert str(repo / "app.py") in applied
        assert str(repo / "generated.py") in applied
        assert (repo / "app.py").read_text(encoding="utf-8") == "value = 3\n"
        assert (repo / "scratch.py").read_text(encoding="utf-8") == "scratch = True\n"
        assert (repo / "generated.py").read_text(encoding="utf-8") == "generated = True\n"
        assert (repo / "notes.txt").read_text(encoding="utf-8") == "outside local edit\n"

        manager.cleanup(session)

    def test_deleted_file_propagates_back(self, tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init")
        _git(repo, "config", "user.email", "muscle@example.com")
        _git(repo, "config", "user.name", "MUSCLE")
        (repo / "obsolete.py").write_text("print('bye')\n", encoding="utf-8")
        _git(repo, "add", "obsolete.py")
        _git(repo, "commit", "-m", "init")

        manager = GitWorktreeManager(str(repo))
        session = manager.create("job-delete")
        assert session is not None

        manager.sync_local_changes(session, str(repo))
        baseline = manager.capture_snapshot(session, str(repo))
        Path(manager.map_target(session, str(repo / "obsolete.py"))).unlink()

        delta = manager.collect_delta(session, str(repo), baseline)
        assert "obsolete.py" in delta.deleted_files
        manager.apply_delta(session, delta)
        assert not (repo / "obsolete.py").exists()

        manager.cleanup(session)


class TestShadowBrokerMetadata:
    def test_shadow_job_persists_workflow_metadata(self, tmp_path: Path):
        project = tmp_path / "project"
        project.mkdir()
        broker = ShadowBroker(project_path=str(project))
        job_id = broker.create_job(
            "/target",
            ReviewMode.REVIEW,
            Intensity.MODERATE,
            workflow_name="review-comprehensive",
        )

        updated = broker.update_job_metadata(
            job_id,
            execution_mode="worktree",
            workflow_name="review-comprehensive",
            worktree_path="/tmp/worktree",
            base_branch="main",
            artifact_dir="/tmp/artifacts",
            scope_json='{"complexity":"small"}',
        )

        job = broker.get_job(job_id)
        assert updated is True
        assert job is not None
        assert job["execution_mode"] == "worktree"
        assert job["workflow_name"] == "review-comprehensive"
        assert job["worktree_path"] == "/tmp/worktree"
        assert job["base_branch"] == "main"
        assert job["artifact_dir"] == "/tmp/artifacts"
