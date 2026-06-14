"""Tests for diff_analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from muscle.diff_analyzer import DiffAnalyzer

SAMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,3 @@
 def hello():
-    print("old")
+    print("new")
     return 42
"""


def test_parse_diff_extracts_file_diff():
    diffs = DiffAnalyzer.parse_diff(SAMPLE_DIFF)
    assert len(diffs) == 1
    assert diffs[0].path == Path("src/foo.py")


def test_parse_diff_hunk_properties():
    diffs = DiffAnalyzer.parse_diff(SAMPLE_DIFF)
    hunks = diffs[0].hunks
    assert len(hunks) == 1
    assert hunks[0].old_start == 1
    assert hunks[0].new_start == 1
    assert hunks[0].old_lines == 3
    assert hunks[0].new_lines == 3


def test_changed_line_numbers():
    diffs = DiffAnalyzer.parse_diff(SAMPLE_DIFF)
    hunk = diffs[0].hunks[0]
    assert hunk.changed_line_numbers == [2]


def test_is_pure_addition():
    add_diff = """\
diff --git a/src/bar.py b/src/bar.py
--- a/src/bar.py
+++ b/src/bar.py
@@ -5,0 +6 @@
+    extra()
"""
    diffs = DiffAnalyzer.parse_diff(add_diff)
    assert diffs[0].hunks[0].is_pure_addition is True


def test_file_diff_is_new_file():
    new_diff = """\
diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+line1
+line2
"""
    diffs = DiffAnalyzer.parse_diff(new_diff)
    assert diffs[0].is_new_file is True


def test_file_diff_is_deleted():
    del_diff = """\
diff --git a/src/gone.py b/src/gone.py
--- a/src/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2
"""
    diffs = DiffAnalyzer.parse_diff(del_diff)
    assert diffs[0].is_deleted is True


def test_extract_changed_context():
    diffs = DiffAnalyzer.parse_diff(SAMPLE_DIFF)
    content = "def hello():\n    print(\"old\")\n    return 42\n"
    ctx = DiffAnalyzer.extract_changed_context(
        Path("src/foo.py"), content, diffs[0], context_lines=2
    )
    assert ">>>" in ctx
    assert "def hello()" in ctx


def test_from_string_alias():
    diffs = DiffAnalyzer.from_string(SAMPLE_DIFF)
    assert len(diffs) == 1


@pytest.mark.asyncio
async def test_diff_review_scope_builder(tmp_path: Path) -> None:
    from muscle.diff_analyzer import DiffReviewScopeBuilder

    class FakeFS:
        def read_text(self, path: Path) -> str:
            return "line1\nline2\nline3\n"

    builder = DiffReviewScopeBuilder(tmp_path, FakeFS())
    # No git repo, so from_git will fail; test the builder structure instead
    assert builder.repo_path == tmp_path


def test_empty_diff():
    diffs = DiffAnalyzer.parse_diff("")
    assert diffs == []
