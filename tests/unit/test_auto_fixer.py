"""Tests for auto_fixer."""

from __future__ import annotations

from pathlib import Path

from tools.muscle.services.auto_fixer import (
    AutoFixer,
    GitBackup,
    Suggestion,
)


def test_git_backup_file_fallback(tmp_path: Path) -> None:
    file_path = tmp_path / "test.py"
    file_path.write_text("original")
    backup = GitBackup(tmp_path)
    backup._has_git = False
    assert backup.create_backup([file_path]) is True
    assert (Path(str(file_path) + ".muscle.bak")).exists()


def test_git_backup_restore(tmp_path: Path) -> None:
    file_path = tmp_path / "test.py"
    file_path.write_text("original")
    backup = GitBackup(tmp_path)
    backup._has_git = False
    backup.create_backup([file_path])
    file_path.write_text("modified")
    backup.restore_backup()
    assert file_path.read_text() == "original"


def test_path_traversal_blocked(tmp_path: Path) -> None:
    fixer = AutoFixer(tmp_path)
    suggestion = Suggestion(
        id="s1",
        review_id="r1",
        message="bad",
        severity="high",
        fix="REPLACE WITH: x",
        file_path="../outside.py",
        start_line=1,
        end_line=1,
    )
    results = fixer.apply_fixes([suggestion])
    assert len(results) == 1
    assert results[0].success is False
    assert "Path traversal" in results[0].error_message


def test_line_replacement_strategy(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("a = 1\nb = 2\nc = 3\n")
    fixer = AutoFixer(tmp_path)
    suggestion = Suggestion(
        id="s1",
        review_id="r1",
        message="fix b",
        severity="medium",
        fix="REPLACE WITH: b = 99",
        file_path="target.py",
        start_line=2,
        end_line=2,
    )
    results = fixer.apply_fixes([suggestion])
    assert results[0].success is True
    assert "b = 99" in target.read_text()


def test_find_replace_strategy(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("hello world\n")
    fixer = AutoFixer(tmp_path)
    suggestion = Suggestion(
        id="s1",
        review_id="r1",
        message="fix",
        severity="medium",
        fix="FIND: world\nREPLACE: universe",
        file_path="target.py",
        start_line=1,
        end_line=1,
    )
    results = fixer.apply_fixes([suggestion])
    assert results[0].success is True
    assert "hello universe" in target.read_text()


def test_regex_strategy(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("foo bar baz\n")
    fixer = AutoFixer(tmp_path)
    suggestion = Suggestion(
        id="s1",
        review_id="r1",
        message="fix",
        severity="medium",
        fix="regex:bar->qux",
        file_path="target.py",
    )
    results = fixer.apply_fixes([suggestion])
    assert results[0].success is True
    assert "foo qux baz" in target.read_text()


def test_regex_too_long_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("abc\n")
    fixer = AutoFixer(tmp_path)
    suggestion = Suggestion(
        id="s1",
        review_id="r1",
        message="fix",
        severity="medium",
        fix="regex:" + "a" * 201 + "->b",
        file_path="target.py",
    )
    results = fixer.apply_fixes([suggestion])
    assert results[0].success is False
    assert "too long" in results[0].error_message


def test_python_syntax_validation_blocks_bad_fix(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("x = 1\n")
    fixer = AutoFixer(tmp_path)
    suggestion = Suggestion(
        id="s1",
        review_id="r1",
        message="break syntax",
        severity="medium",
        fix="REPLACE WITH: def broken(",
        file_path="target.py",
        start_line=1,
        end_line=1,
    )
    results = fixer.apply_fixes([suggestion])
    assert results[0].success is False
    assert "syntax error" in results[0].error_message.lower()
