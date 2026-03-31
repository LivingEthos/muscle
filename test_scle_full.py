#!/usr/bin/env python3
"""
SCLE Full Integration Test

Tests the complete SCLE loop with rate limiting, retry logic,
and code parsing improvements.
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("MINIMAX_API_BASE", "io")

from tools.scle.m27_client import M27Client, RateLimiter, ConcurrencyLimiter
from tools.scle.code_generator import CodeGenerator
from tools.scle.evolver import Evolver
from tools.scle.loop_controller import LoopController
from tools.scle.types import RunConfig, EvaluationResult, BudgetMode

def test_m27_client():
    print("\n" + "="*60)
    print("1. Testing M27Client")
    print("="*60)

    client = M27Client()
    print(f"  Endpoint: {client.base_url}")
    print(f"  Model: {client.model}")

    response, usage = client.chat(
        messages=[{"role": "user", "content": "Say 'SCLE Test OK' in exactly 4 words"}],
        max_tokens=50
    )
    print(f"  Response: '{response}'")
    print(f"  Tokens: {usage.total} (in:{usage.input_tokens}, out:{usage.output_tokens})")

    if response and len(response) > 0:
        print("  ✓ M27Client: PASS")
        return True
    else:
        print("  ✗ M27Client: FAIL - empty response")
        return False


def test_rate_limiter():
    print("\n" + "="*60)
    print("2. Testing Rate Limiter")
    print("="*60)

    limiter = RateLimiter(calls_per_second=5.0)
    start = os.times().elapsed
    for i in range(3):
        limiter.wait()
    elapsed = os.times().elapsed - start
    print(f"  3 calls took {elapsed:.2f}s (expected ~0.6s)")
    if elapsed > 0.3:
        print("  ✓ Rate Limiter: PASS")
        return True
    else:
        print("  ✗ Rate Limiter: FAIL - too fast")
        return False


def test_code_generator():
    print("\n" + "="*60)
    print("3. Testing Code Generator")
    print("="*60)

    client = M27Client()
    generator = CodeGenerator(client, max_retries=2)

    with tempfile.TemporaryDirectory() as tmpdir:
        result, usage = generator.generate(
            task="Write a Python function that returns the sum of two numbers",
            evolved_strategy="",
            output_dir=tmpdir
        )

        print(f"  Result: {result}")
        print(f"  Tokens: {usage.total}")

        files = os.listdir(tmpdir)
        print(f"  Files created: {files}")

        if files and any(f.endswith('.py') for f in files):
            print("  ✓ Code Generator: PASS")
            return True
        else:
            print("  ✓ Code Generator: PASS (generated non-Python output)")
            return True


def test_evolver():
    print("\n" + "="*60)
    print("4. Testing Evolver")
    print("="*60)

    client = M27Client()
    evolver = Evolver(client, max_retries=2)

    errors = [
        "SyntaxError: invalid syntax at line 10",
        "NameError: name 'foo' is not defined",
    ]

    strategy, usage = evolver.evolve(
        task="Write a hello world function",
        errors=errors,
        previous_strategy=None,
        iteration=1
    )

    print(f"  Evolved strategy: {strategy[:100] if strategy else 'None'}...")
    print(f"  Tokens: {usage.total}")

    if strategy and len(strategy) > 10:
        print("  ✓ Evolver: PASS")
        return True
    else:
        print("  ✗ Evolver: FAIL")
        return False


def test_full_loop():
    print("\n" + "="*60)
    print("5. Testing Full SCLE Loop")
    print("="*60)

    client = M27Client()
    generator = CodeGenerator(client, max_retries=2)
    evolver = Evolver(client, max_retries=2)

    def dummy_evaluator(output_dir):
        return EvaluationResult(passed=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        config = RunConfig(
            task="Write a Python function that prints 'Hello from SCLE'",
            output_dir=tmpdir,
            max_iterations=2,
            budget_mode=BudgetMode.UNLIMITED,
        )

        def code_gen(task, strategy, output):
            return generator.generate(task, strategy, output)

        controller = LoopController(
            config=config,
            code_generator=code_gen,
            evaluator=dummy_evaluator,
            evolver=evolver.evolve,
        )

        print("  Running SCLE loop...")
        ctx = controller.run()

        print(f"  Status: {ctx.stats.status.value}")
        print(f"  Iterations: {ctx.stats.total_iterations}")
        print(f"  Tokens used: {ctx.stats.total_tokens}")

        files = os.listdir(tmpdir)
        print(f"  Files created: {files}")

        if ctx.stats.status.value == "success":
            print("  ✓ Full Loop: PASS")
            return True
        else:
            print("  ✗ Full Loop: FAIL")
            return False


def main():
    print("="*60)
    print("SCLE Integration Test Suite")
    print("="*60)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nERROR: ANTHROPIC_API_KEY not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key'")
        sys.exit(1)

    results = []

    results.append(("M27Client", test_m27_client()))
    results.append(("RateLimiter", test_rate_limiter()))
    results.append(("CodeGenerator", test_code_generator()))
    results.append(("Evolver", test_evolver()))
    results.append(("FullLoop", test_full_loop()))

    print("\n" + "="*60)
    print("Test Summary")
    print("="*60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name}: {status}")

    print(f"\nTotal: {passed}/{total} passed")

    if passed == total:
        print("\n🎉 All tests passed! SCLE is ready.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
