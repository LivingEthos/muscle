"""
Unit tests for cost_optimizer.py
"""

import json

import pytest

from muscle.cost_optimizer import (
    HOST_MODEL_PRICING,
    M3_LONG_CONTEXT_THRESHOLD,
    CostOptimizer,
    CostTier,
    estimate_host_request_cost,
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

    def test_m3_unchanged_when_host_routing_added(self):
        # Regression pin: routing host models through estimate_request_cost must
        # leave the M3 path byte-identical. These exact figures must not drift.
        assert estimate_request_cost("MiniMax-M3", 100_000, 100_000) == pytest.approx(
            100_000 * 0.60e-6 + 100_000 * 2.40e-6
        )
        assert estimate_request_cost(
            "MiniMax-M3", 10_000, 0, cached_input_tokens=10_000
        ) == pytest.approx(10_000 * 0.12e-6)


class TestHostModelRouting:
    def test_host_model_routed_to_host_pricing(self):
        # A host model passed to estimate_request_cost must price via the host
        # table: fresh*5/M + cached*0.5/M + out*25/M for claude-opus-4-8.
        cost = estimate_request_cost("claude-opus-4-8", 100_000, 20_000, cached_input_tokens=40_000)
        fresh = 60_000  # 100_000 - 40_000 cached
        expected = fresh * 5.00e-6 + 40_000 * 0.50e-6 + 20_000 * 25.00e-6
        assert cost == pytest.approx(expected)

    def test_host_routing_matches_estimate_host_request_cost(self):
        # The host branch must defer to estimate_host_request_cost exactly.
        assert estimate_request_cost("claude-fable-5", 1_000_000, 1_000_000) == pytest.approx(
            estimate_host_request_cost("claude-fable-5", 1_000_000, 1_000_000)
        )


class TestHostPricing:
    def test_fable5_rates(self):
        # 1M input + 1M output on Fable 5 ($10/$50 per MTok).
        cost = estimate_host_request_cost("claude-fable-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(10.00 + 50.00)

    def test_fable5_cache_read_discount(self):
        # 1M input fully cached bills at $1.00/MTok instead of $10.00.
        cost = estimate_host_request_cost("claude-fable-5", 1_000_000, 0, 1_000_000)
        assert cost == pytest.approx(1.00)

    def test_opus48_is_half_fable5(self):
        fable = estimate_host_request_cost("claude-fable-5", 1_000_000, 1_000_000)
        opus = estimate_host_request_cost("claude-opus-4-8", 1_000_000, 1_000_000)
        assert opus == pytest.approx(fable / 2)

    def test_cached_tokens_clamped_to_input(self):
        cost = estimate_host_request_cost("claude-fable-5", 100, 0, 10_000)
        assert cost == pytest.approx(100 * 1.00 / 1_000_000)

    def test_unknown_host_model_fails_loudly(self):
        with pytest.raises(ValueError, match="unknown host model"):
            estimate_host_request_cost("claude-opus-99", 100, 100)

    def test_pricing_table_covers_default_and_codex(self):
        assert "claude-fable-5" in HOST_MODEL_PRICING
        assert "codex-default" in HOST_MODEL_PRICING


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
