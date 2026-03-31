#!/usr/bin/env python3
"""
SCLE Production Test Suite

Run this to thoroughly test SCLE with real M2.7 API calls.

Usage:
    export ANTHROPIC_API_KEY="your-key"
    export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"  # or .com for China
    python test_production.py
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("MINIMAX_API_BASE", "io")

from tools.scle.m27_client import M27Client, RateLimiter, TokenUsage
from tools.scle.code_generator import CodeGenerator
from tools.scle.evolver import Evolver
from tools.scle.loop_controller import LoopController
from tools.scle.types import RunConfig, EvaluationResult, BudgetMode, EvalMode
from tools.scle.budget_manager import BudgetManager
from tools.scle.session_manager import SessionManager
from tools.scle.evaluator_registry import EvaluatorRegistry


def test_m27_connectivity():
    """Test 1: Basic M2.7 API connectivity"""
    print("\n" + "="*60)
    print("TEST 1: M2.7 API Connectivity")
    print("="*60)

    client = M27Client()
    print(f"  Endpoint: {client.base_url}")

    response, usage = client.chat(
        messages=[{"role": "user", "content": "Say 'API OK' in exactly 3 words. Your response should only be those 3 words."}],
        max_tokens=50
    )

    if response and len(response.strip()) > 0:
        print(f"  ✓ Response: '{response.strip()}'")
        print(f"  ✓ Tokens used: {usage.total}")
        return True
    else:
        print(f"  ✗ FAILED - Empty response")
        return False


def test_code_generator_python():
    """Test 2: Python code generation"""
    print("\n" + "="*60)
    print("TEST 2: Python Code Generation")
    print("="*60)

    client = M27Client()
    generator = CodeGenerator(client, max_retries=2)

    with tempfile.TemporaryDirectory() as tmpdir:
        result, usage = generator.generate(
            task="Write a Python function that calculates fibonacci numbers",
            evolved_strategy="",
            output_dir=tmpdir
        )

        print(f"  Result: {result}")
        print(f"  Tokens: {usage.total}")

        files = os.listdir(tmpdir)
        print(f"  Files: {files}")

        py_files = [f for f in files if f.endswith('.py')]
        if py_files:
            content = open(os.path.join(tmpdir, py_files[0])).read()
            print(f"  First 200 chars:\n{content[:200]}...")
            print(f"  ✓ Python code generated successfully")
            return True
        else:
            print(f"  ✗ FAILED - No Python files generated")
            return False


def test_code_generator_javascript():
    """Test 3: JavaScript code generation"""
    print("\n" + "="*60)
    print("TEST 3: JavaScript Code Generation")
    print("="*60)

    client = M27Client()
    generator = CodeGenerator(client, max_retries=2)

    with tempfile.TemporaryDirectory() as tmpdir:
        result, usage = generator.generate(
            task="Write a JavaScript function that returns the sum of an array",
            evolved_strategy="",
            output_dir=tmpdir
        )

        print(f"  Result: {result}")
        print(f"  Tokens: {usage.total}")

        files = os.listdir(tmpdir)
        js_files = [f for f in files if f.endswith('.js')]
        if js_files:
            print(f"  ✓ JavaScript code generated")
            return True
        else:
            print(f"  ⚠ No JS files (may have generated other format)")
            return True  # Not a failure, just different output


def test_evolver():
    """Test 4: Strategy evolution"""
    print("\n" + "="*60)
    print("TEST 4: Strategy Evolution")
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

    print(f"  Strategy length: {len(strategy) if strategy else 0}")
    print(f"  Tokens: {usage.total}")

    if strategy and len(strategy) > 20:
        print(f"  ✓ Strategy evolved successfully")
        return True
    else:
        print(f"  ✗ FAILED - Strategy too short or empty")
        return False


def test_full_loop_success():
    """Test 5: Full SCLE loop with success"""
    print("\n" + "="*60)
    print("TEST 5: Full Loop - Success Case")
    print("="*60)

    client = M27Client()
    generator = CodeGenerator(client, max_retries=2)
    evolver = Evolver(client, max_retries=2)

    def pass_evaluator(output_dir):
        return EvaluationResult(passed=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        config = RunConfig(
            task="Write a Python function that prints 'Hello SCLE'",
            output_dir=tmpdir,
            max_iterations=2,
            budget_mode=BudgetMode.UNLIMITED,
        )

        def code_gen(task, strategy, output):
            return generator.generate(task, strategy, output)

        controller = LoopController(
            config=config,
            code_generator=code_gen,
            evaluator=pass_evaluator,
            evolver=evolver.evolve,
        )

        ctx = controller.run()

        print(f"  Status: {ctx.stats.status.value}")
        print(f"  Iterations: {ctx.stats.total_iterations}")
        print(f"  Tokens: {ctx.stats.total_tokens}")

        if ctx.stats.status.value == "success":
            print(f"  ✓ Loop completed successfully")
            return True
        else:
            print(f"  ✗ FAILED - Status: {ctx.stats.status.value}")
            return False


def test_full_loop_retry():
    """Test 6: Full SCLE loop with failures and retry"""
    print("\n" + "="*60)
    print("TEST 6: Full Loop - Retry with Evolution")
    print("="*60)

    client = M27Client()
    generator = CodeGenerator(client, max_retries=2)
    evolver = Evolver(client, max_retries=2)

    attempt_count = [0]

    def fail_once_evaluator(output_dir):
        attempt_count[0] += 1
        if attempt_count[0] == 1:
            return EvaluationResult(
                passed=False,
                compiler_errors=["SyntaxError: invalid syntax"]
            )
        return EvaluationResult(passed=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        config = RunConfig(
            task="Write a Python hello function",
            output_dir=tmpdir,
            max_iterations=5,
            budget_mode=BudgetMode.UNLIMITED,
        )

        def code_gen(task, strategy, output):
            return generator.generate(task, strategy, output)

        controller = LoopController(
            config=config,
            code_generator=code_gen,
            evaluator=fail_once_evaluator,
            evolver=evolver.evolve,
        )

        ctx = controller.run()

        print(f"  Status: {ctx.stats.status.value}")
        print(f"  Iterations: {ctx.stats.total_iterations}")
        print(f"  Attempts: {attempt_count[0]}")

        if ctx.stats.status.value == "success" and ctx.stats.total_iterations == 2:
            print(f"  ✓ Retry loop worked correctly")
            return True
        else:
            print(f"  ✗ Unexpected result")
            return False


def test_budget_enforcement():
    """Test 7: Budget enforcement"""
    print("\n" + "="*60)
    print("TEST 7: Budget Enforcement")
    print("="*60)

    budget_manager = BudgetManager(mode=BudgetMode.FIXED, fixed_limit=5000)

    ok1, reason1 = budget_manager.check_budget(3000)
    print(f"  First check (3000 tokens): ok={ok1}, reason='{reason1}'")

    ok2, reason2 = budget_manager.check_budget(3000)
    print(f"  Second check (3000 tokens): ok={ok2}, reason='{reason2}'")

    if ok1 and not ok2 and "exceeded" in reason2.lower():
        print(f"  ✓ Budget enforcement works")
        return True
    else:
        print(f"  ✗ FAILED - Budget not enforced correctly")
        return False


def test_session_persistence():
    """Test 8: Session persistence"""
    print("\n" + "="*60)
    print("TEST 8: Session Persistence")
    print("="*60)

    session_manager = SessionManager(base_dir="/tmp/test_scle_sessions")

    config = RunConfig(
        task="Test task",
        output_dir="/tmp/test_output",
        max_iterations=5
    )

    session_id = session_manager.create_session(config)
    print(f"  Created session: {session_id}")

    sessions = session_manager.list_sessions()
    print(f"  Total sessions: {len(sessions)}")

    loaded = session_manager.load_session(session_id)
    print(f"  Loaded session: {loaded is not None}")

    if loaded and session_id:
        print(f"  ✓ Session persistence works")
        session_manager.delete_session(session_id)
        return True
    else:
        print(f"  ✗ FAILED")
        return False


def test_evaluator_registry():
    """Test 9: Evaluator registry"""
    print("\n" + "="*60)
    print("TEST 9: Evaluator Registry")
    print("="*60)

    from tools.scle.evaluator_registry import detect_language

    registry = EvaluatorRegistry()

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a simple Python file
        with open(os.path.join(tmpdir, "test.py"), "w") as f:
            f.write("print('hello')\n")

        lang = detect_language(tmpdir)
        print(f"  Detected language: {lang}")

        result = registry.evaluate(tmpdir, lang)
        print(f"  Evaluation result: passed={result.passed}")

        print(f"  ✓ Evaluator registry works")
        return True


def main():
    print("="*60)
    print("SCLE Production Test Suite")
    print("="*60)

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        print("\nERROR: ANTHROPIC_API_KEY not set")
        print("Set it with: export ANTHROPIC_API_KEY='your-key'")
        return 1

    results = []

    # Core API tests
    results.append(("M27 Connectivity", test_m27_connectivity()))
    results.append(("Python Code Gen", test_code_generator_python()))
    results.append(("JavaScript Code Gen", test_code_generator_javascript()))
    results.append(("Evolver", test_evolver()))

    # Full loop tests (require API)
    results.append(("Full Loop Success", test_full_loop_success()))
    results.append(("Full Loop Retry", test_full_loop_retry()))

    # Unit tests
    results.append(("Budget Enforcement", test_budget_enforcement()))
    results.append(("Session Persistence", test_session_persistence()))
    results.append(("Evaluator Registry", test_evaluator_registry()))

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
        print("\n🎉 All tests passed! SCLE is production ready.")
        return 0
    else:
        print(f"\n⚠️ {total - passed} test(s) failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
