"""
Unit tests for change_capture.py (MUS-021).
"""

from unittest.mock import Mock

from tools.muscle.change_capture import ChangeCapture


class TestChangeCapture:
    """Tests for ChangeCapture class."""

    def test_init_takes_project_path(self, tmp_path):
        cc = ChangeCapture(str(tmp_path))
        assert cc.project_path == tmp_path

    def test_init_accepts_pathlib_path(self, tmp_path):
        cc = ChangeCapture(tmp_path)
        assert cc.project_path == tmp_path

    def test_is_git_project_false_when_not_git_repo(self, mock_subprocess):
        """Non-git project returns False."""
        mock_subprocess.return_value = Mock(returncode=1)
        cc = ChangeCapture("/fake/non-git")
        assert cc.is_git_project() is False

    def test_is_git_project_true_when_git_repo(self, mock_subprocess):
        """Git project returns True."""
        mock_subprocess.return_value = Mock(returncode=0)
        cc = ChangeCapture("/fake/repo")
        assert cc.is_git_project() is True

    def test_collect_changed_files_empty_when_not_git(self, mock_subprocess):
        """Non-git project returns empty list."""
        mock_subprocess.return_value = Mock(returncode=1)
        cc = ChangeCapture("/fake/non-git")
        assert cc.collect_changed_files() == []

    def test_collect_changed_files_returns_file_list(self, mock_subprocess):
        """Git project returns list of changed files."""
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=" M tracked.py\n?? newfile.py\n",
            stderr="",
        )
        cc = ChangeCapture("/fake/repo")
        assert cc.collect_changed_files() == ["tracked.py", "newfile.py"]

    def test_collect_changed_files_handles_renamed(self, mock_subprocess):
        """Renamed files are handled correctly."""
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout="R  old.py -> renamed.py\n",
            stderr="",
        )
        cc = ChangeCapture("/fake/repo")
        assert cc.collect_changed_files() == ["renamed.py"]

    def test_collect_diff_summary_empty_when_not_git(self, mock_subprocess):
        """Non-git project returns empty string."""
        mock_subprocess.return_value = Mock(returncode=1)
        cc = ChangeCapture("/fake/non-git")
        assert cc.collect_diff_summary() == ""

    def test_collect_diff_summary_parses_stat_output(self, mock_subprocess):
        """Diff summary parses --stat --compact-summary output."""
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=" file.py | 5 +++ --- \n 2 files changed, 15 insertions(+), 5 deletions(-)",
            stderr="",
        )
        cc = ChangeCapture("/fake/repo")
        summary = cc.collect_diff_summary()
        assert "file.py" in summary
        assert "5" in summary

    def test_collect_diff_summary_empty_on_error(self, mock_subprocess):
        """Returns empty string on git error."""
        mock_subprocess.side_effect = Exception("git error")
        cc = ChangeCapture("/fake/repo")
        assert cc.collect_diff_summary() == ""

    def test_store_change_events_no_changes_returns_empty(self, mock_subprocess):
        """When no changes, returns empty list."""
        mock_subprocess.return_value = Mock(returncode=1)  # Not a git repo
        cc = ChangeCapture("/fake/non-git")

        mock_pm = Mock()
        event_ids = cc.store_change_events(mock_pm, review_run_id=None)
        assert event_ids == []

    def test_store_change_events_calls_insert_change_event(self, mock_subprocess):
        """Stores change event via project_memory."""
        mock_subprocess.return_value = Mock(returncode=0, stdout=" M foo.py\n", stderr="")
        cc = ChangeCapture("/fake/repo")

        mock_pm = Mock()
        mock_pm.insert_change_event.return_value = 42

        event_ids = cc.store_change_events(mock_pm, review_run_id=99)

        assert event_ids == [42]
        mock_pm.insert_change_event.assert_called_once()
        call_kwargs = mock_pm.insert_change_event.call_args
        assert call_kwargs.kwargs["review_run_id"] == 99
        assert "foo.py" in call_kwargs.kwargs["changed_files_json"]

    def test_store_change_events_graceful_on_db_error(self, mock_subprocess):
        """DB errors are handled gracefully, returning empty list."""
        mock_subprocess.return_value = Mock(returncode=0, stdout=" M foo.py\n", stderr="")
        cc = ChangeCapture("/fake/repo")

        mock_pm = Mock()
        mock_pm.insert_change_event.side_effect = Exception("DB error")

        event_ids = cc.store_change_events(mock_pm, review_run_id=None)
        assert event_ids == []

    def test_capture_and_store_returns_summary_dict(self, mock_subprocess):
        """capture_and_store returns dict with event_ids, counts, etc."""
        mock_subprocess.return_value = Mock(
            returncode=0,
            stdout=" M bar.py\n?? baz.py\n",
            stderr="",
        )
        cc = ChangeCapture("/fake/repo")

        mock_pm = Mock()
        mock_pm.insert_change_event.return_value = 7

        result = cc.capture_and_store(mock_pm, review_run_id=5)

        assert result["event_ids"] == [7]
        assert result["changed_files_count"] == 2
        assert "bar.py" in result["changed_files"]
        assert "baz.py" in result["changed_files"]

    def test_handles_git_command_failure_gracefully(self, mock_subprocess):
        """Git command failures don't crash capture."""
        mock_subprocess.return_value = Mock(returncode=128, stderr="not a git repo")
        cc = ChangeCapture("/fake/repo")

        mock_pm = Mock()
        # Should not raise
        result = cc.capture_and_store(mock_pm, review_run_id=None)
        assert result["changed_files_count"] == 0
        assert result["event_ids"] == []

    def test_changed_files_json_is_valid_json(self, mock_subprocess):
        """changed_files_json field contains valid JSON list."""
        import json

        mock_subprocess.return_value = Mock(
            returncode=0, stdout=" M test.py\n?? new.py\n", stderr=""
        )
        cc = ChangeCapture("/fake/repo")

        mock_pm = Mock()
        mock_pm.insert_change_event.return_value = 1

        cc.store_change_events(mock_pm, review_run_id=None)

        call_kwargs = mock_pm.insert_change_event.call_args
        changed_files = json.loads(call_kwargs.kwargs["changed_files_json"])
        assert changed_files == ["test.py", "new.py"]
