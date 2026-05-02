"""
Unit tests for command evidence and declarative output filters.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.muscle.command_evidence import (
    ParserTier,
    build_command_evidence,
    estimate_tokens,
    iter_command_evidence,
)
from tools.muscle.output_filters import (
    apply_output_filters,
    project_filters_trusted,
    trust_project_filters,
    untrust_project_filters,
    verify_filters,
)


def test_command_evidence_persists_raw_failure_output(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()

    evidence = build_command_evidence(
        command=["pytest", "-q"],
        cwd=str(tmp_path),
        exit_code=1,
        duration_ms=42,
        raw_stdout="FAILED test_example.py::test_case - boom",
        raw_stderr="traceback",
        parser_tier=ParserTier.DEGRADED,
        warnings=["fallback parser used"],
    )

    assert evidence.parser_tier == "DEGRADED"
    assert evidence.raw_stdout_path is not None
    assert evidence.raw_stderr_path is not None
    assert Path(evidence.raw_stdout_path).exists()
    assert Path(evidence.raw_stderr_path).exists()
    assert evidence.tokens_raw_estimate >= evidence.tokens_compact_estimate
    assert evidence.tokens_saved_estimate >= 0

    rows = iter_command_evidence(tmp_path)
    assert rows[0]["command"] == ["pytest", "-q"]
    assert rows[0]["raw_stdout_path"] == evidence.raw_stdout_path


def test_command_evidence_truncation_flags_and_token_estimate(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()
    raw = "x" * 10_000

    evidence = build_command_evidence(
        command=["tool"],
        cwd=str(tmp_path),
        exit_code=0,
        duration_ms=1,
        raw_stdout=raw,
        raw_stderr="",
        compact_max_chars=120,
    )

    assert evidence.stdout_truncated is True
    assert evidence.raw_stdout_path is not None
    assert evidence.tokens_raw_estimate == estimate_tokens(raw)
    assert evidence.tokens_compact_estimate < evidence.tokens_raw_estimate


def test_builtin_filter_keeps_failures_while_removing_noise() -> None:
    filtered, warnings = apply_output_filters(
        "pytest -q",
        "collected 3 items\n...\nFAILED test_example.py::test_case - boom",
    )

    assert warnings == []
    assert "FAILED" in filtered
    assert "collected 3 items" not in filtered


def test_project_filter_trust_invalidates_on_content_change(tmp_path: Path) -> None:
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    filters_path = muscle_dir / "filters.yaml"
    filters_path.write_text(
        """
filters:
  - name: strip-ok
    command: tool
    strip_regex: "^OK$"
    tests:
      - input: "OK\\nERROR"
        expected_contains: "ERROR"
        expected_not_contains: "OK"
""".strip(),
        encoding="utf-8",
    )

    assert project_filters_trusted(tmp_path)[0] is False
    trusted = trust_project_filters(tmp_path)
    assert trusted["trusted"] is True
    assert project_filters_trusted(tmp_path)[0] is True

    verify = verify_filters(tmp_path, filter_name="strip-ok", require_all=True)
    assert verify["passed"] is True

    filters_path.write_text(filters_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert project_filters_trusted(tmp_path)[0] is False

    untrusted = untrust_project_filters(tmp_path)
    assert untrusted["removed"] is True


def test_project_filter_success_message_requires_unless_guard(tmp_path: Path) -> None:
    (tmp_path / ".muscle").mkdir()
    (tmp_path / ".muscle" / "filters.yaml").write_text(
        json.dumps(
            {
                "filters": [
                    {
                        "name": "bad-success",
                        "command": "tool",
                        "success_message": "all good",
                        "tests": [{"input": "warning: no", "expected_contains": "warning"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    trust_project_filters(tmp_path)

    filtered, warnings = apply_output_filters("tool", "warning: no", tmp_path)
    assert filtered == "warning: no"
    assert warnings
