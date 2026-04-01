"""
Unit tests for StaticAnalyzer.
"""

import json
import tempfile
from pathlib import Path

import pytest

from tools.muscle.code_review.static_analyzer import (
    AUTO_FIXABLE_TOOLS,
    LANGUAGE_TOOLS,
    StaticAnalyzer,
)


@pytest.fixture
def temp_python_dir():
    """Create a temporary directory with Python files for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def clean_code_file(temp_python_dir):
    """Create a clean Python file with minimal issues."""
    code = '''"""Clean Python module."""


def hello():
    """Simple greeting function."""
    print("Hello, World!")


if __name__ == "__main__":
    hello()
'''
    path = temp_python_dir / "clean.py"
    path.write_text(code)
    return temp_python_dir


@pytest.fixture
def bad_code_file(temp_python_dir):
    """Create a Python file with multiple issues."""
    code = '''"""Module with issues."""


def unsafe_eval(user_input):
    result = eval(user_input)
    return result


password = "super_secret"


def long_line():
    x = 1; y = 2; z = 3; a = 4; b = 5; c = 6; d = 7; e = 8; f = 9; g = 10
'''
    path = temp_python_dir / "bad.py"
    path.write_text(code)
    return temp_python_dir


class TestLanguageDetection:
    """Test language detection functionality."""

    def test_detect_python_from_file(self, temp_python_dir):
        """Test language detection from file extension."""
        python_file = temp_python_dir / "test.py"
        python_file.write_text("print('hello')")

        analyzer = StaticAnalyzer(target_path=str(python_file))
        assert analyzer.language == "python"

    def test_detect_javascript_from_file(self, temp_python_dir):
        """Test JavaScript file detection."""
        js_file = temp_python_dir / "test.js"
        js_file.write_text("console.log('hello')")

        analyzer = StaticAnalyzer(target_path=str(js_file))
        assert analyzer.language == "javascript"

    def test_detect_typescript_from_file(self, temp_python_dir):
        """Test TypeScript file detection."""
        ts_file = temp_python_dir / "test.ts"
        ts_file.write_text("const x: number = 5;")

        analyzer = StaticAnalyzer(target_path=str(ts_file))
        assert analyzer.language == "typescript"

    def test_detect_go_from_file(self, temp_python_dir):
        """Test Go file detection."""
        go_file = temp_python_dir / "test.go"
        go_file.write_text("package main")

        analyzer = StaticAnalyzer(target_path=str(go_file))
        assert analyzer.language == "go"

    def test_detect_rust_from_file(self, temp_python_dir):
        """Test Rust file detection."""
        rust_file = temp_python_dir / "test.rs"
        rust_file.write_text("fn main() {}")

        analyzer = StaticAnalyzer(target_path=str(rust_file))
        assert analyzer.language == "rust"

    def test_detect_cpp_from_file(self, temp_python_dir):
        """Test C++ file detection."""
        cpp_file = temp_python_dir / "test.cpp"
        cpp_file.write_text("int main() { return 0; }")

        analyzer = StaticAnalyzer(target_path=str(cpp_file))
        assert analyzer.language == "cpp"

    def test_detect_java_from_file(self, temp_python_dir):
        """Test Java file detection."""
        java_file = temp_python_dir / "test.java"
        java_file.write_text("public class Test {}")

        analyzer = StaticAnalyzer(target_path=str(java_file))
        assert analyzer.language == "java"

    def test_detect_from_directory(self, temp_python_dir):
        """Test language detection from directory contents."""
        (temp_python_dir / "main.py").write_text("print('hello')")
        (temp_python_dir / "utils.py").write_text("def foo(): pass")

        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        assert analyzer.language == "python"

    def test_detect_no_files(self, temp_python_dir):
        """Test detection when directory has no code files."""
        (temp_python_dir / "README.txt").write_text("Just a text file")

        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        assert analyzer.language is None


class TestExcludePatterns:
    """Test file exclusion patterns."""

    def test_exclude_node_modules(self, temp_python_dir):
        """Test that node_modules is excluded."""
        node_modules = temp_python_dir / "node_modules"
        node_modules.mkdir()
        (node_modules / "package.json").write_text("{}")

        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        assert not analyzer._should_include(node_modules / "package.json")

    def test_exclude_pycache(self, temp_python_dir):
        """Test that __pycache__ is excluded."""
        pycache = temp_python_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "test.pyc").write_text("")

        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        assert not analyzer._should_include(pycache / "test.pyc")

    def test_exclude_git(self, temp_python_dir):
        """Test that .git is excluded."""
        git_dir = temp_python_dir / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("")

        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        assert not analyzer._should_include(git_dir / "config")

    def test_include_normal_files(self, temp_python_dir):
        """Test that normal Python files are included."""
        py_file = temp_python_dir / "main.py"
        py_file.write_text("print('hello')")

        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        assert analyzer._should_include(py_file)


class TestLanguageToolsMapping:
    """Test that language to tools mapping is correct."""

    def test_python_has_ruff(self):
        """Test Python has Ruff configured."""
        tools = LANGUAGE_TOOLS.get("python", [])
        tool_names = [t["name"] for t in tools]
        assert "ruff" in tool_names

    def test_javascript_has_eslint(self):
        """Test JavaScript has ESLint configured."""
        tools = LANGUAGE_TOOLS.get("javascript", [])
        tool_names = [t["name"] for t in tools]
        assert "eslint" in tool_names

    def test_typescript_has_eslint_and_tsc(self):
        """Test TypeScript has ESLint and TSC configured."""
        tools = LANGUAGE_TOOLS.get("typescript", [])
        tool_names = [t["name"] for t in tools]
        assert "eslint" in tool_names

    def test_go_has_golangci(self):
        """Test Go has golangci-lint configured."""
        tools = LANGUAGE_TOOLS.get("go", [])
        tool_names = [t["name"] for t in tools]
        assert "golangci-lint" in tool_names

    def test_rust_has_clippy(self):
        """Test Rust has Clippy configured."""
        tools = LANGUAGE_TOOLS.get("rust", [])
        tool_names = [t["name"] for t in tools]
        assert "clippy" in tool_names

    def test_cpp_has_cppcheck(self):
        """Test C++ has Cppcheck configured."""
        tools = LANGUAGE_TOOLS.get("cpp", [])
        tool_names = [t["name"] for t in tools]
        assert "cppcheck" in tool_names


class TestAutoFixableTools:
    """Test auto-fixable tools configuration."""

    def test_ruff_is_auto_fixable(self):
        """Test Ruff is in auto-fixable list."""
        assert "ruff" in AUTO_FIXABLE_TOOLS

    def test_eslint_is_auto_fixable(self):
        """Test ESLint is in auto-fixable list."""
        assert "eslint" in AUTO_FIXABLE_TOOLS

    def test_golangci_is_auto_fixable(self):
        """Test golangci-lint is in auto-fixable list."""
        assert "golangci-lint" in AUTO_FIXABLE_TOOLS

    def test_clippy_is_auto_fixable(self):
        """Test Clippy is in auto-fixable list."""
        assert "clippy" in AUTO_FIXABLE_TOOLS


class TestAnalyzerInitialization:
    """Test StaticAnalyzer initialization."""

    def test_custom_include_patterns(self, temp_python_dir):
        """Test custom include patterns."""
        analyzer = StaticAnalyzer(
            target_path=str(temp_python_dir),
            include_patterns=["*.py", "*.pyx"],
        )
        assert analyzer.include_patterns == ["*.py", "*.pyx"]

    def test_custom_exclude_patterns(self, temp_python_dir):
        """Test custom exclude patterns."""
        analyzer = StaticAnalyzer(
            target_path=str(temp_python_dir),
            exclude_patterns=["test_*.py", "*.test.py"],
        )
        assert analyzer.exclude_patterns == ["test_*.py", "*.test.py"]

    def test_explicit_language(self, temp_python_dir):
        """Test explicit language override."""
        analyzer = StaticAnalyzer(
            target_path=str(temp_python_dir),
            language="python",
        )
        assert analyzer.language == "python"

    def test_target_path_as_path_object(self, temp_python_dir):
        """Test that Path objects are handled correctly."""
        python_file = temp_python_dir / "test.py"
        python_file.write_text("print('hello')")

        analyzer = StaticAnalyzer(target_path=python_file)
        assert analyzer.target_path == python_file


class TestAnalyzerRun:
    """Test StaticAnalyzer.analyze() method."""

    def test_analyze_no_language_returns_empty(self, temp_python_dir):
        """Test that analyze returns empty list when no language detected."""
        analyzer = StaticAnalyzer(target_path=str(temp_python_dir))
        results = analyzer.analyze()
        assert results == []

    def test_analyze_with_clean_code(self, clean_code_file):
        """Test analyze on clean code returns minimal issues."""
        analyzer = StaticAnalyzer(target_path=str(clean_code_file))
        results = analyzer.analyze()
        # Clean code may have no issues or very few
        assert isinstance(results, list)

    def test_analyze_results_are_static_analysis_results(self, clean_code_file):
        """Test that analyze returns StaticAnalysisResult objects."""
        analyzer = StaticAnalyzer(target_path=str(clean_code_file))
        results = analyzer.analyze()

        for result in results:
            assert hasattr(result, "tool_name")
            assert hasattr(result, "language")
            assert hasattr(result, "issues")
            assert hasattr(result, "duration_seconds")

    def test_analyze_handles_missing_tools(self, temp_python_dir):
        """Test that analyze handles missing tools gracefully."""
        (temp_python_dir / "main.py").write_text("print('hello')")

        analyzer = StaticAnalyzer(
            target_path=str(temp_python_dir),
            language="nonexistent_language",
        )
        results = analyzer.analyze()
        assert results == []


class TestParserMethods:
    """Test individual parser methods."""

    @pytest.fixture
    def analyzer(self, temp_python_dir):
        return StaticAnalyzer(target_path=str(temp_python_dir))

    def test_parse_ruff_json_violations_format(self, analyzer):
        """Test ruff JSON parser with violations format."""
        output = json.dumps(
            [
                {
                    "filename": "test.py",
                    "violations": [
                        {
                            "code": "E501",
                            "message": "Line too long",
                            "location": {"row": 10, "column": 1},
                            "severity": "error",
                        }
                    ],
                }
            ]
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW"}
        issues = analyzer._parse_ruff_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].severity == "HIGH"
        assert issues[0].rule_id == "E501"
        assert issues[0].message == "Line too long"

    def test_parse_ruff_json_simple_format(self, analyzer):
        """Test ruff JSON parser with simple format (no violations key)."""
        output = json.dumps(
            [
                {
                    "filename": "test.py",
                    "code": "F401",
                    "message": "Unused import",
                    "location": {"row": 5, "column": 1},
                }
            ]
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW"}
        issues = analyzer._parse_ruff_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].rule_id == "F401"

    def test_parse_ruff_json_non_list(self, analyzer):
        """Test ruff JSON parser handles non-list JSON."""
        output = '{"not": "a list"}'
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW"}
        issues = analyzer._parse_ruff_json(output, severity_map)
        assert issues == []

    def test_parse_ruff_json_invalid_falls_back_to_text(self, analyzer):
        """Test ruff parser falls back to text parsing on invalid JSON."""
        output = "test.py:10:5: E501 Line too long"
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "info": "LOW"}
        issues = analyzer._parse_ruff_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.py"
        assert issues[0].line_number == 10

    def test_parse_pyright_json(self, analyzer):
        """Test pyright JSON parser."""
        output = json.dumps(
            {
                "generalDiagnostics": [
                    {
                        "file": "test.py",
                        "severity": "error",
                        "message": "Cannot assign to a literal",
                        "range": {
                            "start": {"line": 5, "character": 0},
                            "end": {"line": 5, "character": 10},
                        },
                        "rule": "类型的具体数值",
                    }
                ]
            }
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "information": "LOW"}
        issues = analyzer._parse_pyright_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.py"
        assert issues[0].line_number == 6
        assert issues[0].severity == "HIGH"
        assert issues[0].message == "Cannot assign to a literal"

    def test_parse_pyright_json_invalid(self, analyzer):
        """Test pyright parser handles invalid JSON."""
        output = "not json"
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "information": "LOW"}
        issues = analyzer._parse_pyright_json(output, severity_map)
        assert issues == []

    def test_parse_bandit_json(self, analyzer):
        """Test bandit JSON parser."""
        output = json.dumps(
            {
                "results": [
                    {
                        "filename": "test.py",
                        "line": 15,
                        "severity": "HIGH",
                        "issue_id": "B101",
                        "issue_text": "Use of eval detected",
                    }
                ]
            }
        )
        severity_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
        issues = analyzer._parse_bandit_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.py"
        assert issues[0].line_number == 15
        assert issues[0].severity == "HIGH"
        assert issues[0].message == "Use of eval detected"

    def test_parse_bandit_json_invalid(self, analyzer):
        """Test bandit parser handles invalid JSON."""
        output = "not json"
        severity_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
        issues = analyzer._parse_bandit_json(output, severity_map)
        assert issues == []

    def test_parse_eslint_json(self, analyzer):
        """Test ESLint JSON parser."""
        output = json.dumps(
            [
                {
                    "filePath": "test.js",
                    "messages": [
                        {
                            "line": 3,
                            "column": 5,
                            "severity": 2,
                            "message": "Unexpected constant condition",
                            "ruleId": "no-constant-condition",
                        }
                    ],
                }
            ]
        )
        severity_map = {"2": "HIGH", "1": "MEDIUM", "0": "LOW"}
        issues = analyzer._parse_eslint_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.js"
        assert issues[0].line_number == 3
        assert issues[0].severity == "HIGH"
        assert issues[0].rule_id == "no-constant-condition"

    def test_parse_eslint_json_invalid(self, analyzer):
        """Test ESLint parser handles invalid JSON."""
        output = "not json"
        severity_map = {"2": "HIGH", "1": "MEDIUM", "0": "LOW"}
        issues = analyzer._parse_eslint_json(output, severity_map)
        assert issues == []

    def test_parse_tsc_text(self, analyzer):
        """Test TypeScript compiler text output parser."""
        output = """test.ts(5,10): error TS2322: Type 'string' is not assignable to type 'number'.
test.ts(10,5): warning TS6032: File change detected. Starting fresh analysis."""
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_tsc_text(output, severity_map)
        assert len(issues) == 2
        assert issues[0].file_path == "test.ts"
        assert issues[0].line_number == 5
        assert issues[0].severity == "HIGH"
        assert "Type 'string'" in issues[0].message

    def test_parse_tsc_text_no_match(self, analyzer):
        """Test TSC text parser handles non-matching lines."""
        output = "Some random output that doesn't match the pattern"
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_tsc_text(output, severity_map)
        assert issues == []

    def test_parse_golangci_json(self, analyzer):
        """Test golangci-lint JSON parser."""
        output = json.dumps(
            {
                "Issues": [
                    {
                        "FromLinter": "golint",
                        "File": "test.go",
                        "Line": 10,
                        "Severity": "error",
                        "Text": " exported function TestFunc should have comment",
                        "Linter": "golint",
                    }
                ]
            }
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_golangci_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "golint"
        assert issues[0].line_number == 10
        assert issues[0].severity == "HIGH"
        assert "golint" in issues[0].message

    def test_parse_golangci_json_invalid(self, analyzer):
        """Test golangci-lint parser handles invalid JSON."""
        output = "not json"
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_golangci_json(output, severity_map)
        assert issues == []

    def test_parse_clippy_json(self, analyzer):
        """Test clippy JSON parser (newline-delimited JSON with compiler-message)."""
        output = json.dumps(
            {
                "reason": "compiler-message",
                "message": {
                    "message": "this expression creates a default in a way that is confusing",
                    "level": "warning",
                    "code": {"code": "unknown-macro"},
                    "spans": [
                        {
                            "file_name": "test.rs",
                            "line_start": 5,
                            "line_end": 5,
                        }
                    ],
                },
            }
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_clippy_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.rs"
        assert issues[0].line_number == 5
        assert issues[0].severity == "MEDIUM"

    def test_parse_clippy_json_invalid(self, analyzer):
        """Test clippy parser handles invalid JSON."""
        output = "not json"
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_clippy_json(output, severity_map)
        assert issues == []

    def test_parse_cppcheck_json(self, analyzer):
        """Test cppcheck JSON parser."""
        output = json.dumps(
            {
                "results": [
                    {
                        "file": "test.cpp",
                        "line": 15,
                        "severity": "error",
                        "msg": "Memory leak",
                        "id": "memleak",
                        "type": "error",
                    }
                ]
            }
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "style": "LOW"}
        issues = analyzer._parse_cppcheck_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.cpp"
        assert issues[0].line_number == 15
        assert issues[0].severity == "HIGH"
        assert issues[0].message == "Memory leak"

    def test_parse_cppcheck_json_invalid(self, analyzer):
        """Test cppcheck parser handles invalid JSON."""
        output = "not json"
        severity_map = {"error": "HIGH", "warning": "MEDIUM", "style": "LOW"}
        issues = analyzer._parse_cppcheck_json(output, severity_map)
        assert issues == []

    def test_parse_checkstyle_text(self, analyzer):
        """Test checkstyle text parser."""
        output = """[ERROR] test.java:10: '}' is not preceded with a whitespace. [WHITESPACE] [RedundantThrows]
[WARNING] test.java:15:5: Line is longer than 100 characters [FileTabCharacter]"""
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_checkstyle_text(output, severity_map)
        assert len(issues) == 2
        assert issues[0].file_path == "test.java"
        assert issues[0].line_number == 10

    def test_parse_checkstyle_text_no_match(self, analyzer):
        """Test checkstyle parser handles non-matching lines."""
        output = "Some random output"
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_checkstyle_text(output, severity_map)
        assert issues == []

    def test_parse_svelte_check_json(self, analyzer):
        """Test svelte-check JSON parser."""
        output = json.dumps(
            [
                {
                    "file": "test.svelte",
                    "line": 5,
                    "severity": "error",
                    "message": "Props should be passed explicitly",
                    "code": "a11y-no-static-element-interaction",
                    "source": "svelte",
                }
            ]
        )
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_svelte_check_json(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.svelte"
        assert issues[0].line_number == 5
        assert issues[0].severity == "HIGH"

    def test_parse_svelte_check_json_invalid(self, analyzer):
        """Test svelte-check parser handles invalid JSON."""
        output = "not json"
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_svelte_check_json(output, severity_map)
        assert issues == []

    def test_parse_generic(self, analyzer):
        """Test generic parser (line-based with file:line:message format)."""
        output = "test.py:10: Some warning message"
        severity_map = {"error": "HIGH", "warning": "MEDIUM"}
        issues = analyzer._parse_generic(output, severity_map)
        assert len(issues) == 1
        assert issues[0].file_path == "test.py"
        assert issues[0].line_number == 10
        assert issues[0].message == "Some warning message"


class TestAutoFix:
    """Test auto_fix method."""

    def test_auto_fix_no_language(self, temp_python_dir):
        """Test auto_fix returns empty when no language."""
        analyzer = StaticAnalyzer(target_path=str(temp_python_dir), language=None)
        assert analyzer.auto_fix() == []

    def test_auto_fix_no_fixable_tools(self, temp_python_dir):
        """Test auto_fix returns empty for language with no fixable tools."""
        (temp_python_dir / "main.java").write_text("public class Main {}")
        analyzer = StaticAnalyzer(target_path=str(temp_python_dir), language="java")
        result = analyzer.auto_fix()
        assert isinstance(result, list)
