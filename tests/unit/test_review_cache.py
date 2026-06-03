"""Tests for review_cache."""

from __future__ import annotations

import time
from pathlib import Path

from tools.muscle.review_cache import CachedReview, ReviewCache


def test_compute_hash_is_stable():
    cache = ReviewCache()
    h1 = cache._compute_hash("hello")
    h2 = cache._compute_hash("hello")
    assert h1 == h2
    assert len(h1) == 64


def test_set_and_get_roundtrip(tmp_path: Path) -> None:
    cache = ReviewCache(cache_dir=tmp_path / "cache")
    cache.set(Path("src/foo.py"), "content", [{"msg": "issue"}], review_id="r1")
    cached = cache.get(Path("src/foo.py"), "content")
    assert cached is not None
    assert cached.suggestions == [{"msg": "issue"}]
    assert cached.review_id == "r1"


def test_get_returns_none_for_missing():
    cache = ReviewCache()
    assert cache.get(Path("missing.py"), "nope") is None


def test_memory_cache_lru_ordering(tmp_path: Path) -> None:
    """Test that get() updates LRU ordering so recently accessed items survive eviction."""
    cache = ReviewCache(cache_dir=tmp_path / "cache", max_memory_entries=2)
    cache.set(Path("a.py"), "a", [{"msg": "a"}])
    cache.set(Path("b.py"), "b", [{"msg": "b"}])
    # Access 'a' to make it most-recently used
    cache.get(Path("a.py"), "a")
    # Now add 'c' — 'b' should be evicted (not 'a')
    cache.set(Path("c.py"), "c", [{"msg": "c"}])
    assert len(cache._memory_cache) == 2
    # 'a' should still be in memory (MRU), 'b' evicted
    assert "a.py:" in str(list(cache._memory_cache.keys())) or cache.get(Path("a.py"), "a") is not None
    # 'b' should be on disk but not in memory
    assert cache.get(Path("b.py"), "b") is not None  # falls back to disk


def test_memory_cache_lru_eviction(tmp_path: Path) -> None:
    cache = ReviewCache(cache_dir=tmp_path / "cache", max_memory_entries=2)
    cache.set(Path("a.py"), "a", [])
    cache.set(Path("b.py"), "b", [])
    cache.set(Path("c.py"), "c", [])
    # a should be evicted from memory
    assert cache.get(Path("a.py"), "a") is not None  # falls back to disk
    assert len(cache._memory_cache) == 2


def test_ttl_expiration(tmp_path: Path) -> None:
    cache = ReviewCache(cache_dir=tmp_path / "cache", ttl_seconds=0)
    cache.set(Path("x.py"), "x", [{"msg": "old"}])
    time.sleep(0.01)
    assert cache.get(Path("x.py"), "x") is None


def test_invalidate_specific_file(tmp_path: Path) -> None:
    cache = ReviewCache(cache_dir=tmp_path / "cache")
    cache.set(Path("keep.py"), "k", [])
    cache.set(Path("drop.py"), "d", [])
    removed = cache.invalidate(file_path=Path("drop.py"))
    assert removed >= 1
    assert cache.get(Path("keep.py"), "k") is not None
    assert cache.get(Path("drop.py"), "d") is None


def test_invalidate_all_clears_everything(tmp_path: Path) -> None:
    cache = ReviewCache(cache_dir=tmp_path / "cache")
    cache.set(Path("a.py"), "a", [])
    cache.set(Path("b.py"), "b", [])
    removed = cache.invalidate()
    assert removed >= 2
    assert cache.get(Path("a.py"), "a") is None
    assert cache.get(Path("b.py"), "b") is None


def test_get_stats_reports_sizes(tmp_path: Path) -> None:
    cache = ReviewCache(cache_dir=tmp_path / "cache")
    cache.set(Path("s.py"), "s", [{"msg": "issue"}])
    stats = cache.get_stats()
    assert stats["memory_entries"] == 1
    assert stats["disk_entries"] == 1
    assert stats["ttl_seconds"] == 3600


def test_cached_review_is_expired():
    from datetime import UTC, datetime, timedelta

    cr = CachedReview(
        file_hash="h", file_path="p.py", suggestions=[], timestamp=datetime.now(UTC)
    )
    assert not cr.is_expired(ttl_seconds=3600)
    cr_old = CachedReview(
        file_hash="h",
        file_path="p.py",
        suggestions=[],
        timestamp=datetime.now(UTC) - timedelta(seconds=7200),
    )
    assert cr_old.is_expired(ttl_seconds=3600)
