"""
Unit tests for adapters/github.py
"""

from unittest.mock import Mock, patch

import pytest

from tools.muscle.adapters.github import GitHubAdapter


class TestGitHubAdapter:
    @pytest.fixture
    def adapter(self):
        return GitHubAdapter(token="test-token", repo="owner/repo")

    def test_get_headers(self, adapter):
        headers = adapter._get_headers()
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Accept"] == "application/vnd.github.v3+json"

    def test_repo_required_for_operations(self, adapter):
        adapter.repo = None
        assert adapter.create_pull_request("title", "body", "head") is None
        assert adapter.get_pull_request(1) is None
        assert adapter.create_review(1, "body") is None

    def test_create_pull_request_success(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(
            status_code=201,
            json=lambda: {"number": 42, "html_url": "https://github.com/owner/repo/pull/42"},
        )
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_pull_request("title", "body", "feature")
        assert result == {"number": 42, "html_url": "https://github.com/owner/repo/pull/42"}

    def test_create_pull_request_failure(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(status_code=403, json=lambda: {"error": "Forbidden"})
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_pull_request("title", "body", "feature")
        assert result is None

    def test_get_pull_request_success(self, adapter, mock_requests):
        mock_requests.get.return_value = Mock(
            status_code=200, json=lambda: {"number": 42, "state": "open"}
        )
        with patch.object(mock_requests, "get", mock_requests.get):
            result = adapter.get_pull_request(42)
        assert result is not None

    def test_create_review_success(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(status_code=201, json=lambda: {"id": 1})
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_review(42, "LGTM")
        assert result is None

    def test_create_check_run_success(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(
            status_code=201, json=lambda: {"id": 123, "status": "in_progress"}
        )
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_check_run("my-check", "abc123")
        assert result is not None

    def test_update_check_run(self, adapter, mock_requests):
        mock_requests.patch.return_value = Mock(
            status_code=200, json=lambda: {"id": 123, "status": "completed"}
        )
        with patch.object(mock_requests, "patch", mock_requests.patch):
            result = adapter.update_check_run(123, status="completed", conclusion="success")
        assert result is not None

    def test_get_file_content(self, adapter, mock_requests):
        mock_requests.get.return_value = Mock(
            status_code=200,
            json=lambda: {"content": "aW1wb3J0IG9z", "encoding": "base64"},
        )
        with patch.object(mock_requests, "get", mock_requests.get):
            content = adapter.get_file_content("src/main.py")
        assert content == "import os"

    def test_create_issue(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(
            status_code=201,
            json=lambda: {"number": 5, "html_url": "https://github.com/owner/repo/issues/5"},
        )
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_issue("Bug: crash on startup", "Steps to reproduce...")
        assert result is not None

    def test_create_issue_comment(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(status_code=201, json=lambda: {"id": 1})
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_issue_comment(5, "Fixed in abc123")
        assert result is not None

    def test_download_artifact(self, adapter, mock_requests):
        mock_requests.get.return_value = Mock(status_code=200, content=b"artifact bytes")
        with patch.object(mock_requests, "get", mock_requests.get):
            data = adapter.download_artifact(123)
        assert data == b"artifact bytes"
