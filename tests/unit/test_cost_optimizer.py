"""
Unit tests for cost_optimizer.py
"""

import json

import pytest

from tools.muscle.cost_optimizer import (
    M3_LONG_CONTEXT_THRESHOLD,
    CostOptimizer,
    CostTier,
    estimate_request_cost,
    m3_pricing_tier,
)


class TestM3Pricing:
    def test_standard_tier_rates(self):
        # 1M input + 1M output at the standard (<=512K input) tier.
        # Tier is set by input length; 1M input crosses into long-context, so
        # use a sub-threshold input to exercise the standard rate explicitly.
        cost = estimate_request_cost("MiniMax-M3", 100_000, 100_000)
        assert cost == pytest.approx(100_000 * 0.60e-6 + 100_000 * 2.40e-6)

    def test_long_context_tier_doubles(self):
        big = M3_LONG_CONTEXT_THRESHOLD + 1
        standard = estimate_request_cost("MiniMax-M3", 100_000, 100_000)
        # Same token counts but crossing the 512K input boundary doubles rates.
        long_ctx = estimate_request_cost("MiniMax-M3", big, big)
        per_tok_standard = standard / 200_000
        per_tok_long = long_ctx / (2 * big)
        assert per_tok_long == pytest.approx(per_tok_standard * 2)

    def test_cache_hit_tokens_discounted(self):
        no_cache = estimate_request_cost("MiniMax-M3", 10_000, 0, cached_input_tokens=0)
        cached = estimate_request_cost("MiniMax-M3", 10_000, 0, cached_input_tokens=10_000)
        # Fully-cached input bills at $0.12/M vs $0.60/M (80% cheaper).
        assert cached == pytest.approx(10_000 * 0.12e-6)
        assert cached < no_cache

    def test_pricing_tier_helper(self):
        assert m3_pricing_tier(1000) == "standard"
        assert m3_pricing_tier(M3_LONG_CONTEXT_THRESHOLD) == "standard"
        assert m3_pricing_tier(M3_LONG_CONTEXT_THRESHOLD + 1) == "long_context"

    def test_non_m3_uses_flat_fallback(self):
        cost = estimate_request_cost("MiniMax-M2.7", 1_000_000, 1_000_000)
        assert cost == pytest.approx(1_000_000 * 0.28e-6 + 1_000_000 * 1.20e-6)

    def test_estimate_cost_reports_model_and_tier(self, tmp_path):
        opt = CostOptimizer(cache_dir=str(tmp_path / "c"))
        result = opt.estimate_cost("add two numbers")
        assert result["model"] == "MiniMax-M3"
        assert result["pricing_tier"] == "standard"
        assert result["estimated_cost_usd"] >= 0


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
