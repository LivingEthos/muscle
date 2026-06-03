"""Review caching with content hashing.

Architecture Decision Record (ADR):
- SHA-256 content hashing gives deterministic cache keys.
- Two-tier cache (memory LRU + disk with TTL) balances speed and persistence.
- Subdirectory sharding (first 2 hash chars) prevents directory bloat.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class CachedReview:
    """A cached review result."""

    file_hash: str
    file_path: str
    suggestions: list[dict[str, Any]]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    review_id: str = ""

    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """Check if the cache entry has expired."""
        return datetime.now(timezone.utc) - self.timestamp > timedelta(seconds=ttl_seconds)


class ReviewCache:
    """Caches review results by file content hash."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl_seconds: int = 3600,
        max_memory_entries: int = 1000,
    ) -> None:
        self.cache_dir = cache_dir or Path.home() / ".cache" / "muscle" / "reviews"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.max_memory_entries = max_memory_entries
        self._eviction_count = 0
        self._memory_cache: OrderedDict[str, CachedReview] = OrderedDict()

    def _compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of file content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _cache_path(self, file_path: Path, file_hash: str) -> Path:
        """Get the cache file path for a file path and content hash."""
        # Include file path hash to avoid collisions between files with same content
        path_hash = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:8]
        # Use first 2 chars of content hash as subdirectory
        return self.cache_dir / file_hash[:2] / f"{path_hash}_{file_hash}.json"

    def get(self, file_path: Path, content: str) -> CachedReview | None:
        """Get cached review if available and not expired."""
        file_hash = self._compute_hash(content)
        cache_key = f"{file_path}:{file_hash}"

        # Check memory cache first
        if cache_key in self._memory_cache:
            cached = self._memory_cache[cache_key]
            if not cached.is_expired(self.ttl_seconds):
                self._memory_cache.move_to_end(cache_key)
                return cached
            del self._memory_cache[cache_key]

        # Check disk cache
        cache_file = self._cache_path(file_path, file_hash)
        if cache_file.exists():
            try:
                with open(cache_file, encoding="utf-8") as f:
                    data = json.load(f)
                cached = CachedReview(
                    file_hash=data["file_hash"],
                    file_path=data["file_path"],
                    suggestions=data["suggestions"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    review_id=data.get("review_id", ""),
                )
                if not cached.is_expired(self.ttl_seconds):
                    self._memory_cache[cache_key] = cached
                    self._memory_cache.move_to_end(cache_key)
                    # Enforce memory limit after loading from disk
                    while len(self._memory_cache) > self.max_memory_entries:
                        self._memory_cache.popitem(last=False)
                        self._eviction_count += 1
                    return cached
                else:
                    # Clean up expired cache (ignore read-only fs errors)
                    try:
                        cache_file.unlink()
                    except OSError:
                        pass
            except (json.JSONDecodeError, KeyError, OSError):
                pass

        return None

    def set(
        self,
        file_path: Path,
        content: str,
        suggestions: list[dict[str, Any]],
        review_id: str = "",
    ) -> None:
        """Cache review results for a file."""
        file_hash = self._compute_hash(content)
        cache_key = f"{file_path}:{file_hash}"

        cached = CachedReview(
            file_hash=file_hash,
            file_path=str(file_path),
            suggestions=suggestions,
            review_id=review_id,
        )

        # Store in memory (move to end for LRU ordering)
        self._memory_cache[cache_key] = cached
        self._memory_cache.move_to_end(cache_key)

        # Evict oldest entry if at capacity
        while len(self._memory_cache) > self.max_memory_entries:
            self._memory_cache.popitem(last=False)
            self._eviction_count += 1

        # Store on disk
        cache_file = self._cache_path(file_path, file_hash)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "file_hash": cached.file_hash,
                    "file_path": cached.file_path,
                    "suggestions": cached.suggestions,
                    "timestamp": cached.timestamp.isoformat(),
                    "review_id": cached.review_id,
                },
                f,
                indent=2,
            )

    def invalidate(self, file_path: Path | None = None) -> int:
        """Invalidate cache entries. Returns count removed."""
        removed = 0

        if file_path is None:
            # Clear all cache
            self._memory_cache.clear()
            for cache_file in self.cache_dir.rglob("*.json"):
                cache_file.unlink()
                removed += 1
        else:
            # Clear specific file entries from memory
            keys_to_remove = [k for k in self._memory_cache if k.startswith(f"{file_path}:")]
            for key in keys_to_remove:
                del self._memory_cache[key]
                removed += 1
            # Also clear from disk
            for cache_file in self.cache_dir.rglob("*.json"):
                try:
                    with open(cache_file, encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("file_path") == str(file_path):
                        cache_file.unlink()
                        removed += 1
                except (json.JSONDecodeError, OSError):
                    pass

        return removed

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        disk_entries = len(list(self.cache_dir.rglob("*.json")))
        memory_entries = len(self._memory_cache)

        # Calculate total size
        total_size = 0
        for cache_file in self.cache_dir.rglob("*.json"):
            total_size += cache_file.stat().st_size

        return {
            "memory_entries": memory_entries,
            "max_memory_entries": self.max_memory_entries,
            "eviction_count": self._eviction_count,
            "disk_entries": disk_entries,
            "total_size_bytes": total_size,
            "cache_dir": str(self.cache_dir),
            "ttl_seconds": self.ttl_seconds,
        }
