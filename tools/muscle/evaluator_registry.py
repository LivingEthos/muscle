"""
Evaluator Registry - Routes language detection to appropriate evaluators.

Architecture Decision Record (ADR):
- Auto-detects language from file extensions
- Maps language to list of evaluators (compiler, test, lint, assertions)
- Supports custom assertion runners per project
- Lazy imports to avoid circular dependencies
- Parallel evaluation using ThreadPoolExecutor for concurrent execution
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .evaluators.base import BaseEvaluator, EvaluatorResult
from .types import EvalMode, EvaluationResult

logger = logging.getLogger(__name__)


LANGUAGE_EVALUATORS = {
    ".py": ["python_compiler", "pytest_runner", "ruff_linter"],
    ".js": ["node_compiler", "jest_runner", "eslint_linter"],
    ".ts": ["tsc_compiler", "jest_runner", "eslint_linter"],
    ".go": ["go_compiler", "go_test_runner", "golangci_linter"],
    ".java": ["javac_compiler", "junit_runner", "checkstyle_linter"],
    ".rs": ["rust_compiler", "cargo_test_runner", "clippy_linter"],
    ".cpp": ["gpp_compiler", "gtest_runner", "cppcheck_linter"],
    ".c": ["gcc_compiler", "gtest_runner", "cppcheck_linter"],
    ".cs": ["csc_compiler", "nunit_runner", "dotnet_linter"],
}


def detect_language(output_dir: str) -> str | None:
    path = Path(output_dir)

    if not path.exists():
        path = Path.cwd()

    for ext in LANGUAGE_EVALUATORS.keys():
        files = list(path.rglob(f"*{ext}"))
        if files:
            logger.info(f"Detected {ext} language from {len(files)} files")
            return ext

    logger.warning("Could not auto-detect language")
    return None


LANGUAGE_ALIASES: dict[str, str] = {
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "go": ".go",
    "rust": ".rs",
    "java": ".java",
    "cpp": ".cpp",
    "c": ".c",
    "csharp": ".cs",
    "py": ".py",
    "js": ".js",
    "ts": ".ts",
    "rs": ".rs",
    "cs": ".cs",
}


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._evaluators: dict[str, BaseEvaluator] = {}

    def get_evaluators(self, language: str | None) -> list[BaseEvaluator]:
        if not language:
            evaluator_names = []
        elif language.startswith("."):
            evaluator_names = LANGUAGE_EVALUATORS.get(language, [])
        else:
            normalized = LANGUAGE_ALIASES.get(language.lower())
            evaluator_names = LANGUAGE_EVALUATORS.get(normalized, []) if normalized else []

        evaluators = []
        for name in evaluator_names:
            eval_instance = self._load_evaluator(name)
            if eval_instance:
                evaluators.append(eval_instance)

        if not evaluators:
            logger.warning(f"No evaluators found for language: {language}")
            evaluators.append(self._dummy_evaluator())

        return evaluators

    def _load_evaluator(self, name: str) -> BaseEvaluator | None:
        if name in self._evaluators:
            return self._evaluators[name]

        try:
            if name == "python_compiler":
                from .evaluators.compiler import PythonCompiler

                self._evaluators[name] = PythonCompiler()
            elif name == "pytest_runner":
                from .evaluators.tester import PytestRunner

                self._evaluators[name] = PytestRunner()
            elif name == "black_linter":
                from .evaluators.linter import BlackLinter

                self._evaluators[name] = BlackLinter()
            elif name == "ruff_linter":
                from .evaluators.linter import RuffLinter

                self._evaluators[name] = RuffLinter()
            elif name == "node_compiler":
                from .evaluators.compiler import NodeCompiler

                self._evaluators[name] = NodeCompiler()
            elif name == "jest_runner":
                from .evaluators.tester import JestRunner

                self._evaluators[name] = JestRunner()
            elif name == "eslint_linter":
                from .evaluators.linter import EslintLinter

                self._evaluators[name] = EslintLinter()
            elif name == "tsc_compiler":
                from .evaluators.compiler import TscCompiler

                self._evaluators[name] = TscCompiler()
            elif name == "go_compiler":
                from .evaluators.compiler import GoCompiler

                self._evaluators[name] = GoCompiler()
            elif name == "go_test_runner":
                from .evaluators.tester import GoTestRunner

                self._evaluators[name] = GoTestRunner()
            elif name == "golangci_linter":
                from .evaluators.linter import GolangciLinter

                self._evaluators[name] = GolangciLinter()
            elif name == "rust_compiler":
                from .evaluators.compiler import RustCompiler

                self._evaluators[name] = RustCompiler()
            elif name == "cargo_test_runner":
                from .evaluators.tester import CargoTestRunner

                self._evaluators[name] = CargoTestRunner()
            elif name == "clippy_linter":
                from .evaluators.linter import ClippyLinter

                self._evaluators[name] = ClippyLinter()
            elif name == "gpp_compiler":
                from .evaluators.compiler import GppCompiler

                self._evaluators[name] = GppCompiler()
            elif name == "gtest_runner":
                from .evaluators.tester import GtestRunner

                self._evaluators[name] = GtestRunner()
            elif name == "cppcheck_linter":
                from .evaluators.linter import CppcheckLinter

                self._evaluators[name] = CppcheckLinter()
            else:
                logger.warning(f"Unknown evaluator: {name}")
                return None

            return self._evaluators[name]

        except ImportError as e:
            logger.warning(f"Could not load evaluator {name}: {e}")
            return None

    def _dummy_evaluator(self) -> BaseEvaluator:
        from .evaluators.assertions import DummyEvaluator

        return DummyEvaluator()

    def evaluate(
        self,
        output_dir: str,
        language: str | None = None,
        eval_mode: EvalMode = EvalMode.ALL,
    ) -> EvaluationResult:
        if not language:
            language = detect_language(output_dir)

        evaluators = self.get_evaluators(language)

        if eval_mode == EvalMode.PARALLEL:
            return self._evaluate_parallel(output_dir, evaluators)

        return self._evaluate_sequential(output_dir, evaluators)

    def _evaluate_sequential(
        self, output_dir: str, evaluators: list[BaseEvaluator]
    ) -> EvaluationResult:
        all_compiler_errors: list[str] = []
        all_test_failures: list[str] = []
        all_linter_warnings: list[str] = []
        all_assertion_failures: list[str] = []

        for evaluator in evaluators:
            result = evaluator.evaluate(output_dir)

            error_type = evaluator.error_type
            errors = getattr(result, "errors", []) if hasattr(result, "errors") else []

            if error_type == "compiler":
                all_compiler_errors.extend(errors)
            elif error_type == "test":
                all_test_failures.extend(errors)
            elif error_type == "linter":
                all_linter_warnings.extend(errors)
            elif error_type == "assertion":
                all_assertion_failures.extend(errors)
            else:
                all_compiler_errors.extend(errors)

        passed = not any(
            [
                all_compiler_errors,
                all_test_failures,
                all_linter_warnings,
                all_assertion_failures,
            ]
        )

        return EvaluationResult(
            passed=passed,
            compiler_errors=all_compiler_errors,
            test_failures=all_test_failures,
            linter_warnings=all_linter_warnings,
            assertion_failures=all_assertion_failures,
        )

    def _evaluate_parallel(
        self, output_dir: str, evaluators: list[BaseEvaluator]
    ) -> EvaluationResult:
        start_time = time.time()
        max_workers = min(4, len(evaluators))
        timeout_seconds = 30

        evaluator_names = [e.name for e in evaluators]
        logger.info(f"Running {len(evaluators)} evaluators in parallel: {evaluator_names}")

        all_compiler_errors: list[str] = []
        all_test_failures: list[str] = []
        all_linter_warnings: list[str] = []
        all_assertion_failures: list[str] = []

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_evaluator = {
                    executor.submit(self._run_evaluator, evaluator, output_dir): evaluator
                    for evaluator in evaluators
                }

                for future in as_completed(
                    future_to_evaluator, timeout=timeout_seconds * len(evaluators)
                ):
                    evaluator = future_to_evaluator[future]
                    evaluator_name = evaluator.name
                    try:
                        result = future.result(timeout=timeout_seconds)
                        logger.info(f"Evaluator '{evaluator_name}' completed")

                        if isinstance(result, Exception):
                            logger.error(f"Evaluator '{evaluator_name}' failed: {result}")
                            all_compiler_errors.append(str(result))
                            continue

                        error_type = evaluator.error_type
                        errors = getattr(result, "errors", []) if hasattr(result, "errors") else []

                        if error_type == "compiler":
                            all_compiler_errors.extend(errors)
                        elif error_type == "test":
                            all_test_failures.extend(errors)
                        elif error_type == "linter":
                            all_linter_warnings.extend(errors)
                        elif error_type == "assertion":
                            all_assertion_failures.extend(errors)
                        else:
                            all_compiler_errors.extend(errors)
                    except TimeoutError:
                        logger.error(
                            f"Evaluator '{evaluator_name}' timed out after {timeout_seconds}s"
                        )
                    except Exception as e:
                        logger.error(f"Evaluator '{evaluator_name}' failed: {e}")
        except Exception as e:
            logger.warning(f"Parallel evaluation failed, falling back to sequential: {e}")
            return self._evaluate_sequential(output_dir, evaluators)

        duration = time.time() - start_time
        logger.info(f"Parallel evaluation completed in {duration:.2f}s")

        passed = not any(
            [
                all_compiler_errors,
                all_test_failures,
                all_linter_warnings,
                all_assertion_failures,
            ]
        )

        return EvaluationResult(
            passed=passed,
            compiler_errors=all_compiler_errors,
            test_failures=all_test_failures,
            linter_warnings=all_linter_warnings,
            assertion_failures=all_assertion_failures,
        )

    def _run_evaluator(
        self, evaluator: BaseEvaluator, output_dir: str
    ) -> EvaluatorResult | Exception:
        try:
            return evaluator.evaluate(output_dir)
        except Exception as e:
            return e
