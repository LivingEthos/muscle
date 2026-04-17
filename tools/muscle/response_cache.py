"""Content-addressed response cache for M2.7 structured calls."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".muscle" / "cache" / "cache.db"

RESPONSE_CACHE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS response_cache (
    key TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    response_json BLOB NOT NULL,
    tokens_saved INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL,
    hit_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_response_cache_created ON response_cache(created_at);
"""


class ResponseCache:
    """SQLite-backed content-addressed response cache for M2.7 calls."""

    def __init__(self, db_path: Path = DEFAULT_DB) -> None:
        self._db = db_path
        self._db.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.executescript(RESPONSE_CACHE_SCHEMA_SQL)

    @staticmethod
    def build_key(
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        scope_files: list[tuple[str, str]] | None = None,
        pack_id: str | None = None,
    ) -> str:
        """Deterministic cache key.

        scope_files: list of (path, sha256) tuples. Any change invalidates.
        pack_id: B.5 pack content-hash if this call consumes a pack.
        """
        scope = json.dumps(sorted(scope_files or []))
        pack = pack_id or ""
        payload = f"{model_id}||{system_prompt}||{user_prompt}||{scope}||{pack}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT response_json, created_at, ttl_seconds FROM response_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        created = datetime.fromisoformat(row[1])
        if datetime.now(timezone.utc) - created > timedelta(seconds=row[2]):
            return None  # expired
        # Update hit counter
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE response_cache SET hit_count = hit_count + 1 WHERE key = ?", (key,)
            )
        result: dict = json.loads(row[0])
        return result

    def put(
        self,
        key: str,
        model_id: str,
        response: dict,
        ttl_seconds: int,
        tokens_saved: int = 0,
    ) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO response_cache
                   (key, model_id, response_json, tokens_saved, created_at, ttl_seconds, hit_count)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (
                    key,
                    model_id,
                    json.dumps(response),
                    tokens_saved,
                    datetime.now(timezone.utc).isoformat(),
                    ttl_seconds,
                ),
            )

    def clear(self, older_than: timedelta | None = None) -> int:
        """Delete entries older than `older_than`. Return count removed."""
        with sqlite3.connect(self._db) as conn:
            if older_than:
                cutoff = (datetime.now(timezone.utc) - older_than).isoformat()
                cur = conn.execute("DELETE FROM response_cache WHERE created_at < ?", (cutoff,))
            else:
                cur = conn.execute("DELETE FROM response_cache")
            return cur.rowcount

    def hit_count(self, key: str) -> int:
        """Return the current hit count for a cache entry (0 if missing)."""
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT hit_count FROM response_cache WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else 0
