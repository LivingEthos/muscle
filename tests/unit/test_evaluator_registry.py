"""
Unit tests for evaluator_registry.py
"""

from unittest.mock import Mock, patch

from tools.muscle.evaluator_registry import LANGUAGE_ALIASES, EvaluatorRegistry, detect_language
from tools.muscle.types import EvalMode


class TestDetectLanguage:
    def test_detect_python(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        lang = detect_language(str(tmp_path))
        assert lang == ".py"

    def test_detect_javascript(self, tmp_path):
        (tmp_path / "index.js").write_text("console.log('hello')")
        lang = detect_language(str(tmp_path))
        assert lang == ".js"

    def test_detect_typescript(self, tmp_path):
        (tmp_path / "app.ts").write_text("const x: number = 1;")
        lang = detect_language(str(tmp_path))
        assert lang == ".ts"

    def test_detect_go(self, tmp_path):
        (tmp_path / "main.go").write_text("package main")
        lang = detect_language(str(tmp_path))
        assert lang == ".go"

    def test_detect_unknown(self, tmp_path):
        (tmp_path / "README.txt").write_text("Just a readme")
        lang = detect_language(str(tmp_path))
        assert lang is None


class TestLanguageAliases:
    def test_alias_py(self):
        assert LANGUAGE_ALIASES.get("py") == ".py"

    def test_alias_python(self):
        assert LANGUAGE_ALIASES.get("python") == ".py"

    def test_alias_js(self):
        assert LANGUAGE_ALIASES.get("js") == ".js"

    def test_alias_javascript(self):
        assert LANGUAGE_ALIASES.get("javascript") == ".js"

    def test_get_evaluators_with_short_alias(self):
        registry = EvaluatorRegistry()
        evaluators = registry.get_evaluators("py")
        names = [e.name for e in evaluators]
        assert any("python" in n or "pytest" in n or "ruff" in n for n in names)

    def test_get_evaluators_with_long_alias(self):
        registry = EvaluatorRegistry()
        evaluators = registry.get_evaluators("python")
        names = [e.name for e in evaluators]
        assert any("python" in n or "pytest" in n or "ruff" in n for n in names)

    def test_get_evaluators_with_dot_prefix(self):
        registry = EvaluatorRegistry()
        evaluators = registry.get_evaluators(".py")
        names = [e.name for e in evaluators]
        assert any("python" in n or "pytest" in n or "ruff" in n for n in names)


class TestEvaluatorRegistry:
    def test_get_evaluators_python(self):
        registry = EvaluatorRegistry()
        evaluators = registry.get_evaluators(".py")
        assert len(evaluators) > 0
        names = [e.name for e in evaluators]
        assert any("python" in n or "pytest" in n or "ruff" in n or "black" in n for n in names)

    def test_get_evaluators_unknown(self):
        registry = EvaluatorRegistry()
        evaluators = registry.get_evaluators("nonexistent-lang-xyz")
        names = [e.name for e in evaluators]
        assert any("dummy" in n.lower() for n in names)

    def test_evaluate_sequential(self):
        registry = EvaluatorRegistry()
        mock_eval = Mock()
        mock_eval.evaluate.return_value = Mock(
            passed=True,
            errors=[],
        )
        mock_eval.error_type = "compiler"
        mock_eval.name = "mock"
        with patch.object(registry, "get_evaluators", return_value=[mock_eval]):
            result = registry.evaluate("/fake", language=".py", eval_mode=EvalMode.SEQUENTIAL)
        assert result.passed is True

    def test_evaluate_parallel(self):
        registry = EvaluatorRegistry()
        mock_eval = Mock()
        mock_eval.evaluate.return_value = Mock(
            passed=True,
            errors=[],
        )
        mock_eval.error_type = "compiler"
        mock_eval.name = "mock"
        with patch.object(registry, "get_evaluators", return_value=[mock_eval]):
            result = registry.evaluate("/fake", language=".py", eval_mode=EvalMode.PARALLEL)
        assert result.passed is True

    def test_evaluate_collects_errors(self):
        registry = EvaluatorRegistry()
        mock_eval = Mock()
        mock_eval.evaluate.return_value = Mock(
            passed=False,
            errors=["SyntaxError"],
        )
        mock_eval.error_type = "compiler"
        mock_eval.name = "mock"
        with patch.object(registry, "get_evaluators", return_value=[mock_eval]):
            result = registry.evaluate("/fake", eval_mode=EvalMode.SEQUENTIAL)
        assert result.passed is False
        assert len(result.compiler_errors) == 1
