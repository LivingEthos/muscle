from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tools.muscle.cli import cli
from tools.muscle.project_memory import ProjectMemory


def test_optimize_status_displays_project_summary(tmp_path: Path, monkeypatch) -> None:
    pm = ProjectMemory(str(tmp_path))
    pm.insert_token_savings_entry(
        project_path=str(tmp_path),
        session_id="sess-1",
        stage="review_total",
        workflow_name="review-smart",
        comparable_key="review_total|python|unknown|directory",
        baseline_tokens=1000,
        actual_tokens=800,
        delta_tokens=200,
        confidence=0.5,
        realized=False,
        estimation_type="estimated",
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["optimize", "status"])

    assert result.exit_code == 0
    assert "Optimization Status" in result.output
    assert "Net Tokens Saved" in result.output


def test_optimize_recommendations_handles_empty_project(tmp_path: Path, monkeypatch) -> None:
    ProjectMemory(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["optimize", "recommendations"])

    assert result.exit_code == 0
    assert "No safe recommendations yet" in result.output
