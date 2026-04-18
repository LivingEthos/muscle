"""
Pressure fragility review tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from tools.muscle.cli import cli
from tools.muscle.code_review.code_reviewer import CodeReviewer
from tools.muscle.code_review.review_controller import ReviewController
from tools.muscle.code_review.types import (
    PressureFocus,
    ReviewConfig,
    ReviewMode,
)


def test_review_pressure_challenge_threads_into_config() -> None:
    runner = CliRunner()
    env = os.environ.copy()
    env["MINIMAX_API_KEY"] = "test-key"

    mock_result = MagicMock()
    mock_result.session_id = "abc123"
    mock_result.target_path = "/tmp/test"
    mock_result.issues = []
    mock_result.critical_count = 0
    mock_result.high_count = 0
    mock_result.medium_count = 0
    mock_result.low_count = 0
    mock_result.info_count = 0
    mock_result.workflow_name = "pressure-review"
    mock_result.execution_mode = "local"

    mock_run_result = MagicMock()
    mock_run_result.handoff_plan = None
    mock_run_result.stats.duration_seconds = 0.0
    mock_run_result.stats.tokens_used = 0

    mock_instance = MagicMock()
    mock_instance.run.return_value = mock_run_result
    mock_instance.get_review_result.return_value = mock_result

    with patch("tools.muscle.code_review.ReviewController") as mock_class:
        mock_class.return_value = mock_instance
        result = runner.invoke(
            cli,
            [
                "review",
                "--target",
                "/tmp/test",
                "--mode",
                "pressure",
                "--challenge",
                "fragility",
                "--focus",
                "failure,reliability",
            ],
            env=env,
        )

    assert result.exit_code == 0
    config = mock_class.call_args.kwargs["config"]
    assert config.pressure_challenge == "fragility"
    assert config.pressure_focus is not None
    assert config.pressure_focus.failure_modes is True
    assert config.pressure_focus.reliability is True


def test_pressure_review_fragility_challenge_normalizes_hardening_guidance() -> None:
    mock_m27 = MagicMock()
    response = {
        "pressure_findings": [
            {
                "file_path": "test.py",
                "line_number": 7,
                "severity": "MEDIUM",
                "title": "Retry storm after harmless refactor",
                "description": "The retry budget depends on call ordering.",
                "incident_title": "Retries overwhelm downstream service",
                "fragility_type": "ordering_dependency",
                "plausible_triggering_change": "Move the retry hook below logging.",
                "failure_surface": "Timeouts spike and duplicate writes appear.",
                "hardening_suggestions": [
                    "Make retries idempotent.",
                    "Persist retry state before side effects.",
                ],
                "challenge_question": "What guarantees the ordering here?",
            }
        ],
        "summary": {
            "total_examined": 1,
            "critical_findings": 0,
            "high_findings": 0,
            "concerns_addressed": 0,
            "confidence_score": 6,
        },
    }
    mock_m27.chat.return_value = (json.dumps(response), MagicMock(total=120))
    reviewer = CodeReviewer(mock_m27)

    result = reviewer.pressure_review(
        "test.py",
        "if should_retry:\n    run_once()\n",
        PressureFocus(failure_modes=True, reliability=True),
        challenge_mode="fragility",
        telemetry_session_id="sess-1",
        review_mode="pressure",
    )

    assert result["summary"]["challenge_mode"] == "fragility"
    assert result["pressure_findings"][0]["finding_type"] == "fragility"
    assert result["pressure_findings"][0]["suggested_approach"].startswith(
        "Make retries idempotent."
    )


def test_pressure_mode_threads_fragility_challenge_into_controller(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("value = 1\n", encoding="utf-8")
    config = ReviewConfig(
        target_path=str(target),
        mode=ReviewMode.PRESSURE,
        pressure_challenge="fragility",
    )
    mock_client = MagicMock()
    controller = ReviewController(config=config, m27_client=mock_client, use_kb=False)

    with patch.object(controller.static_analyzer, "analyze", return_value=[]):
        with patch.object(
            controller.code_reviewer,
            "pressure_review",
            return_value={
                "pressure_findings": [
                    {
                        "file_path": str(target),
                        "line_number": 1,
                        "severity": "MEDIUM",
                        "title": "Retry storm after refactor",
                        "description": "Ordering dependency hidden in retries.",
                        "suggested_approach": "Persist retry state before side effects.",
                    }
                ],
                "summary": {"token_usage": 5},
            },
        ):
            ctx = controller.run()

    assert ctx.issues[0].source_agent == "pressure:fragility"
