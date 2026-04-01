"""
Unit tests for adapters/gitlab.py
"""

from unittest.mock import Mock, patch

import pytest

from tools.muscle.adapters.gitlab import GitLabAdapter


class TestGitLabAdapter:
    @pytest.fixture
    def adapter(self):
        return GitLabAdapter(token="test-token", project_id="owner/repo")

    def test_get_headers(self, adapter):
        headers = adapter._get_headers()
        assert headers["PRIVATE-TOKEN"] == "test-token"
        assert headers["Content-Type"] == "application/json"

    def test_project_required(self, adapter):
        adapter.project_id = None
        assert adapter.create_merge_request("feat", "main", "title", "desc") is None
        assert adapter.get_merge_request(1) is None

    def test_create_merge_request_success(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(
            status_code=201,
            json=lambda: {
                "iid": 42,
                "web_url": "https://gitlab.com/owner/repo/-/merge_requests/42",
            },
        )
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_merge_request("feat", "main", "title", "desc")
        assert result is not None

    def test_get_merge_request_success(self, adapter, mock_requests):
        mock_requests.get.return_value = Mock(
            status_code=200, json=lambda: {"iid": 42, "state": "opened"}
        )
        with patch.object(mock_requests, "get", mock_requests.get):
            result = adapter.get_merge_request(42)
        assert result is not None

    def test_create_note_success(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(status_code=201, json=lambda: {"id": 1})
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_note(42, "LGTM!")
        assert result is not None

    def test_create_pipeline_success(self, adapter, mock_requests):
        mock_requests.post.return_value = Mock(
            status_code=201, json=lambda: {"id": 99, "status": "pending"}
        )
        with patch.object(mock_requests, "post", mock_requests.post):
            result = adapter.create_pipeline("main")
        assert result is not None

    def test_get_pipeline_status(self, adapter, mock_requests):
        mock_requests.get.return_value = Mock(
            status_code=200, json=lambda: {"id": 99, "status": "success"}
        )
        with patch.object(mock_requests, "get", mock_requests.get):
            result = adapter.get_pipeline_status(99)
        assert result == "success"

    def test_download_artifact(self, adapter, mock_requests):
        mock_requests.get.return_value = Mock(status_code=200, content=b"artifact data")
        with patch.object(mock_requests, "get", mock_requests.get):
            data = adapter.download_artifact(99, "build/output.jar")
        assert data is not None
        assert data == b"artifact data"
