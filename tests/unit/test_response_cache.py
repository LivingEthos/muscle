"""Tests for response_cache — Phase B.3 content-addressed response cache + B.5 pack_id isolation."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.muscle.response_cache import ResponseCache


class TestResponseCache:
    """Core ResponseCache round-trip, expiry, key determinism, and clear."""

    def test_put_then_get_roundtrip(self, tmp_path: Path) -> None:
        cache = ResponseCache(db_path=tmp_path / "test.db")
        key = ResponseCache.build_key("model-x", "sys", "user")
        payload = {"tier": "mechanical", "confidence": 0.9}
        cache.put(key, "model-x", payload, ttl_seconds=3600)
        result = cache.get(key)
        assert result == payload

    def test_expired_entry_returns_none(self, tmp_path: Path) -> None:
        cache = ResponseCache(db_path=tmp_path / "test.db")
        key = ResponseCache.build_key("model-x", "sys", "user")
        cache.put(key, "model-x", {"x": 1}, ttl_seconds=1)
        time.sleep(2)
        assert cache.get(key) is None

    def test_cache_key_deterministic(self) -> None:
        k1 = ResponseCache.build_key("m", "sys", "user", [("a.py", "abc")])
        k2 = ResponseCache.build_key("m", "sys", "user", [("a.py", "abc")])
        assert k1 == k2

    def test_scope_change_invalidates(self) -> None:
        k1 = ResponseCache.build_key("m", "sys", "user", [("a.py", "hash1")])
        k2 = ResponseCache.build_key("m", "sys", "user", [("a.py", "hash2")])
        assert k1 != k2

    def test_clear_older_than(self, tmp_path: Path) -> None:
        cache = ResponseCache(db_path=tmp_path / "test.db")
        old_key = ResponseCache.build_key("m", "old", "user")
        new_key = ResponseCache.build_key("m", "new", "user")
        cache.put(old_key, "m", {"old": True}, ttl_seconds=1)
        time.sleep(2)
        cache.put(new_key, "m", {"new": True}, ttl_seconds=3600)
        from datetime import timedelta

        removed = cache.clear(older_than=timedelta(seconds=1))
        assert removed >= 1
        assert cache.get(new_key) == {"new": True}

    def test_hit_count_increments(self, tmp_path: Path) -> None:
        cache = ResponseCache(db_path=tmp_path / "test.db")
        key = ResponseCache.build_key("m", "sys", "user")
        cache.put(key, "m", {"v": 1}, ttl_seconds=3600)
        assert cache.get(key) is not None
        assert cache.get(key) is not None
        assert cache.hit_count(key) == 2


# ---------------------------------------------------------------------------
# ResponseCache.build_key — pack_id isolation (B.5)
# ---------------------------------------------------------------------------


class TestBuildKeyPackId:
    def test_different_pack_ids_produce_different_keys(self) -> None:
        key_a = ResponseCache.build_key("m2.7", "sys", "user", pack_id="pack-v1")
        key_b = ResponseCache.build_key("m2.7", "sys", "user", pack_id="pack-v2")
        assert key_a != key_b

    def test_same_pack_id_produces_same_key(self) -> None:
        key_a = ResponseCache.build_key("m2.7", "sys", "user", pack_id="pack-v1")
        key_b = ResponseCache.build_key("m2.7", "sys", "user", pack_id="pack-v1")
        assert key_a == key_b

    def test_none_pack_id_no_regression(self) -> None:
        key = ResponseCache.build_key("m2.7", "sys", "user", pack_id=None)
        assert isinstance(key, str) and len(key) == 64

    def test_none_and_omitted_pack_id_produce_same_key(self) -> None:
        key_none = ResponseCache.build_key("m2.7", "sys", "user", pack_id=None)
        key_omitted = ResponseCache.build_key("m2.7", "sys", "user")
        assert key_none == key_omitted

    def test_pack_id_and_model_id_both_influence_key(self) -> None:
        key_a = ResponseCache.build_key("m2.7", "sys", "user", pack_id="pack-v1")
        key_b = ResponseCache.build_key("m2.7-turbo", "sys", "user", pack_id="pack-v1")
        assert key_a != key_b

    def test_scope_files_still_work_with_pack_id(self) -> None:
        key_a = ResponseCache.build_key("m", "sys", "user", scope_files=[("foo.py", "abc")])
        key_b = ResponseCache.build_key("m", "sys", "user", scope_files=[("foo.py", "def")])
        assert key_a != key_b


# ---------------------------------------------------------------------------
# M27Client.chat_structured — pack_id wiring (B.5)
# ---------------------------------------------------------------------------


class TestChatStructuredPackIdWiring:
    def test_pack_v1_and_v2_produce_different_cache_keys(self) -> None:
        key_v1 = ResponseCache.build_key("m2.7", "schema-hint", "content", pack_id="pack-v1")
        key_v2 = ResponseCache.build_key("m2.7", "schema-hint", "content", pack_id="pack-v2")
        assert key_v1 != key_v2

    def test_no_pack_id_produces_valid_key(self) -> None:
        key = ResponseCache.build_key("m2.7", "schema-hint", "content", pack_id=None)
        assert isinstance(key, str) and len(key) == 64

    def test_chat_structured_passes_cache_pack_id_to_build_key(self) -> None:
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

            with (
                patch.object(M27Client, "_get_session"),
                patch.object(M27Client, "_configure_limiters"),
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
