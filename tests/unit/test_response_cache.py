"""
Unit tests for tools/muscle/response_cache.py (B.5: pack_id cache isolation).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.response_cache import ResponseCache


# ---------------------------------------------------------------------------
# ResponseCache.build_key — pack_id isolation
# ---------------------------------------------------------------------------


class TestBuildKey:
    def test_different_pack_ids_produce_different_keys(self):
        key_a = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id="pack-v1",
        )
        key_b = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id="pack-v2",
        )
        assert key_a != key_b

    def test_same_pack_id_produces_same_key(self):
        key_a = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id="pack-v1",
        )
        key_b = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id="pack-v1",
        )
        assert key_a == key_b

    def test_none_pack_id_works_no_regression(self):
        """pack_id=None must not raise and must produce a consistent key."""
        key = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id=None,
        )
        assert isinstance(key, str)
        assert len(key) == 64  # sha256 hex

    def test_none_and_empty_pack_id_produce_same_key(self):
        """None and omitted pack_id are both treated as 'no pack'."""
        key_none = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id=None,
        )
        key_omitted = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
        )
        assert key_none == key_omitted

    def test_pack_id_isolates_from_model_id_change(self):
        """Both pack_id and model_id independently influence the key."""
        key_a = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            pack_id="pack-v1",
        )
        key_b = ResponseCache.build_key(
            model_id="m2.7-turbo",
            system_prompt="sys",
            user_prompt="user",
            pack_id="pack-v1",
        )
        assert key_a != key_b

    def test_scope_files_still_work(self):
        """scope_files parameter continues to influence the key."""
        key_a = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            scope_files=[("foo.py", "abc123")],
        )
        key_b = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="sys",
            user_prompt="user",
            scope_files=[("foo.py", "def456")],
        )
        assert key_a != key_b


# ---------------------------------------------------------------------------
# M27Client.chat_structured — pack_id wiring
# ---------------------------------------------------------------------------


class TestChatStructuredPackIdWiring:
    """Assert that chat_structured passes _cache_pack_id to build_key."""

    def _make_client(self, cache_pack_id: str | None = None) -> object:
        """Build a minimal M27Client with cache enabled but no real API calls."""
        from tools.muscle.m27_client import M27Client

        with patch.object(M27Client, "_get_session"):
            with patch.object(M27Client, "_configure_limiters"):
                client = M27Client.__new__(M27Client)
                client.api_key = "test-key"
                client.base_url = "https://test"
                client.model = "m2.7"
                client.timeout = 30
                client.max_retries = 1
                client._rate_limit_errors = 0
                client._last_request_time = None
                client._telemetry_sink = None
                client._model_identity = {}
                client._cache_db_path = Path(tempfile.mktemp(suffix=".db"))
                client._cache_pack_id = cache_pack_id
        return client

    def test_pack_v1_and_pack_v2_produce_different_cache_keys(self):
        """Two clients with different pack_ids must generate different cache keys."""
        key_v1 = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="schema-hint",
            user_prompt="content",
            pack_id="pack-v1",
        )
        key_v2 = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="schema-hint",
            user_prompt="content",
            pack_id="pack-v2",
        )
        assert key_v1 != key_v2, "Different pack_ids must produce different cache keys"

    def test_no_pack_id_no_regression(self):
        """cache_pack_id=None must produce a valid key (no regression)."""
        key = ResponseCache.build_key(
            model_id="m2.7",
            system_prompt="schema-hint",
            user_prompt="content",
            pack_id=None,
        )
        assert isinstance(key, str) and len(key) == 64

    def test_chat_structured_passes_cache_pack_id_to_build_key(self):
        """
        When chat_structured is called on a client with _cache_pack_id set,
        ResponseCache.build_key must receive that pack_id value.
        """
        import json

        from pydantic import BaseModel

        from tools.muscle.m27_client import M27Client

        class FakeSchema(BaseModel):
            value: int

        captured: list[dict] = []
        original_build_key = ResponseCache.build_key

        def tracking_build_key(**kwargs: object) -> str:
            captured.append(dict(kwargs))
            return original_build_key(**kwargs)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "cache.db"

            with patch.object(M27Client, "_get_session"), patch.object(
                M27Client, "_configure_limiters"
            ):
                client = M27Client.__new__(M27Client)
                client.api_key = "test-key"
                client.base_url = "https://test"
                client.model = "m2.7"
                client.timeout = 30
                client.max_retries = 1
                client._rate_limit_errors = 0
                client._last_request_time = None
                client._telemetry_sink = None
                client._model_identity = {}
                client._cache_db_path = db_path
                client._cache_pack_id = "sha256-of-pack-content"

            valid_response = json.dumps({"value": 42})
            with (
                patch.object(client, "chat", return_value=(valid_response, MagicMock())),
                patch.object(ResponseCache, "build_key", side_effect=tracking_build_key),
            ):
                result = client.chat_structured(
                    schema=FakeSchema,
                    messages=[{"role": "user", "content": "give me json"}],
                )

        assert result.value == 42
        assert len(captured) == 1
        assert captured[0].get("pack_id") == "sha256-of-pack-content"
