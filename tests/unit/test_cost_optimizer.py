"""
Unit tests for cost_optimizer.py
"""

import json

import pytest

from tools.muscle.cost_optimizer import CostOptimizer, CostTier


class TestCostTier:
    def test_values(self):
        assert CostTier.SIMPLE.value == "simple"
        assert CostTier.MEDIUM.value == "medium"
        assert CostTier.COMPLEX.value == "complex"
        assert CostTier.PROJECT.value == "project"


class TestCostOptimizer:
    @pytest.fixture
    def optimizer(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "index.json").write_text(json.dumps([]))
        return CostOptimizer(cache_dir=str(cache_dir))

    def test_estimate_tier_simple(self, optimizer):
        tier = optimizer.estimate_tier("add two numbers with regex validation")
        assert tier == CostTier.SIMPLE

    def test_estimate_tier_complex(self, optimizer):
        tier = optimizer.estimate_tier(
            "design and implement a distributed microservices architecture "
            "with event sourcing and CQRS patterns"
        )
        assert tier in [CostTier.COMPLEX, CostTier.PROJECT]

    def test_get_max_tokens(self, optimizer):
        assert optimizer.get_max_tokens(CostTier.SIMPLE) == 500
        assert optimizer.get_max_tokens(CostTier.MEDIUM) == 2000
        assert optimizer.get_max_tokens(CostTier.COMPLEX) == 4096
        assert optimizer.get_max_tokens(CostTier.PROJECT) == 8192

    def test_estimate_cost(self, optimizer):
        result = optimizer.estimate_cost("implement user authentication")
        assert "estimated_input_tokens" in result
        assert "estimated_output_tokens" in result
        assert "estimated_cost_usd" in result
        assert "recommendation" in result

    def test_cache_roundtrip(self, optimizer, tmp_path):
        optimizer.save_to_cache("test task", "test result", ["file1.py"])
        cached = optimizer.get_from_cache("test task")
        assert cached is not None

    def test_cache_miss(self, optimizer):
        result = optimizer.get_from_cache("nonexistent task xyzabc")
        assert result is None

    def test_clear_cache(self, optimizer, tmp_path):
        optimizer.save_to_cache("task1", "result1", ["f1.py"])
        optimizer.save_to_cache("task2", "result2", ["f2.py"])
        count = optimizer.clear_cache()
        assert count >= 1

    def test_hash_task(self, optimizer):
        hash1 = optimizer._hash_task("build a calculator")
        hash2 = optimizer._hash_task("build a calculator")
        assert hash1 == hash2
        hash3 = optimizer._hash_task("build a different thing")
        assert hash1 != hash3

    def test_get_cache_stats(self, optimizer, tmp_path):
        optimizer.save_to_cache("task", "result", ["f.py"])
        stats = optimizer.get_cache_stats()
        assert "cached_items" in stats
        assert "total_size_bytes" in stats
