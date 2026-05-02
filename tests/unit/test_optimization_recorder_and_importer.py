from __future__ import annotations

import json
from pathlib import Path

from tools.muscle.optimization.importers import ExternalBenchmarkImporter
from tools.muscle.optimization.recorder import LLMCallEvent, TelemetryRecorder
from tools.muscle.project_memory import ProjectMemory


def test_telemetry_recorder_flushes_llm_calls(tmp_path: Path) -> None:
    project_path = tmp_path / "telemetry-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    recorder = TelemetryRecorder(pm)

    recorder.record_llm_call(
        LLMCallEvent(
            project_path=str(project_path),
            call_id="call-1",
            session_id="session-1",
            stage="generate",
            model="MiniMax-M2.7",
            input_tokens=100,
            output_tokens=25,
            duration_ms=50,
            success=True,
            requested_label="claude-sonnet-4",
            provider_endpoint="https://api.minimax.io/anthropic",
            provider_fingerprint="api.minimax.io/anthropic",
            canonical_model_key="openai/gpt-5@1",
            identity_source="manual_override",
            identity_confidence=1.0,
            manual_override=True,
            metadata_json=json.dumps(
                {
                    "requested_label": "claude-sonnet-4",
                    "canonical_model_key": "openai/gpt-5@1",
                },
                sort_keys=True,
            ),
        )
    )
    recorder.close()

    calls = pm.list_llm_calls(project_path=str(project_path), session_id="session-1")
    assert len(calls) == 1
    assert calls[0]["stage"] == "generate"
    assert calls[0]["requested_label"] == "claude-sonnet-4"
    assert calls[0]["canonical_model_key"] == "openai/gpt-5@1"
    assert calls[0]["identity_source"] == "manual_override"
    assert calls[0]["manual_override"] == 1


def test_telemetry_recorder_flushes_model_identity_history(tmp_path: Path) -> None:
    project_path = tmp_path / "telemetry-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    recorder = TelemetryRecorder(pm)

    recorder.record_model_identity_history(
        str(project_path),
        {
            "requested_label": "custom-openai-alias",
            "provider_endpoint": "https://api.openai.com/v1",
            "provider_fingerprint": "api.openai.com/v1",
            "canonical_model_key": "openai/gpt-5-mini@1",
            "identity_source": "provider_introspection",
            "confidence": 0.98,
            "manual_override": False,
            "metadata": {
                "provider_owner": "openai",
                "response_model_name": "gpt-5-mini-2026-04-14",
            },
        },
    )
    recorder.close()

    latest = pm.get_latest_model_identity(str(project_path))
    assert latest is not None
    assert latest["canonical_model_key"] == "openai/gpt-5-mini@1"
    assert latest["identity_source"] == "provider_introspection"


def test_codex_importer_is_project_scoped_and_idempotent(tmp_path: Path, monkeypatch) -> None:
    project_path = tmp_path / "tracked-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    importer = ExternalBenchmarkImporter(pm, str(project_path))

    codex_home = tmp_path / "codex-home"
    session_dir = codex_home / "sessions" / "2026" / "04" / "15" / "session-a"
    session_dir.mkdir(parents=True)
    rollout_path = session_dir / "rollout-test.jsonl"
    lines = [
        {
            "type": "session_meta",
            "timestamp": "2026-04-15T10:00:00Z",
            "payload": {
                "session_id": "codex-session-1",
                "cwd": str(project_path),
                "model": "gpt-5.4",
                "originator": "test",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "fix the failing test"}],
            },
        },
        {
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec_command"},
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-15T10:00:05Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "model": "gpt-5.4",
                    "last_token_usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 20,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 10,
                    },
                },
            },
        },
    ]
    rollout_path.write_text(
        "\n".join(json.dumps(line) for line in lines),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    detailed_first = importer.import_sessions_with_deltas(provider="codex", since_days=30)
    second = importer.import_sessions(provider="codex", since_days=30)

    assert detailed_first["codex"]["sessions_imported"] == 1
    assert detailed_first["codex"]["turns_imported"] == 1
    assert len(detailed_first["codex"]["new_turn_ids"]) == 1
    assert second["codex"]["turns_imported"] == 0
    sessions = pm.list_external_benchmark_sessions(str(project_path), provider="codex")
    assert len(sessions) == 1


def test_codex_importer_skips_rate_limit_only_events(tmp_path: Path, monkeypatch) -> None:
    project_path = tmp_path / "tracked-project"
    project_path.mkdir()
    pm = ProjectMemory(str(project_path))
    importer = ExternalBenchmarkImporter(pm, str(project_path))

    codex_home = tmp_path / "codex-home"
    sessions_dir = codex_home / "sessions" / "2026" / "04" / "15"
    sessions_dir.mkdir(parents=True)
    rollout_path = sessions_dir / "rollout-test.jsonl"
    lines = [
        {
            "type": "session_meta",
            "timestamp": "2026-04-15T10:00:00Z",
            "payload": {
                "session_id": "codex-session-2",
                "cwd": str(project_path),
                "model": "gpt-5.4",
                "originator": "test",
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-15T10:00:01Z",
            "payload": {
                "type": "token_count",
                "info": None,
                "rate_limits": {"plan_type": "plus"},
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "review the file"}],
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-04-15T10:00:05Z",
            "payload": {
                "type": "token_count",
                "info": {
                    "model": "gpt-5.4",
                    "last_token_usage": {
                        "input_tokens": 75,
                        "cached_input_tokens": 0,
                        "output_tokens": 25,
                        "reasoning_output_tokens": 5,
                    },
                },
            },
        },
    ]
    rollout_path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    summary = importer.import_sessions(provider="codex", since_days=30)

    assert summary["codex"]["sessions_imported"] == 1
    assert summary["codex"]["turns_imported"] == 1
