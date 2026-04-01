"""
Unit tests for adapters/jenkins.py
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from tools.muscle.adapters.jenkins import JenkinsAdapter


class TestJenkinsAdapter:
    @pytest.fixture
    def adapter(self):
        return JenkinsAdapter(url="https://jenkins.example.com", username="user", token="token")

    def test_url_required(self):
        adapter = JenkinsAdapter()
        assert adapter.get_job_info("test-job") is None

    def test_authenticate_header(self, adapter):
        adapter._authenticate()
        import base64

        expected = base64.b64encode(b"user:token").decode()
        assert expected in adapter.session.headers["Authorization"]

    def test_get_job_info_success(self, adapter):
        mock_response = Mock(
            status_code=200,
            json=lambda: {"name": "test-job", "url": "https://jenkins.example.com/job/test-job"},
        )
        with patch.object(adapter.session, "get", return_value=mock_response) as mock_get:
            result = adapter.get_job_info("test-job")
        assert result is not None
        assert result["name"] == "test-job"
        mock_get.assert_called_once()

    def test_trigger_build_success(self, adapter):
        mock_queue_response = Mock(
            status_code=200,
            json=lambda: {"number": 123},
        )
        mock_post_response = Mock(
            status_code=200,
            headers={"Location": "https://jenkins.example.com/queue/item/123"},
        )
        mock_session = MagicMock()
        mock_session.post.return_value = mock_post_response
        mock_session.get.return_value = mock_queue_response
        adapter.session = mock_session
        result = adapter.trigger_build("test-job")
        assert result == 123

    def test_get_artifact(self, adapter):
        mock_artifact_response = Mock(
            status_code=200,
            content=b"artifact bytes",
        )
        mock_build_info_response = Mock(
            status_code=200,
            json=lambda: {
                "artifacts": [{"displayPath": "output.jar", "relativePath": "path/to/output.jar"}]
            },
        )
        mock_session = MagicMock()
        mock_session.get.side_effect = [
            mock_build_info_response,
            mock_artifact_response,
        ]
        adapter.session = mock_session
        data = adapter.get_artifact("test-job", 1, "output.jar")
        assert data == b"artifact bytes"

    def test_create_or_update_build_description(self, adapter):
        mock_response = Mock(status_code=200)
        with patch.object(adapter.session, "post", return_value=mock_response) as mock_post:
            result = adapter.create_or_update_build_description("test-job", 1, "muscle fix")
        assert result is True
        mock_post.assert_called_once()
