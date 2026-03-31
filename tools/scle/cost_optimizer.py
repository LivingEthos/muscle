"""
Cost Optimizer - Estimate and optimize token usage.

Architecture Decision Record (ADR):
- Tiered approach based on task complexity
- Estimate cost before running
- Suggest optimizations
- Cache common patterns to avoid regeneration
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path


class CostTier(Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    PROJECT = "project"


class CostOptimizer:
    CACHE_DIR = Path.home() / ".scle" / "cache"

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
        self._load_cache()

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
        cache_file = self.cache_dir / f"{task_hash}.json"

        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                return dict(data) if isinstance(data, dict) else None
            except Exception:
                return None
        return None

    def save_to_cache(self, task: str, result: str, files: list[str]) -> None:
        task_hash = self._hash_task(task)
        cache_file = self.cache_dir / f"{task_hash}.json"

        cache_data = {
            "task": task,
            "result": result,
            "files": files,
            "cached_at": str(cache_file.stat().st_mtime) if cache_file.exists() else None,
        }

        cache_file.write_text(json.dumps(cache_data, indent=2))

    def _hash_task(self, task: str) -> str:
        return hashlib.md5(task.lower().encode()).hexdigest()[:16]

    def _load_cache(self) -> None:
        index_file = self.cache_dir / "index.json"
        if index_file.exists():
            try:
                self.cache_index = json.loads(index_file.read_text())
            except Exception:
                self.cache_index = {}
        else:
            self.cache_index = {}

    def clear_cache(self) -> int:
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            if cache_file.name != "index.json":
                cache_file.unlink()
                count += 1
        return count

    def get_cache_stats(self) -> dict:
        cache_files = [f for f in self.cache_dir.glob("*.json") if f.name != "index.json"]
        total_size = sum(f.stat().st_size for f in cache_files)

        return {
            "cached_items": len(cache_files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }
