"""Tests for routing — Phase B.1 task-level classifier."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from tools.muscle.cli import cli
from tools.muscle.routing import (
    Recommendation,
    RouteDecision,
    TaskRouter,
    TaskTier,
    _parse_json_response,
    benchmark_routing_profiles,
    offline_route,
)


class TestTaskTier:
    def test_values(self) -> None:
        assert TaskTier.MECHANICAL.value == "mechanical"
        assert TaskTier.REASONING.value == "reasoning"
        assert TaskTier.ARCHITECTURAL.value == "architectural"


class TestRecommendation:
    def test_values(self) -> None:
        assert Recommendation.M27.value == "m27"
        assert Recommendation.M27_WITH_VERIFY.value == "m27_with_verify"
        assert Recommendation.ESCALATE_TO_HOST.value == "escalate_to_host"


class TestRouteDecision:
    def test_defaults(self) -> None:
        rd = RouteDecision(
            tier=TaskTier.MECHANICAL,
            recommended=Recommendation.M27,
            confidence=0.9,
            rationale="simple task",
        )
        assert rd.from_cache is False
        assert rd.routing_profile == "current"


class TestParseJsonResponse:
    def test_plain_json(self) -> None:
        result = _parse_json_response('{"tier": "mechanical"}')
        assert result["tier"] == "mechanical"

    def test_json_fence(self) -> None:
        text = '```json\n{"tier": "mechanical"}\n```'
        result = _parse_json_response(text)
        assert result["tier"] == "mechanical"

    def test_plain_fence(self) -> None:
        text = '```\n{"tier": "mechanical"}\n```'
        result = _parse_json_response(text)
        assert result["tier"] == "mechanical"

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json")


class TestTaskRouter:
    @pytest.fixture()
    def mock_client(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture()
    def router(self, mock_client: MagicMock, tmp_path: Path) -> TaskRouter:
        return TaskRouter(mock_client, cache_db_path=tmp_path / "test_cache.db")

    def test_classifier_returns_valid_schema(
        self, router: TaskRouter, mock_client: MagicMock
    ) -> None:
        mock_client.chat.return_value = (
            '{"tier": "mechanical", "recommended": "m27_with_verify", '
            '"confidence": 0.85, "rationale": "test task"}',
            MagicMock(),
        )
        decision = router.route("write unit test for foo.py")
        assert decision.tier == TaskTier.MECHANICAL
        assert decision.recommended == Recommendation.M27_WITH_VERIFY
        assert decision.confidence == 0.85
        assert decision.from_cache is False

    def test_low_confidence_defaults_to_escalate(
        self, router: TaskRouter, mock_client: MagicMock
    ) -> None:
        mock_client.chat.return_value = (
            '{"tier": "reasoning", "recommended": "m27", '
            '"confidence": 0.3, "rationale": "uncertain"}',
            MagicMock(),
        )
        decision = router.route("some ambiguous task")
        assert decision.recommended == Recommendation.ESCALATE_TO_HOST

    def test_architectural_always_escalates(
        self, router: TaskRouter, mock_client: MagicMock
    ) -> None:
        mock_client.chat.return_value = (
            '{"tier": "architectural", "recommended": "m27", '
            '"confidence": 0.9, "rationale": "design task"}',
            MagicMock(),
        )
        decision = router.route("redesign the auth system")
        assert decision.tier == TaskTier.ARCHITECTURAL
        assert decision.recommended == Recommendation.ESCALATE_TO_HOST

    def test_mechanical_with_verify_for_test_tasks(
        self, router: TaskRouter, mock_client: MagicMock
    ) -> None:
        mock_client.chat.return_value = (
            '{"tier": "mechanical", "recommended": "m27_with_verify", '
            '"confidence": 0.9, "rationale": "test task"}',
            MagicMock(),
        )
        decision = router.route("write tests for the parser module")
        assert decision.recommended == Recommendation.M27_WITH_VERIFY

    def test_cache_hit_skips_m27_call(self, router: TaskRouter, mock_client: MagicMock) -> None:
        mock_client.chat.return_value = (
            '{"tier": "mechanical", "recommended": "m27", '
            '"confidence": 0.9, "rationale": "cache test"}',
            MagicMock(),
        )
        first = router.route("identical task description")
        assert first.from_cache is False
        assert mock_client.chat.call_count == 1

        second = router.route("identical task description")
        assert second.from_cache is True
        assert second.tier == first.tier
        assert second.recommended == first.recommended
        assert mock_client.chat.call_count == 1

    def test_scope_hint_included_in_prompt(
        self, router: TaskRouter, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        mock_client.chat.return_value = (
            '{"tier": "mechanical", "recommended": "m27", '
            '"confidence": 0.9, "rationale": "scoped"}',
            MagicMock(),
        )
        scope_file = tmp_path / "test_scope.py"
        scope_file.write_text("x = 1")
        router.route("fix typo", scope=scope_file)
        call_args = mock_client.chat.call_args
        user_msg = call_args[1]["messages"][0]["content"]
        assert "Scope hint" in user_msg


class TestRouteCLI:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_route_text_output(self, runner: CliRunner) -> None:
        with patch("tools.muscle.cli.M27Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_client_cls.return_value = mock_instance
            mock_instance.chat.return_value = (
                '{"tier": "mechanical", "recommended": "m27", '
                '"confidence": 0.9, "rationale": "test task"}',
                MagicMock(),
            )
            with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
                result = runner.invoke(cli, ["route", "--task", "fix a typo"])
        assert result.exit_code == 0
        assert "Tier:" in result.output
        assert "mechanical" in result.output

    def test_route_json_output(self, runner: CliRunner) -> None:
        with patch("tools.muscle.cli.M27Client") as mock_client_cls:
            mock_instance = MagicMock()
            mock_client_cls.return_value = mock_instance
            mock_instance.chat.return_value = (
                '{"tier": "reasoning", "recommended": "m27", '
                '"confidence": 0.7, "rationale": "debug task"}',
                MagicMock(),
            )
            with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
                result = runner.invoke(cli, ["route", "--task", "debug null pointer", "--json"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["tier"] == "reasoning"
        assert output["recommended"] == "m27"

    def test_route_falls_back_to_offline_when_no_api_key(self, runner: CliRunner) -> None:
        """B1 + N3: missing API key must not raise; the heuristic produces a
        valid decision and the JSON payload exposes the fallback reason."""
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("MINIMAX_API_KEY", None)
            _os.environ.pop("ANTHROPIC_API_KEY", None)
            result = runner.invoke(cli, ["route", "--task", "rename a variable", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["fallback"] == "offline_heuristic"
        assert payload["fallback_reason"] == "MINIMAX_API_KEY not set"
        assert payload["tier"] in {"mechanical", "reasoning", "architectural"}
        assert payload["recommended"] in {"m27", "m27_with_verify", "escalate_to_host"}

    def test_route_falls_back_when_classifier_raises(self, runner: CliRunner) -> None:
        """B1: if the M2.7 client fails, the CLI falls back to the heuristic
        instead of bubbling a Python traceback up to the host model."""
        with patch("tools.muscle.cli.M27Client") as mock_client_cls:
            mock_client_cls.side_effect = ValueError("boom")
            with patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"}):
                result = runner.invoke(cli, ["route", "--task", "rename a variable", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["fallback"] == "offline_heuristic"
        assert "boom" in payload["fallback_reason"]


class TestOfflineRoute:
    """Public ``offline_route`` API used by the CLI fallback (B1/N3)."""

    def test_default_review_returns_m27(self) -> None:
        decision = offline_route("rename a variable across files")
        assert decision.recommended in {Recommendation.M27, Recommendation.M27_WITH_VERIFY}
        assert decision.tier in {TaskTier.MECHANICAL, TaskTier.REASONING}

    def test_pressure_routes_to_host(self) -> None:
        decision = offline_route(
            "mode=pressure; workflow=pressure-review; target=directory:/tmp; intensity=deep"
        )
        assert decision.recommended == Recommendation.ESCALATE_TO_HOST
        assert decision.tier == TaskTier.ARCHITECTURAL


def test_benchmark_routing_profiles_prefers_candidate_without_quality_regression() -> None:
    result = benchmark_routing_profiles()

    assert result["candidate_quality"] >= result["baseline_quality"]
    assert "promotion_rule" in result
    assert result["cases"]
