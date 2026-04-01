"""
Unit tests for project_builder.py
"""

from pathlib import Path

from tools.muscle.project_builder import ProjectBuilder


class TestProjectBuilder:
    def test_init(self):
        builder = ProjectBuilder(language="python", project_name="myproject")
        assert builder.language == "python"
        assert builder.project_name == "myproject"

    def test_detect_language_python(self):
        lang = ProjectBuilder.detect_language_from_task(
            "build a REST API with FastAPI and user authentication"
        )
        assert lang == "python"

    def test_detect_language_javascript(self):
        lang = ProjectBuilder.detect_language_from_task(
            "build a Node.js Express API with JWT authentication"
        )
        assert lang == "javascript"

    def test_detect_language_go(self):
        lang = ProjectBuilder.detect_language_from_task(
            "build a Go service with goroutines and channels"
        )
        assert lang == "go"

    def test_detect_language_unknown(self):
        lang = ProjectBuilder.detect_language_from_task("build something with xyz framework")
        assert lang is None

    def test_detect_language_does_not_match_ts_inside_tests(self):
        lang = ProjectBuilder.detect_language_from_task("investigate flaky tests in backend")
        assert lang is None

    def test_build_python(self, tmp_path):
        builder = ProjectBuilder(language="python", project_name="testproject")
        files = builder.build(str(tmp_path))
        assert isinstance(files, list)
        if files:
            for f in files:
                assert Path(f).exists()

    def test_build_unknown_language(self, tmp_path):
        builder = ProjectBuilder(language="unknown-lang", project_name="test")
        files = builder.build(str(tmp_path))
        assert files == []

    def test_template_formatting(self, tmp_path):
        builder = ProjectBuilder(language="python", project_name="MyApp")
        files = builder.build(str(tmp_path), description="A test application")
        assert isinstance(files, list)

    def test_build_uses_custom_description(self, tmp_path):
        builder = ProjectBuilder(language="python", project_name="MyApp")
        builder.build(str(tmp_path), description="A test application")
        readme = (tmp_path / "README.md").read_text()
        assert "A test application" in readme
