"""
Webhook Notifier - Send HTTP notifications for session events.

Architecture Decision Record (ADR):
- Async non-blocking sends (don't slow down the loop)
- Supports generic HTTP POST with JSON body
- Events: session_start, iteration_complete, session_success, session_failure, budget_warning, budget_exceeded
- Config via SCLE_WEBHOOK_URL environment variable
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class WebhookEvent(Enum):
    SESSION_START = "session_start"
    ITERATION_COMPLETE = "iteration_complete"
    SESSION_SUCCESS = "session_success"
    SESSION_FAILURE = "session_failure"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class WebhookPayload:
    event: str
    session_id: str
    timestamp: str
    data: dict[str, Any]


class WebhookNotifier:
    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("SCLE_WEBHOOK_URL")
        self._enabled = bool(self.webhook_url)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _send_async(self, payload: WebhookPayload) -> bool:
        """Send webhook notification asynchronously."""
        if not self._enabled or not self.webhook_url:
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload.__dict__,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status < 400:
                        logger.info(f"Webhook sent: {payload.event}")
                        return True
                    else:
                        logger.warning(f"Webhook failed: {response.status}")
                        return False
        except Exception as e:
            logger.warning(f"Webhook error: {e}")
            return False

    def send(self, event: WebhookEvent, session_id: str, data: dict[str, Any]) -> None:
        """Send webhook notification (fire and forget)."""
        payload = WebhookPayload(
            event=event.value,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data,
        )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_in_executor(None, lambda: asyncio.run(self._send_async(payload)))
        except Exception as e:
            logger.warning(f"Could not send webhook: {e}")

    def send_session_start(self, session_id: str, task: str, config: dict) -> None:
        self.send(WebhookEvent.SESSION_START, session_id, {"task": task, "config": config})

    def send_iteration_complete(
        self, session_id: str, iteration: int, success: bool, tokens: int
    ) -> None:
        self.send(
            WebhookEvent.ITERATION_COMPLETE,
            session_id,
            {"iteration": iteration, "success": success, "tokens": tokens},
        )

    def send_session_success(self, session_id: str, iterations: int, total_tokens: int) -> None:
        self.send(
            WebhookEvent.SESSION_SUCCESS,
            session_id,
            {"iterations": iterations, "total_tokens": total_tokens},
        )

    def send_session_failure(self, session_id: str, reason: str) -> None:
        self.send(WebhookEvent.SESSION_FAILURE, session_id, {"reason": reason})

    def send_budget_warning(self, session_id: str, percent: float, remaining: int) -> None:
        self.send(
            WebhookEvent.BUDGET_WARNING,
            session_id,
            {"percent": percent, "remaining": remaining},
        )

    def send_budget_exceeded(self, session_id: str) -> None:
        self.send(WebhookEvent.BUDGET_EXCEEDED, session_id, {})
