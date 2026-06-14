"""Tests for routing — Phase B.1 task-level classifier."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from muscle.cli import cli
from muscle.host_risk_preflight import HostRiskReasonCode
from muscle.routing import (
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
        assert rd.host_risk is None
        assert rd.host_effort is None


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

    def test_thinking_tags_are_stripped(self) -> None:
        text = '<think>classifying</think>{"tier": "mechanical"}'
        result = _parse_json_response(text)
        assert result["tier"] == "mechanical"

    def test_prose_wrapped_json_is_extracted(self) -> None:
        text = 'Here is the route:\n{"tier": "reasoning"}\nDone.'
        result = _parse_json_response(text)
        assert result["tier"] == "reasoning"

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

    def test_classifier_failure_falls_back_to_offline_route(
        self, router: TaskRouter, mock_client: MagicMock
    ) -> None:
        mock_client.chat.side_effect = RuntimeError("provider unavailable")

        decision = router.route("rename one variable")

        assert decision.routing_profile == "current"
        assert decision.tier == TaskTier.MECHANICAL
        assert decision.recommended in {Recommendation.M27, Recommendation.M27_WITH_VERIFY}


class TestRouteCLI:
    @pytest.fixture()
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_route_text_output(self, runner: CliRunner) -> None:
        with patch("muscle.cli.plumbing.create_client") as mock_client_cls:
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

    def test_route_json_output(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        with patch("muscle.cli.plumbing.create_client") as mock_client_cls:
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
        assert output["host_risk"]["safe_for_fable"] is True
        assert output["host_risk"]["recommended_host"] == "claude-fable-5"
        assert output["host_effort"]["effort"] == "medium"
        assert output["host_effort"]["max_output_tokens"] == 4096
        assert output["recommended_host_role"] == "premium-host"
        assert output["recommended_executor_role"] == "cheap-worker"
        assert output["host_capability_profile"] == "claude-fable-5"
        assert output["executor_provider"] == "minimax-plan"
        assert output["executor_capability_profile"] == "minimax-m3"
        assert output["provider_identity_trust"] == "first-party"
        assert output["provider_cost_confidence"] == "known"

    def test_route_json_includes_host_risk_metadata(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("MINIMAX_API_KEY", None)
            _os.environ.pop("ANTHROPIC_API_KEY", None)
            result = runner.invoke(
                cli,
                [
                    "route",
                    "--task",
                    "Internal authorized pentest exploit proof of concept for our lab app",
                    "--json",
                ],
            )

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["host_risk"]["likely_fallback"] is True
        assert output["host_risk"]["needs_user_confirmation"] is True
        assert output["host_risk"]["recommended_host"] == "claude-opus-4-8"
        assert "cyber_dual_use" in output["host_risk"]["reason_codes"]
        assert output["host_effort"]["effort"] == "medium"
        assert output["recommended_host_role"] == "fallback-host"

    def test_route_json_can_surface_openrouter_executor_metadata(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MUSCLE_PROVIDER", "openrouter-api")
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        result = runner.invoke(cli, ["route", "--task", "summarize static findings", "--json"])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["executor_provider"] == "openrouter-api"
        assert output["recommended_executor_role"] == "user-selected-gateway"
        assert output["executor_capability_profile"] == "openrouter-selected"
        assert output["provider_identity_trust"] == "gateway-reported"
        assert output["provider_cost_confidence"] == "unknown"

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
        with patch("muscle.cli.plumbing.create_client") as mock_client_cls:
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
        assert decision.host_risk is not None
        assert decision.host_risk.safe_for_fable is True
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "high"

    def test_fable_risk_is_labeled_separately_from_architectural_escalation(self) -> None:
        decision = offline_route(
            "mode=pressure; workflow=pressure-review; target=file:/tmp/exploit.py; "
            "intensity=deep; requested_tools=ghidra; "
            "task=Use Ghidra to reconstruct exploit shellcode from a firmware binary"
        )

        assert decision.recommended == Recommendation.ESCALATE_TO_HOST
        assert decision.tier == TaskTier.ARCHITECTURAL
        assert decision.host_risk is not None
        assert decision.host_risk.likely_fallback is True
        assert (
            HostRiskReasonCode.BINARY_RECONSTRUCTION_OR_EXPLOIT_LIKE
            in decision.host_risk.reason_codes
        )
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "high"

    def test_high_critical_route_cannot_remain_medium_effort(self) -> None:
        decision = offline_route(
            "mode=review; workflow=review-smart; target=file:/tmp/app.py; "
            "static_issue_count=2; high_critical_issue_count=1"
        )

        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "high"
        assert decision.host_effort.must_not_downgrade is True

    def test_likely_fallback_suppresses_unrequested_max_effort(self) -> None:
        decision = offline_route(
            "mode=pressure; workflow=pressure-review; target=file:/tmp/exploit.py; "
            "verification_failure_count=3; requested_tools=ghidra; "
            "task=Use Ghidra to reconstruct exploit shellcode from a firmware binary"
        )

        assert decision.host_risk is not None
        assert decision.host_risk.likely_fallback is True
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "xhigh"
        assert decision.host_effort.avoided_escalation is True


class TestHostSynthesisFloor:
    def test_opus_host_raises_routine_floor_to_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MUSCLE_HOST_MODEL", "opus")
        decision = offline_route("rename a variable across files")
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "high"

    def test_unknown_host_keeps_routine_floor_medium(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("MUSCLE_HOST_MODEL", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        decision = offline_route("rename a variable across files")
        assert decision.host_effort is not None
        assert decision.host_effort.effort.value == "medium"


def test_benchmark_routing_profiles_prefers_candidate_without_quality_regression() -> None:
    result = benchmark_routing_profiles()

    assert result["candidate_quality"] >= result["baseline_quality"]
    assert "promotion_rule" in result
    assert result["cases"]
