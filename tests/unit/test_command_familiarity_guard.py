"""Tests for command familiarity guard."""

from __future__ import annotations

from pathlib import Path

from muscle.command_evidence import build_command_evidence, run_command_with_evidence
from muscle.command_familiarity_guard import CommandFamiliarityGuard


def test_known_pytest_command_is_familiar(tmp_path: Path) -> None:
    result = CommandFamiliarityGuard(tmp_path).check(["pytest", "tests"], tmp_path)

    assert result.checked is True
    assert result.familiar is True
    assert result.risk_level == "low"
    assert result.source == "known_evaluator_allowlist"
    assert result.blocked is False


def test_project_script_command_is_familiar(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project.scripts]\nreview-local = 'pkg:main'\n",
        encoding="utf-8",
    )

    result = CommandFamiliarityGuard(tmp_path).check(["review-local"], tmp_path)

    assert result.familiar is True
    assert result.source == "project_script"


def test_unknown_command_records_unfamiliar_warning(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()

    evidence = build_command_evidence(
        command=["unknown-review-tool", "--json"],
        cwd=str(tmp_path),
        exit_code=0,
        duration_ms=1,
        raw_stdout="{}",
        raw_stderr="",
    )

    assert evidence.command_familiarity["checked"] is True
    assert evidence.command_familiarity["familiar"] is False
    assert "command_unfamiliar" in evidence.warnings


def test_destructive_command_is_blocked_before_execution(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()
    target = tmp_path / "important.txt"
    target.write_text("keep", encoding="utf-8")

    exit_code, _stdout, stderr, evidence = run_command_with_evidence(
        ["rm", str(target)],
        cwd=str(tmp_path),
    )

    assert exit_code == -4
    assert "blocked" in stderr.lower()
    assert target.exists()
    assert evidence.command_familiarity["blocked"] is True
    assert "command_blocked" in evidence.warnings


def test_option_looking_filename_is_warned_until_separator_is_used(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()
    (tmp_path / "-evil.py").write_text("print('x')", encoding="utf-8")

    risky = CommandFamiliarityGuard(tmp_path).check(["ruff", "check", "-evil.py"], tmp_path)
    safe = CommandFamiliarityGuard(tmp_path).check(["ruff", "check", "--", "-evil.py"], tmp_path)

    assert any("option_looking_filename" in warning for warning in risky.warnings)
    assert not any("option_looking_filename" in warning for warning in safe.warnings)
