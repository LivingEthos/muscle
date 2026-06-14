from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from muscle.visual_devflow import (
    VisualDevFlowBridge,
    VisualDevFlowEmitter,
    enable_visual_devflow,
)


def test_emitter_discovers_url_from_agent_env(tmp_path: Path) -> None:
    state_dir = tmp_path / ".visual-devflow"
    state_dir.mkdir()
    (state_dir / "agent-env").write_text(
        "VISUAL_DEVFLOW_ENABLED=1\nVISUAL_DEVFLOW_URL=http://127.0.0.1:3456\n",
        encoding="utf-8",
    )

    emitter = VisualDevFlowEmitter.discover(tmp_path)

    assert emitter.enabled
    assert emitter.url == "http://127.0.0.1:3456"


def test_emitter_discovers_url_from_state_json(tmp_path: Path) -> None:
    state_dir = tmp_path / ".visual-devflow"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        '{"enabled": true, "url": "http://127.0.0.1:4567"}',
        encoding="utf-8",
    )

    emitter = VisualDevFlowEmitter.discover(tmp_path)

    assert emitter.enabled
    assert emitter.url == "http://127.0.0.1:4567"


def test_emit_task_posts_to_visual_devflow(monkeypatch) -> None:
    posts: list[dict] = []

    def fake_post(url: str, json: dict, timeout: float) -> object:
        posts.append({"url": url, "json": json, "timeout": timeout})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr("muscle.visual_devflow.requests.post", fake_post)
    emitter = VisualDevFlowEmitter(project_path=Path("/project"), url="http://127.0.0.1:3456")

    emitted = emitter.emit_task(
        task_id="task-1",
        kind="muscle-review",
        status="running",
        name="MUSCLE review",
        path="/project/src/app.py",
        meta={"session_id": "abc"},
    )

    assert emitted is True
    assert posts[0]["url"] == "http://127.0.0.1:3456/api/events/task"
    assert posts[0]["json"]["path"] == "src/app.py"
    assert posts[0]["json"]["meta"]["system"] == "muscle"
    assert posts[0]["json"]["meta"]["session_id"] == "abc"


def test_emit_task_fails_open(monkeypatch) -> None:
    import requests

    def fake_post(url: str, json: dict, timeout: float) -> object:
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("muscle.visual_devflow.requests.post", fake_post)
    emitter = VisualDevFlowEmitter(project_path=Path("/project"), url="http://127.0.0.1:3456")

    assert (
        emitter.emit_task(
            task_id="task-1",
            kind="muscle-review",
            status="running",
            name="MUSCLE review",
        )
        is False
    )


def test_bridge_maps_loop_events(monkeypatch) -> None:
    posts: list[dict] = []

    def fake_post(url: str, json: dict, timeout: float) -> object:
        posts.append(json)
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr("muscle.visual_devflow.requests.post", fake_post)
    bridge = VisualDevFlowBridge(
        emitter=VisualDevFlowEmitter(Path("/project"), "http://127.0.0.1:3456"),
        project_path=Path("/project"),
        run_task="make a thing",
        run_output_dir="/project/out",
        run_max_iterations=10,
    )

    bridge.handle_loop_event("session_start", {"session": "abc"})
    bridge.handle_loop_event("iteration_start", {"iteration": 2})
    bridge.handle_loop_event("session_complete", {"status": "success"})

    task_events = [payload for payload in posts if "taskId" in payload]
    assert task_events[0]["taskId"] == "muscle-run-abc"
    assert task_events[0]["status"] == "started"
    assert task_events[1]["progress"] == 17
    assert task_events[-1]["status"] == "succeeded"


def test_bridge_maps_review_fix_file(monkeypatch) -> None:
    posts: list[dict] = []

    def fake_post(url: str, json: dict, timeout: float) -> object:
        posts.append(json)
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr("muscle.visual_devflow.requests.post", fake_post)
    bridge = VisualDevFlowBridge(
        emitter=VisualDevFlowEmitter(Path("/project"), "http://127.0.0.1:3456"),
        project_path=Path("/project"),
        review_target="/project/src",
        review_mode="hybrid",
    )

    bridge.handle_review_event("review_start", {"session": "rev1"})
    bridge.handle_review_event("fix_applied", {"file": "/project/src/app.py", "line": 12})

    fix_events = [payload for payload in posts if payload.get("kind") == "muscle-fix"]
    assert fix_events[0]["taskId"] == "muscle-review-rev1"
    assert fix_events[0]["path"] == "src/app.py"


def test_enable_visual_devflow_reports_missing_command(tmp_path: Path) -> None:
    result = enable_visual_devflow(
        tmp_path,
        command=str(tmp_path / "missing-visual-devflow"),
    )

    assert result["ok"] is False
    assert result["status"] == "missing-command"
