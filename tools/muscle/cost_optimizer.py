"""
Cost Optimizer - Estimate and optimize token usage.

Architecture Decision Record (ADR):
- Tiered approach based on task complexity
- Estimate cost before running
- Suggest optimizations
- SQLite cache for fast lookups and LRU eviction
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class CostTier(Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    PROJECT = "project"


class CostOptimizer:
    CACHE_DIR = Path.home() / ".muscle" / "cache"
    MAX_CACHE_SIZE = 1000

    SIMPLE_KEYWORDS = [
        "regex",
        "format",
        "validate",
        "simple",
        "hello",
        "add two",
        "multiply",
        "calculate",
        "fibonacci",
    ]

    MEDIUM_KEYWORDS = [
        "class",
        "function",
        "api",
        "endpoint",
        "handler",
        "middleware",
        "decorator",
        "generator",
    ]

    COMPLEX_KEYWORDS = [
        "microservice",
        "database",
        "auth",
        "jwt",
        "oauth",
        "websocket",
        "async",
        "distributed",
        "cache",
    ]

    PROJECT_KEYWORDS = [
        "project",
        "application",
        "system",
        "platform",
        "full-stack",
        "monolith",
        "backend",
        "frontend",
    ]

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else self.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._conn_lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        self.cache_dir / "cache.db"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cost_cache (
                    task_hash TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    result TEXT NOT NULL,
                    files TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 1,
                    last_accessed TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_accessed_at ON cost_cache(last_accessed)
            """)
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        with self._conn_lock:
            if self._conn is not None:
                try:
                    self._conn.execute("SELECT 1")
                    return self._conn
                except (sqlite3.Error, sqlite3.ProgrammingError):
                    self._conn = None

            db_path = self.cache_dir / "cache.db"
            conn = sqlite3.connect(str(db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
            self._conn = conn
            return conn

    def estimate_tier(self, task: str) -> CostTier:
        task_lower = task.lower()

        project_score = sum(1 for kw in self.PROJECT_KEYWORDS if kw in task_lower)
        complex_score = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in task_lower)
        medium_score = sum(1 for kw in self.MEDIUM_KEYWORDS if kw in task_lower)
        simple_score = sum(1 for kw in self.SIMPLE_KEYWORDS if kw in task_lower)

        if "multiple files" in task_lower or "several files" in task_lower:
            project_score += 2
        if "2 files" in task_lower or "three files" in task_lower:
            complex_score += 1

        tier_map: dict[CostTier, int] = {
            CostTier.PROJECT: project_score,
            CostTier.COMPLEX: complex_score,
            CostTier.MEDIUM: medium_score,
            CostTier.SIMPLE: simple_score,
        }

        return max(tier_map.items(), key=lambda x: x[1])[0]

    def get_max_tokens(self, tier: CostTier) -> int:
        tier_tokens: dict[CostTier, int] = {
            CostTier.SIMPLE: 500,
            CostTier.MEDIUM: 2000,
            CostTier.COMPLEX: 4096,
            CostTier.PROJECT: 8192,
        }
        return tier_tokens.get(tier, 2000)

    def estimate_cost(self, task: str) -> dict:
        tier = self.estimate_tier(task)
        max_tokens = self.get_max_tokens(tier)

        estimated_input_tokens = len(task) * 2
        estimated_output_tokens = max_tokens

        estimated_cost = (estimated_input_tokens * 0.000001) + (estimated_output_tokens * 0.000003)

        return {
            "tier": tier,
            "max_tokens": max_tokens,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "estimated_cost_usd": round(estimated_cost, 6),
            "recommendation": self._get_recommendation(tier, task),
        }

    def _get_recommendation(self, tier: CostTier, task: str) -> str:
        if tier == CostTier.SIMPLE:
            return "Simple task - should complete quickly with minimal tokens"
        elif tier == CostTier.MEDIUM:
            return "Medium complexity - standard generation with good results expected"
        elif tier == CostTier.COMPLEX:
            return "Complex task - may require multiple iterations, budget accordingly"
        else:
            return "Large project - consider breaking into smaller tasks if possible"

    def get_from_cache(self, task: str) -> dict | None:
        task_hash = self._hash_task(task)
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            cursor.execute(
                """
                UPDATE cost_cache
                SET access_count = access_count + 1, last_accessed = ?
                WHERE task_hash = ?
                """,
                (now, task_hash),
            )
            conn.commit()

            if cursor.rowcount == 0:
                return None

            cursor.execute(
                "SELECT task, result, files FROM cost_cache WHERE task_hash = ?",
                (task_hash,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "task": row["task"],
                    "result": row["result"],
                    "files": row["files"].split(",") if row["files"] else [],
                }
        except sqlite3.Error as e:
            logger.warning(f"Cache lookup failed: {e}")
        return None

    def save_to_cache(self, task: str, result: str, files: list[str]) -> None:
        task_hash = self._hash_task(task)
        now = datetime.now().isoformat()
        files_str = ",".join(files) if files else ""

        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM cost_cache")
            count = cursor.fetchone()[0]

            if count >= self.MAX_CACHE_SIZE:
                cursor.execute(
                    """
                    DELETE FROM cost_cache
                    WHERE task_hash IN (
                        SELECT task_hash FROM cost_cache
                        ORDER BY last_accessed ASC
                        LIMIT ?
                    )
                    """,
                    (count - self.MAX_CACHE_SIZE + 100,),
                )

            cursor.execute(
                """
                INSERT OR REPLACE INTO cost_cache
                (task_hash, task, result, files, created_at, access_count, last_accessed)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (task_hash, task, result, files_str, now, now),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Cache save failed: {e}")

    def _hash_task(self, task: str) -> str:
        return hashlib.md5(task.lower().encode()).hexdigest()[:16]

    def clear_cache(self) -> int:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cost_cache")
            row = cursor.fetchone()
            count = int(row[0]) if row else 0
            cursor.execute("DELETE FROM cost_cache")
            conn.commit()
            return count
        except sqlite3.Error as e:
            logger.warning(f"Cache clear failed: {e}")
            return 0

    def get_cache_stats(self) -> dict:
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cost_cache")
            count = cursor.fetchone()[0]
            return {
                "cached_items": count,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
            }
        except sqlite3.Error as e:
            logger.warning(f"Cache stats failed: {e}")
            return {"cached_items": 0, "total_size_bytes": 0, "total_size_mb": 0.0}
