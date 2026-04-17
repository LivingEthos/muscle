"""
Unit tests for webhook_notifier.py
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.muscle.webhook_notifier import WebhookEvent, WebhookNotifier


class TestWebhookNotifier:
    def test_disabled_when_no_url(self):
        notifier = WebhookNotifier(webhook_url=None)
        assert notifier.enabled is False

    def test_enabled_when_url_provided(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        assert notifier.enabled is True

    # CLI-03: HTTPS enforcement
    def test_rejects_http_url(self):
        with pytest.raises(ValueError, match="HTTPS"):
            WebhookNotifier(webhook_url="http://evil.example/hook")

    def test_accepts_https_url(self):
        notifier = WebhookNotifier(webhook_url="https://ok.example/hook")
        assert notifier.enabled is True
        assert notifier.webhook_url == "https://ok.example/hook"

    def test_accepts_localhost_http_url(self):
        # localhost is in the allowlist for local dev / testing
        notifier = WebhookNotifier(webhook_url="http://localhost/hook")
        assert notifier.enabled is True

    def test_accepts_loopback_http_url(self):
        notifier = WebhookNotifier(webhook_url="http://127.0.0.1/hook")
        assert notifier.enabled is True

    def test_rejects_http_url_from_env(self, monkeypatch):
        monkeypatch.setenv("MUSCLE_WEBHOOK_URL", "http://evil.example/hook")
        with pytest.raises(ValueError, match="HTTPS"):
            WebhookNotifier(webhook_url=None)

    def test_send_noop_when_disabled(self):
        notifier = WebhookNotifier(webhook_url=None)
        notifier.send(WebhookEvent.SESSION_START, "sess-1", {})

    @pytest.mark.asyncio
    async def test_send_async_success(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")

        mock_response = MagicMock()
        mock_response.status = 200

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session_ctx)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_session_ctx.post = MagicMock(return_value=mock_post_ctx)

        with patch("aiohttp.ClientSession", return_value=mock_session_ctx):
            from tools.muscle.webhook_notifier import WebhookPayload

            payload = WebhookPayload(
                event="session_start",
                session_id="sess-1",
                timestamp="2026-03-31T00:00:00Z",
                data={"task": "test"},
            )
            result = await notifier._send_async(payload)
            assert result is True

    @pytest.mark.asyncio
    async def test_send_async_http_error(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")

        mock_response = MagicMock()
        mock_response.status = 500

        mock_session = MagicMock()
        mock_session.__aenter__ = MagicMock(return_value=mock_session)
        mock_session.__aexit__ = MagicMock(return_value=None)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=MagicMock(return_value=mock_response),
                __aexit__=MagicMock(return_value=None),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from tools.muscle.webhook_notifier import WebhookPayload

            payload = WebhookPayload(
                event="session_start",
                session_id="sess-1",
                timestamp="2026-03-31T00:00:00Z",
                data={"task": "test"},
            )
            result = await notifier._send_async(payload)
            assert result is False

    @pytest.mark.asyncio
    async def test_send_async_connection_error(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")

        with patch("aiohttp.ClientSession", side_effect=ConnectionError("Network unreachable")):
            from tools.muscle.webhook_notifier import WebhookPayload

            payload = WebhookPayload(
                event="session_start",
                session_id="sess-1",
                timestamp="2026-03-31T00:00:00Z",
                data={"task": "test"},
            )
            result = await notifier._send_async(payload)
            assert result is False

    def test_send_async_disabled(self):
        notifier = WebhookNotifier(webhook_url=None)
        result = notifier.send(WebhookEvent.SESSION_START, "sess-1", {"task": "test"})
        assert result is None

    def test_send_session_start(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        with patch.object(notifier, "send", return_value=None) as mock_send:
            notifier.send_session_start("sess-1", "test task", {"max_iterations": 5})
            mock_send.assert_called_once()

    def test_send_session_success(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        with patch.object(notifier, "send", return_value=None) as mock_send:
            notifier.send_session_success("sess-1", 3, 5000)
            mock_send.assert_called_once()

    def test_send_budget_warning(self):
        notifier = WebhookNotifier(webhook_url="https://example.com/webhook")
        with patch.object(notifier, "send", return_value=None) as mock_send:
            notifier.send_budget_warning("sess-1", 0.75, 25000)
            mock_send.assert_called_once()
