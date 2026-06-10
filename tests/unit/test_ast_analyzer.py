"""
Unit tests for AST analyzer.
"""

import tempfile
from pathlib import Path

from muscle.analysis.ast_analyzer import ASTAnalyzer, ASTFinding, ASTSecurityAnalyzer
from muscle.analysis.types import Severity


class TestASTSecurityAnalyzer:
    """Tests for the low-level ASTSecurityAnalyzer."""

    def test_detect_eval(self):
        """AST-001: eval() usage is detected."""
        source = "result = eval(user_input)\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-001" for f in findings)

    def test_detect_exec(self):
        """AST-002: exec() usage is detected."""
        source = "exec(code)\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-002" for f in findings)

    def test_detect_compile(self):
        """AST-003: compile() usage is detected."""
        source = "compile('x', '<string>', 'exec')\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-003" for f in findings)

    def test_detect_import(self):
        """AST-004: __import__() usage is detected."""
        source = "mod = __import__('os')\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-004" for f in findings)

    def test_detect_pickle_loads(self):
        """AST-005: pickle.loads() usage is detected."""
        source = "import pickle\ndata = pickle.loads(raw)\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-005" for f in findings)

    def test_detect_yaml_load(self):
        """AST-006: yaml.load() usage is detected."""
        source = "import yaml\ndata = yaml.load(stream)\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-006" for f in findings)

    def test_detect_os_system(self):
        """AST-007: os.system() usage is detected."""
        source = "import os\nos.system('ls')\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-007" for f in findings)

    def test_detect_os_popen(self):
        """AST-008: os.popen() usage is detected."""
        source = "import os\nos.popen('ls')\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-008" for f in findings)

    def test_detect_subprocess_shell_true(self):
        """AST-009: subprocess with shell=True is detected."""
        source = "import subprocess\nsubprocess.run('ls', shell=True)\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-009" for f in findings)

    def test_detect_sql_injection_fstring(self):
        """AST-010: SQL injection via f-string is detected."""
        source = (
            "import sqlite3\n"
            "conn = sqlite3.connect(':memory:')\n"
            "cur = conn.cursor()\n"
            "cur.execute(f'SELECT * FROM users WHERE id = {uid}')\n"
        )
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-010" for f in findings)

    def test_detect_hardcoded_secret(self):
        """AST-012: hardcoded secret in assignment is detected."""
        source = "password = 'super_secret'\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-012" for f in findings)

    def test_detect_os_getenv_default_secret(self):
        """AST-011: os.getenv with hardcoded default is detected."""
        source = "import os\npassword = os.getenv('PASSWORD', 'default_secret')\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert any(f.rule_id == "AST-011" for f in findings)

    def test_syntax_error_handling(self):
        """Syntax errors are handled gracefully."""
        source = "def foo(\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        assert findings == []


class TestASTAnalyzer:
    """Tests for the high-level ASTAnalyzer service."""

    def test_analyze_file_not_found(self):
        """Missing files return empty findings."""
        service = ASTAnalyzer()
        findings = service.analyze_file("/nonexistent/path.py")
        assert findings == []

    def test_analyze_directory(self):
        """Directory scan returns findings from all files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "a.py").write_text("eval('1')\n")
            (path / "b.py").write_text("exec('pass')\n")
            service = ASTAnalyzer()
            findings = service.analyze_directory(tmpdir)
            rule_ids = {f.rule_id for f in findings}
            assert "AST-001" in rule_ids
            assert "AST-002" in rule_ids

    def test_finding_sort_order(self):
        """Findings are sorted by line then column."""
        source = "eval('1')\nexec('2')\n"
        analyzer = ASTSecurityAnalyzer()
        findings = analyzer.analyze("test.py", source)
        lines = [f.line for f in findings]
        assert lines == sorted(lines)

    def test_to_static_issue_dict(self):
        """ASTFinding emits v1-compatible StaticIssue shape."""
        finding = ASTFinding(
            rule_id="AST-001",
            message="eval used",
            severity=Severity.CRITICAL,
            line=1,
            column=0,
            category="security",
            file_path="test.py",
        )
        d = finding.to_static_issue_dict()
        assert d["file_path"] == "test.py"
        assert d["line_number"] == 1
        assert d["severity"] == "CRITICAL"
        assert d["rule_id"] == "AST-001"
