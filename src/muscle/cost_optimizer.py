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

# Default model used for cost estimation. Mirrors m27_client.DEFAULT_MODEL but is
# kept as a local literal to avoid an import cycle (pricing is model-string driven).
DEFAULT_PRICING_MODEL = "MiniMax-M3"

# MiniMax-M3 pricing (USD per token), tiered by input length (MiniMax docs, 2026-06):
# input <=512K tokens bills at the standard rate; input >512K bills at the
# long-context rate (exactly 2x). Cache-hit (passive prefix-cache) input tokens
# bill at a flat discounted rate. Output is billed at the input tier's output rate.
M3_LONG_CONTEXT_THRESHOLD = 512_000
M3_INPUT_STANDARD = 0.60 / 1_000_000
M3_INPUT_LONG = 1.20 / 1_000_000
M3_OUTPUT_STANDARD = 2.40 / 1_000_000
M3_OUTPUT_LONG = 4.80 / 1_000_000
M3_CACHE_HIT_INPUT = 0.12 / 1_000_000

# Fallback flat pricing for non-M3 models (approx MiniMax-M2.7 base rates).
FALLBACK_INPUT_RATE = 0.28 / 1_000_000
FALLBACK_OUTPUT_RATE = 1.20 / 1_000_000

# Host-model pricing (USD per token): (input, output, cache_read). Used to express
# delegation and crush savings in host dollars. Anthropic list prices, 2026-06:
# Fable 5 $10/$50, Opus 4.8/4.7 $5/$25, Sonnet 4.6 $3/$15; cache reads ~0.1x input.
# Codex hosts bill in the Opus range per docs; modeled at Opus rates.
HOST_MODEL_PRICING: dict[str, tuple[float, float, float]] = {
    "claude-fable-5": (10.00 / 1_000_000, 50.00 / 1_000_000, 1.00 / 1_000_000),
    "claude-opus-4-8": (5.00 / 1_000_000, 25.00 / 1_000_000, 0.50 / 1_000_000),
    "claude-opus-4-7": (5.00 / 1_000_000, 25.00 / 1_000_000, 0.50 / 1_000_000),
    "claude-sonnet-4-6": (3.00 / 1_000_000, 15.00 / 1_000_000, 0.30 / 1_000_000),
    "codex-default": (5.00 / 1_000_000, 25.00 / 1_000_000, 0.50 / 1_000_000),
}
DEFAULT_HOST_PRICING_MODEL = "claude-fable-5"


def estimate_host_request_cost(
    host_model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Estimate the USD cost of one request on a *host* model (Fable 5, Opus, Codex).

    Raises ``ValueError`` for unknown host models rather than silently falling back
    to some default pricing — a typo here would corrupt every savings report.
    """
    pricing = HOST_MODEL_PRICING.get(host_model)
    if pricing is None:
        known = ", ".join(sorted(HOST_MODEL_PRICING))
        raise ValueError(f"unknown host model {host_model!r}; known: {known}")
    input_rate, output_rate, cache_rate = pricing
    input_tokens = max(0, input_tokens)
    output_tokens = max(0, output_tokens)
    cached = max(0, min(cached_input_tokens, input_tokens))
    fresh_input = input_tokens - cached
    return fresh_input * input_rate + cached * cache_rate + output_tokens * output_rate


def m3_pricing_tier(input_tokens: int) -> str:
    """Return the M3 input-length pricing tier for a request."""
    return "long_context" if input_tokens > M3_LONG_CONTEXT_THRESHOLD else "standard"


def estimate_request_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Estimate the USD cost of one request under the model's pricing.

    Host models (Fable 5, Opus, Codex — anything in ``HOST_MODEL_PRICING``) are
    routed to ``estimate_host_request_cost`` so a Claude *execution* provider is
    priced with its real host rates. For MiniMax-M3 this applies the input-length
    tier (>512K input doubles both input and output rates) and bills any
    cached-prefix input tokens at the discounted cache-hit rate. Other non-M3
    models use a flat fallback rate.
    """
    if model in HOST_MODEL_PRICING:
        return estimate_host_request_cost(model, input_tokens, output_tokens, cached_input_tokens)
    input_tokens = max(0, input_tokens)
    output_tokens = max(0, output_tokens)
    if "m3" not in (model or "").lower():
        return input_tokens * FALLBACK_INPUT_RATE + output_tokens * FALLBACK_OUTPUT_RATE

    cached = max(0, min(cached_input_tokens, input_tokens))
    fresh_input = input_tokens - cached
    long_context = input_tokens > M3_LONG_CONTEXT_THRESHOLD
    input_rate = M3_INPUT_LONG if long_context else M3_INPUT_STANDARD
    output_rate = M3_OUTPUT_LONG if long_context else M3_OUTPUT_STANDARD
    return fresh_input * input_rate + cached * M3_CACHE_HIT_INPUT + output_tokens * output_rate


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

    def estimate_cost(self, task: str, model: str = DEFAULT_PRICING_MODEL) -> dict:
        tier = self.estimate_tier(task)
        max_tokens = self.get_max_tokens(tier)

        estimated_input_tokens = len(task) * 2
        estimated_output_tokens = max_tokens

        estimated_cost = estimate_request_cost(
            model, estimated_input_tokens, estimated_output_tokens
        )
        pricing_tier = m3_pricing_tier(estimated_input_tokens) if "m3" in model.lower() else "flat"

        return {
            "tier": tier,
            "model": model,
            "pricing_tier": pricing_tier,
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
