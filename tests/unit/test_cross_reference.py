"""
Unit tests for cross-reference analyzer.
"""

import tempfile
from pathlib import Path

from tools.muscle.analysis.cross_reference import (
    CrossReferenceAnalyzer,
    CrossReferenceFinding,
    ImportGraph,
)
from tools.muscle.analysis.types import Severity


class TestImportGraph:
    """Tests for the ImportGraph data structure."""

    def test_add_node_and_edge(self):
        """Nodes and edges are stored correctly."""
        graph = ImportGraph()
        graph.add_edge("a", "b")
        assert "a" in graph._nodes
        assert "b" in graph._nodes
        assert graph.neighbors("a") == ["b"]

    def test_find_simple_cycle(self):
        """A simple cycle a -> b -> a is detected."""
        graph = ImportGraph()
        graph.add_edge("a", "b")
        graph.add_edge("b", "a")
        cycles = graph.find_cycles()
        assert len(cycles) == 1
        assert set(cycles[0]) == {"a", "b"}

    def test_no_cycle(self):
        """Acyclic graph returns no cycles."""
        graph = ImportGraph()
        graph.add_edge("a", "b")
        graph.add_edge("b", "c")
        assert graph.find_cycles() == []

    def test_self_loop(self):
        """Self-import is detected as a cycle."""
        graph = ImportGraph()
        graph.add_edge("a", "a")
        cycles = graph.find_cycles()
        assert len(cycles) == 1


class TestCrossReferenceAnalyzer:
    """Tests for the CrossReferenceAnalyzer."""

    def test_unused_export(self):
        """XREF-001: unused public function is reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "mod.py").write_text("def public_func(): pass\n")
            analyzer = CrossReferenceAnalyzer()
            analyzer.build_graph(tmpdir)
            findings = analyzer.find_unused_exports()
            assert any(f.rule_id == "XREF-001" for f in findings)

    def test_circular_import(self):
        """XREF-002: circular import is detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "a.py").write_text("import b\n")
            (path / "b.py").write_text("import a\n")
            analyzer = CrossReferenceAnalyzer()
            findings = analyzer.analyze(tmpdir)
            assert any(f.rule_id == "XREF-002" for f in findings)

    def test_missing_dependency(self):
        """XREF-003: missing local dependency is reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "main.py").write_text("import unknown_module\n")
            analyzer = CrossReferenceAnalyzer()
            findings = analyzer.analyze(tmpdir)
            assert any(f.rule_id == "XREF-003" for f in findings)

    def test_signature_mismatch(self):
        """XREF-004: inconsistent function signatures are reported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "a.py").write_text("def foo(x, y): pass\n")
            (path / "b.py").write_text("def foo(x): pass\n")
            analyzer = CrossReferenceAnalyzer()
            findings = analyzer.analyze(tmpdir)
            assert any(f.rule_id == "XREF-004" for f in findings)

    def test_no_false_positive_for_used_export(self):
        """Used exports are not reported as unused."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "mod.py").write_text("def public_func(): pass\n")
            (path / "main.py").write_text("from mod import public_func\n")
            analyzer = CrossReferenceAnalyzer()
            findings = analyzer.analyze(tmpdir)
            assert not any(f.rule_id == "XREF-001" for f in findings)

    def test_stdlib_imports_ignored_for_missing(self):
        """Standard library imports are not flagged as missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "main.py").write_text("import os\n")
            analyzer = CrossReferenceAnalyzer()
            findings = analyzer.analyze(tmpdir)
            assert not any(f.rule_id == "XREF-003" for f in findings)

    def test_to_review_issue_dict(self):
        """CrossReferenceFinding emits v1-compatible ReviewIssue shape."""
        finding = CrossReferenceFinding(
            rule_id="XREF-001",
            message="unused",
            severity=Severity.LOW,
            line=1,
            column=0,
            category="best_practice",
            file_path="mod.py",
            symbol="func",
        )
        d = finding.to_review_issue_dict()
        assert d["file_path"] == "mod.py"
        assert d["title"] == "XREF-001"
        assert d["source_agent"] == "cross_reference"

    def test_syntax_error_handling(self):
        """Syntax errors during parsing are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "bad.py").write_text("def foo(\n")
            analyzer = CrossReferenceAnalyzer()
            findings = analyzer.analyze(tmpdir)
            # Should not crash; may return empty or partial results
            assert isinstance(findings, list)
