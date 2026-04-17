"""
Unit tests for adapters/mcp_client.py
"""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestMCPClient:
    @pytest.fixture
    def mock_popen(self):
        with patch("subprocess.Popen") as mock, patch(
            "tools.muscle.adapters.mcp_client.select.select"
        ) as mock_select:
            process_mock = MagicMock()
            process_mock.stdin = MagicMock()
            process_mock.stdout = MagicMock()
            process_mock.stderr = MagicMock()
            process_mock.poll.return_value = None
            process_mock.stdout.fileno.return_value = 0
            process_mock.stderr.fileno.return_value = 0
            mock_select.side_effect = lambda read, *_args, **_kwargs: (read, [], [])
            mock.return_value = process_mock
            yield mock, process_mock

    def test_start_server_success(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        client = MCPClient(api_key="test-key")
        assert client.start_server() is True

    def test_start_server_no_key(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        client = MCPClient(api_key=None)
        assert client.api_key is None

    def test_stop_server(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        client = MCPClient(api_key="test-key")
        client.start_server()
        client.stop_server()
        process_mock.terminate.assert_called_once()

    def test_send_request_success(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        process_mock.stdin.read.return_value = ""
        process_mock.stdout.readline.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "response"}]}}
        )

        client = MCPClient(api_key="test-key")
        client.start_server()
        result = client._send_request("test_tool", {"arg": "value"})
        assert result == {"content": [{"text": "response"}]}

    def test_context_manager(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        client = MCPClient(api_key="test-key")
        with client as c:
            assert c is not None
        process_mock.terminate.assert_called_once()

    def test_text_to_speech(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        process_mock.stdin.read.return_value = ""
        process_mock.stdout.readline.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "audio_id"}]}}
        )

        client = MCPClient(api_key="test-key")
        client.start_server()
        result = client.text_to_speech("Hello world")
        assert result == "audio_id"

    def test_generate_image(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        process_mock.stdin.read.return_value = ""
        process_mock.stdout.readline.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": "image_id"}]}}
        )

        client = MCPClient(api_key="test-key")
        client.start_server()
        result = client.generate_image("a cat")
        assert result == "image_id"

    def test_list_voices(self, mock_popen):
        from tools.muscle.adapters.mcp_client import MCPClient

        mock, process_mock = mock_popen
        process_mock.stdin.read.return_value = ""
        process_mock.stdout.readline.return_value = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"text": '[{"voice_id": "v1", "name": "Voice 1"}]'}]},
            }
        )

        client = MCPClient(api_key="test-key")
        client.start_server()
        voices = client.list_voices()
        assert isinstance(voices, list)

    def test_send_request_raises_on_timeout(self, mock_popen, monkeypatch):
        from tools.muscle.adapters.mcp_client import MCPClient

        _, process_mock = mock_popen
        monkeypatch.setattr(
            "tools.muscle.adapters.mcp_client.select.select",
            lambda *args, **kwargs: ([], [], []),
        )

        client = MCPClient(api_key="test-key", request_timeout_seconds=0.01)
        client.start_server()

        with pytest.raises(TimeoutError):
            client._send_request("test_tool", {"arg": "value"})
