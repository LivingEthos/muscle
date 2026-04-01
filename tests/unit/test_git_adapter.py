"""
Unit tests for adapters/git_adapter.py
"""

from unittest.mock import Mock

from tools.muscle.adapters.git_adapter import GitAdapter


class TestGitAdapter:
    def test_is_git_repo_true(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0)
        assert adapter.is_git_repo() is True

    def test_is_git_repo_false(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=1)
        assert adapter.is_git_repo() is False

    def test_get_current_branch(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0, stdout="feature-branch\n", stderr="")
        assert adapter.get_current_branch() == "feature-branch"

    def test_get_current_branch_fallback(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=1, stdout="", stderr="")
        assert adapter.get_current_branch() == "main"

    def test_create_branch_success(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0)
        assert adapter.create_branch("feature-x") is True

    def test_create_branch_failure(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=1)
        assert adapter.create_branch("bad/branch") is False

    def test_add_files_success(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0)
        assert adapter.add_files(["file1.py", "file2.py"]) is True

    def test_add_files_failure(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=128)
        assert adapter.add_files(["nonexistent"]) is False

    def test_commit_success(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="abc1234567890def\n",
            stderr="",
        )
        result = adapter.commit("feat: add new feature")
        assert result == "abc12345"

    def test_commit_failure(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=1, stdout="", stderr="nothing to commit")
        assert adapter.commit("wip") is None

    def test_push_success(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0)
        assert adapter.push() is True

    def test_push_failure(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=1, stderr="remote not found")
        assert adapter.push() is False

    def test_get_diff_with_changes(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
            stderr="",
        )
        diff = adapter.get_diff()
        assert "diff --git" in diff

    def test_get_diff_no_changes(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
        assert adapter.get_diff() == ""

    def test_checkout_success(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=0)
        assert adapter.checkout("main") is True

    def test_checkout_failure(self, mock_subprocess):
        adapter = GitAdapter("/fake/repo")
        mock_subprocess.return_value = Mock(returncode=128, stderr="branch not found")
        assert adapter.checkout("nonexistent") is False
