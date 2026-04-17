"""Multi-language fix-verification rollback tests (TEST-02).

Exercises ``FixGenerator.apply_fix`` for Python, JavaScript, and
TypeScript files. For each language:

- The source file starts syntactically valid.
- A staged fix is invalid (syntax error / tsc error / node --check fail).
- ``apply_fix`` must reject the staged content, leave the original file
  unchanged, and leave no ``*.muscle.bak`` stragglers on disk.

Subprocess calls for JS/TS validators are mocked so the test is offline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.code_review.fix_generator import FixGenerator
from tools.muscle.code_review.types import IssueCategory, ReviewIssue, Severity


def _issue(file_path: Path) -> ReviewIssue:
    return ReviewIssue(
        file_path=str(file_path),
        line_number=1,
        severity=Severity.MEDIUM,
        category=IssueCategory.STYLE,
        cwe_id=None,
        title="Test",
        description="Test fix",
        code_snippet="x",
        suggested_fix=None,
        auto_fixable=True,
    )


def _assert_rollback(file_path: Path, original_content: str) -> None:
    """Shared assertions: original file intact, no .muscle.bak left."""
    assert file_path.read_text() == original_content
    stragglers = list(file_path.parent.glob("*.muscle.bak"))
    assert stragglers == [], f"Unexpected .muscle.bak stragglers: {stragglers}"
    stragglers_tmp = list(file_path.parent.glob("*.muscle.tmp"))
    assert stragglers_tmp == [], f"Unexpected .muscle.tmp stragglers: {stragglers_tmp}"


class TestApplyFixRollbackPython:
    """Python: the built-in compile() check catches syntax errors."""

    def test_python_syntax_error_rolls_back(self, tmp_path):
        target = tmp_path / "sample.py"
        original = "def greet(name):\n    return 'hello ' + name\n"
        target.write_text(original)

        generator = FixGenerator(MagicMock())  # verify_compile default True
        bad_fix = "def greet(name):\n    return 'hello ' + \n"  # trailing op = SyntaxError

        result = generator.apply_fix(_issue(target), bad_fix)

        assert result.success is False
        assert result.applied is False
        assert "syntax" in (result.error or "").lower()
        _assert_rollback(target, original)


class TestApplyFixRollbackJavaScript:
    """JavaScript: `node --check` is invoked via subprocess.run; mock it."""

    def test_js_syntax_error_rolls_back(self, tmp_path):
        target = tmp_path / "sample.js"
        original = "function greet(name) { return 'hello ' + name; }\n"
        target.write_text(original)

        generator = FixGenerator(MagicMock())
        bad_fix = "function greet(name) { return 'hello ' + ; }\n"

        # Fake `node --check` returning non-zero + an error message on stderr.
        fake_proc = MagicMock()
        fake_proc.returncode = 1
        fake_proc.stderr = "SyntaxError: Unexpected token ';'\n"
        fake_proc.stdout = ""

        with patch(
            "tools.muscle.code_review.fix_generator.subprocess.run",
            return_value=fake_proc,
        ) as mock_run:
            result = generator.apply_fix(_issue(target), bad_fix)

        # Subprocess was actually consulted with node --check
        assert mock_run.called
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "node"
        assert "--check" in cmd

        assert result.success is False
        assert result.applied is False
        assert "validation failed" in (result.error or "").lower()
        _assert_rollback(target, original)

    def test_js_node_not_installed_still_rolls_back(self, tmp_path):
        """If `node` isn't installed, apply_fix must not silently succeed."""
        target = tmp_path / "sample.js"
        original = "const x = 1;\n"
        target.write_text(original)

        generator = FixGenerator(MagicMock())

        with patch(
            "tools.muscle.code_review.fix_generator.subprocess.run",
            side_effect=FileNotFoundError("node not found"),
        ):
            result = generator.apply_fix(_issue(target), "const x = ;\n")

        assert result.success is False
        assert result.applied is False
        assert "node" in (result.error or "").lower()
        _assert_rollback(target, original)


class TestApplyFixRollbackTypeScript:
    """TypeScript: `npx tsc --noEmit` is invoked; mock the subprocess."""

    def test_ts_type_error_rolls_back(self, tmp_path):
        target = tmp_path / "sample.ts"
        original = "export function greet(name: string): string { return name; }\n"
        target.write_text(original)

        generator = FixGenerator(MagicMock())
        bad_fix = "export function greet(name: string): string { return ; }\n"

        fake_proc = MagicMock()
        fake_proc.returncode = 2
        fake_proc.stderr = "sample.ts(1,64): error TS1109: Expression expected.\n"
        fake_proc.stdout = ""

        with patch(
            "tools.muscle.code_review.fix_generator.subprocess.run",
            return_value=fake_proc,
        ) as mock_run:
            result = generator.apply_fix(_issue(target), bad_fix)

        assert mock_run.called
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "npx"
        assert "tsc" in cmd
        assert "--noEmit" in cmd

        assert result.success is False
        assert result.applied is False
        assert "validation failed" in (result.error or "").lower()
        _assert_rollback(target, original)

    def test_ts_subprocess_timeout_still_rolls_back(self, tmp_path):
        """A tsc timeout is treated as validation failure, not silent pass."""
        target = tmp_path / "sample.ts"
        original = "export const x = 1;\n"
        target.write_text(original)

        generator = FixGenerator(MagicMock())

        with patch(
            "tools.muscle.code_review.fix_generator.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tsc", timeout=30),
        ):
            result = generator.apply_fix(_issue(target), "export const x = ;\n")

        assert result.success is False
        assert result.applied is False
        _assert_rollback(target, original)


class TestApplyFixRollbackSharedInvariants:
    """Cross-language invariant: no bak/tmp stragglers after rejection."""

    @pytest.mark.parametrize(
        "suffix,language,bad_content,fake_proc_returncode,needs_subprocess",
        [
            ("py", "python", "def f(:\n", None, False),
            ("js", "javascript", "const a = ;\n", 1, True),
            ("ts", "typescript", "const a: number = ;\n", 2, True),
        ],
    )
    def test_no_stragglers_after_rejection(
        self,
        tmp_path,
        suffix,
        language,
        bad_content,
        fake_proc_returncode,
        needs_subprocess,
    ):
        target = tmp_path / f"sample.{suffix}"
        original = "// ok\n" if suffix != "py" else "x = 1\n"
        target.write_text(original)

        generator = FixGenerator(MagicMock())

        if needs_subprocess:
            fake_proc = MagicMock()
            fake_proc.returncode = fake_proc_returncode
            fake_proc.stderr = "validator said no"
            fake_proc.stdout = ""
            cm = patch(
                "tools.muscle.code_review.fix_generator.subprocess.run",
                return_value=fake_proc,
            )
        else:
            # no-op patch so the `with` block is uniform
            cm = patch(
                "tools.muscle.code_review.fix_generator.subprocess.run",
                return_value=MagicMock(returncode=0, stderr="", stdout=""),
            )

        with cm:
            result = generator.apply_fix(_issue(target), bad_content)

        assert result.success is False
        _assert_rollback(target, original)
