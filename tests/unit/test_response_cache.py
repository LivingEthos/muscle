"""Tests for response_cache — Phase B.3 content-addressed response cache."""

from __future__ import annotations

import time
from pathlib import Path

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
        # Insert with a 1-second TTL so it expires quickly
        cache.put(old_key, "m", {"old": True}, ttl_seconds=1)
        time.sleep(2)
        cache.put(new_key, "m", {"new": True}, ttl_seconds=3600)
        # Clear everything older than 1 second — the old entry's creation time
        # is >1s ago so it should be removed; the new one was just inserted.
        from datetime import timedelta

        removed = cache.clear(older_than=timedelta(seconds=1))
        assert removed >= 1
        # The fresh entry should survive.
        assert cache.get(new_key) == {"new": True}

    def test_hit_count_increments(self, tmp_path: Path) -> None:
        cache = ResponseCache(db_path=tmp_path / "test.db")
        key = ResponseCache.build_key("m", "sys", "user")
        cache.put(key, "m", {"v": 1}, ttl_seconds=3600)
        assert cache.get(key) is not None
        assert cache.get(key) is not None
        assert cache.hit_count(key) == 2
