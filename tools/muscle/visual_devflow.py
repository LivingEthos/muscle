"""
Visual DevFlow bridge for MUSCLE lifecycle events.

Architecture Decision Record (ADR):
- Keep Visual DevFlow optional so MUSCLE remains usable without Node/browser tooling.
- Emit generic task and agent events instead of coupling MUSCLE to dashboard internals.
- Fail open on network/process errors because observability must never block review or generation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 0.75
DISABLED_VALUES = {"0", "false", "no", "off"}
VISUAL_STATE_DIR = ".visual-devflow"
MAX_DETAIL_LENGTH = 220


def _event_value(event: object) -> str:
    value = getattr(event, "value", event)
    return str(value)


def _trim(value: object, limit: int = MAX_DETAIL_LENGTH) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    candidate = url.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate.rstrip("/")


def _parse_agent_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    except OSError:
        return {}
    return data


def _project_visual_url(project_path: Path) -> str | None:
    state_dir = project_path / VISUAL_STATE_DIR
    agent_env = _parse_agent_env(state_dir / "agent-env")
    url = _normalize_url(agent_env.get("VISUAL_DEVFLOW_URL"))
    if url:
        return url

    state_path = state_dir / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(state, dict) and state.get("enabled") is False:
        return None
    if isinstance(state, dict):
        return _normalize_url(str(state.get("url") or ""))
    return None


def _disabled_by_env() -> bool:
    value = os.environ.get("MUSCLE_VISUAL_DEVFLOW")
    return bool(value and value.strip().lower() in DISABLED_VALUES)


def _relative_reference(project_path: Path, candidate: str | Path | None) -> str | None:
    if candidate is None:
        return None
    text = str(candidate)
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(project_path).as_posix()
    except ValueError:
        return text


def _normalize_files(project_path: Path, files: list[str | Path] | None, mode: str) -> list[dict]:
    if not files:
        return []
    normalized: list[dict] = []
    for file_path in files:
        path = _relative_reference(project_path, file_path)
        if path:
            normalized.append({"path": path, "mode": mode})
    return normalized


def _progress_for_iteration(iteration: Any, max_iterations: int | None) -> int | None:
    try:
        iteration_number = int(iteration)
    except (TypeError, ValueError):
        return None
    if not max_iterations or max_iterations <= 0:
        return None
    return min(94, max(5, int((iteration_number / max_iterations) * 85)))


def _coerce_progress(value: int | float | None) -> int | None:
    if value is None:
        return None
    return min(100, max(0, int(value)))


@dataclass
class VisualDevFlowEmitter:
    """Best-effort HTTP emitter for a running Visual DevFlow dashboard."""

    project_path: Path
    url: str | None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def discover(
        cls,
        project_path: str | Path,
        *,
        url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> VisualDevFlowEmitter:
        """Resolve a Visual DevFlow endpoint from env or project-local state."""

        resolved_project = Path(project_path).resolve()
        if _disabled_by_env():
            return cls(resolved_project, None, timeout_seconds=timeout_seconds)
        resolved_url = _normalize_url(
            url
            or os.environ.get("MUSCLE_VISUAL_DEVFLOW_URL")
            or os.environ.get("VISUAL_DEVFLOW_URL")
            or _project_visual_url(resolved_project)
        )
        return cls(resolved_project, resolved_url, timeout_seconds=timeout_seconds)

    @property
    def enabled(self) -> bool:
        """Return True when a dashboard URL is available."""

        return self.url is not None

    def emit_task(
        self,
        *,
        task_id: str,
        kind: str,
        status: str,
        name: str,
        command: str | None = None,
        progress: int | float | None = None,
        detail: str | None = None,
        path: str | Path | None = None,
        meta: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        """Emit a Visual DevFlow task event, returning False if unavailable."""

        payload: dict[str, Any] = {
            "taskId": task_id,
            "kind": kind,
            "status": status,
            "name": name,
            "meta": {"system": "muscle", **(meta or {})},
        }
        if command:
            payload["command"] = command
        if detail:
            payload["detail"] = _trim(detail)
        if path:
            payload["path"] = _relative_reference(self.project_path, path)
        normalized_progress = _coerce_progress(progress)
        if normalized_progress is not None:
            payload["progress"] = normalized_progress
        if duration_ms is not None:
            payload["durationMs"] = duration_ms
        return self._post("/api/events/task", payload)

    def emit_agent(
        self,
        *,
        agent_id: str,
        name: str,
        action: str,
        status: str = "active",
        files: list[str | Path] | None = None,
        detail: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> bool:
        """Emit a Visual DevFlow agent focus event."""

        payload: dict[str, Any] = {
            "agentId": agent_id,
            "name": name,
            "action": action,
            "status": status,
            "files": _normalize_files(self.project_path, files, action),
            "meta": {"system": "muscle", **(meta or {})},
        }
        if detail:
            payload["detail"] = _trim(detail)
        return self._post("/api/events/agent", payload)

    def _post(self, endpoint: str, payload: dict[str, Any]) -> bool:
        if not self.url:
            return False
        try:
            response = requests.post(
                f"{self.url}{endpoint}",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.debug("Visual DevFlow event emission failed: %s", exc)
            return False


@dataclass
class VisualDevFlowBridge:
    """Maps MUSCLE run/review lifecycle events into Visual DevFlow events."""

    emitter: VisualDevFlowEmitter
    project_path: Path
    run_task: str | None = None
    run_output_dir: str | Path | None = None
    run_max_iterations: int | None = None
    review_target: str | Path | None = None
    review_mode: str | None = None
    review_workflow: str | None = None
    _run_session_id: str | None = field(default=None, init=False)
    _review_session_id: str | None = field(default=None, init=False)

    @classmethod
    def discover(
        cls,
        project_path: str | Path,
        *,
        run_task: str | None = None,
        run_output_dir: str | Path | None = None,
        run_max_iterations: int | None = None,
        review_target: str | Path | None = None,
        review_mode: str | None = None,
        review_workflow: str | None = None,
    ) -> VisualDevFlowBridge:
        """Create a bridge using the dashboard configured for this project."""

        resolved_project = Path(project_path).resolve()
        return cls(
            emitter=VisualDevFlowEmitter.discover(resolved_project),
            project_path=resolved_project,
            run_task=run_task,
            run_output_dir=run_output_dir,
            run_max_iterations=run_max_iterations,
            review_target=review_target,
            review_mode=review_mode,
            review_workflow=review_workflow,
        )

    @property
    def enabled(self) -> bool:
        """Return True when event emission can be attempted."""

        return self.emitter.enabled

    def handle_loop_event(self, event: object, data: dict[str, Any]) -> None:
        """Translate a LoopController event into task/agent dashboard events."""

        if not self.enabled:
            return
        event_name = _event_value(event)
        if event_name == "generation_stream":
            return

        session_id = self._loop_session_id(data)
        task_id = f"muscle-run-{session_id}"
        meta = {
            "event": event_name,
            "session_id": session_id,
            "output_dir": str(self.run_output_dir or ""),
        }
        files = [self.run_output_dir] if self.run_output_dir else None
        progress = _progress_for_iteration(data.get("iteration"), self.run_max_iterations)

        if event_name == "session_start":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-run",
                status="started",
                name="MUSCLE run",
                detail=self.run_task or data.get("task"),
                path=self.run_output_dir,
                progress=1,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-runner",
                name="MUSCLE",
                action="starting",
                files=files,
                detail=f"Session {session_id}",
                meta=meta,
            )
            return

        if event_name == "iteration_start":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-run",
                status="running",
                name=f"MUSCLE iteration {data.get('iteration', '?')}",
                path=self.run_output_dir,
                progress=progress,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-generator",
                name="MUSCLE Generator",
                action="generating",
                files=files,
                meta=meta,
            )
            return

        if event_name in {"generation_start", "generation_end"}:
            status = "running"
            name = (
                "Generate candidate" if event_name == "generation_start" else "Generation complete"
            )
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-run",
                status=status,
                name=name,
                detail=f"tokens={data.get('tokens', 0)}" if data.get("tokens") else None,
                path=self.run_output_dir,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-generator",
                name="MUSCLE Generator",
                action="generating",
                files=files,
                meta=meta,
            )
            return

        if event_name in {"evaluation_start", "evaluation_end"}:
            passed = data.get("passed")
            detail = "passed" if passed else f"errors={data.get('errors', 0)}"
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-evaluation",
                status="running",
                name="Evaluate candidate",
                detail=detail if event_name == "evaluation_end" else None,
                path=self.run_output_dir,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-evaluator",
                name="MUSCLE Evaluator",
                action="evaluating",
                files=files,
                meta=meta,
            )
            return

        if event_name in {"evolution_start", "evolution_end"}:
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-evolution",
                status="running",
                name="Evolve strategy",
                detail=f"tokens={data.get('tokens', 0)}" if data.get("tokens") else None,
                path=self.run_output_dir,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-evolver",
                name="MUSCLE Evolver",
                action="evolving",
                files=files,
                meta=meta,
            )
            return

        if event_name in {"budget_warning", "budget_overspend"}:
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-budget",
                status="running" if event_name == "budget_warning" else "failed",
                name="Budget signal",
                detail=f"tokens={data.get('total_tokens', data.get('tokens', 0))}",
                path=self.run_output_dir,
                meta=meta,
            )
            return

        if event_name in {"session_complete", "session_abort", "iteration_end"}:
            if event_name == "iteration_end":
                status = "running"
                name = "Iteration complete"
                detail = f"success={data.get('success')}"
            else:
                raw_status = str(data.get("status") or event_name)
                status = "succeeded" if raw_status == "success" else "failed"
                name = "MUSCLE run complete"
                detail = data.get("reason") or raw_status
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-run",
                status=status,
                name=name,
                detail=detail,
                path=self.run_output_dir,
                progress=100 if status in {"succeeded", "failed"} else progress,
                meta=meta,
            )
            if status in {"succeeded", "failed"}:
                self.emitter.emit_agent(
                    agent_id="muscle-runner",
                    name="MUSCLE",
                    action="idle",
                    status="idle",
                    files=files,
                    meta=meta,
                )

    def handle_review_event(self, event: object, data: dict[str, Any]) -> None:
        """Translate a ReviewController event into task/agent dashboard events."""

        if not self.enabled:
            return
        event_name = _event_value(event)
        session_id = self._review_session_id_from(data)
        task_id = f"muscle-review-{session_id}"
        event_path = data.get("file") or data.get("path") or self.review_target
        meta = {
            "event": event_name,
            "session_id": session_id,
            "review_mode": self.review_mode or "",
            "workflow_name": self.review_workflow or "",
        }

        if event_name == "review_start":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-review",
                status="started",
                name="MUSCLE review",
                detail=f"mode={self.review_mode or 'review'}",
                path=self.review_target,
                progress=1,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-reviewer",
                name="MUSCLE Reviewer",
                action="reviewing",
                files=[self.review_target] if self.review_target else None,
                detail=f"Session {session_id}",
                meta=meta,
            )
            return

        if event_name == "static_analysis_complete":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-review",
                status="running",
                name="Static analysis complete",
                detail=f"tools={data.get('tools', 0)}",
                path=self.review_target,
                progress=25,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-static-analyzer",
                name="MUSCLE Static Analyzer",
                action="analyzing",
                files=[self.review_target] if self.review_target else None,
                meta=meta,
            )
            return

        if event_name == "semantic_review_complete":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-review",
                status="running",
                name="Semantic review complete",
                detail=f"issues={data.get('issues', 0)}",
                path=self.review_target,
                progress=60,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-semantic-reviewer",
                name="MUSCLE Semantic Reviewer",
                action="reviewing",
                files=[self.review_target] if self.review_target else None,
                meta=meta,
            )
            return

        if event_name == "fix_applied":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-fix",
                status="running",
                name="Fix applied",
                detail=f"{data.get('file', '')}:{data.get('line', '')}",
                path=event_path,
                progress=75,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-fixer",
                name="MUSCLE Fixer",
                action="editing",
                files=[event_path] if event_path else None,
                meta=meta,
            )
            return

        if event_name == "fix_verified":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-verification",
                status="running",
                name="Fix verification complete",
                detail=f"remaining={data.get('remaining_issues', 0)}",
                path=self.review_target,
                progress=86,
                meta=meta,
            )
            self.emitter.emit_agent(
                agent_id="muscle-verifier",
                name="MUSCLE Verifier",
                action="verifying",
                files=[self.review_target] if self.review_target else None,
                meta=meta,
            )
            return

        if event_name == "handoff_generated":
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-review",
                status="running",
                name="Handoff generated",
                detail=f"issues={data.get('count', 0)}",
                path=self.review_target,
                progress=92,
                meta=meta,
            )
            return

        if event_name == "review_complete":
            raw_stats = data.get("stats")
            stats: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else {}
            issue_count = 0
            for name in _SEVERITY_NAMES:
                issue_count += int(stats.get(name, 0) or 0)
            self.emitter.emit_task(
                task_id=task_id,
                kind="muscle-review",
                status="completed",
                name="MUSCLE review complete",
                detail=f"issues={issue_count}",
                path=self.review_target,
                progress=100,
                meta={**meta, "artifact_dir": str(data.get("artifact_dir") or "")},
            )
            self.emitter.emit_agent(
                agent_id="muscle-reviewer",
                name="MUSCLE Reviewer",
                action="idle",
                status="idle",
                files=[self.review_target] if self.review_target else None,
                meta=meta,
            )

    def emit_shadow_review_submitted(
        self,
        *,
        job_id: str,
        target_path: str | Path,
        mode: str,
        workflow_name: str | None,
    ) -> None:
        """Emit a task when a background review job is queued."""

        if not self.enabled:
            return
        self.emitter.emit_task(
            task_id=f"muscle-shadow-{job_id}",
            kind="muscle-review",
            status="started",
            name="MUSCLE shadow review queued",
            detail=f"mode={mode}",
            path=target_path,
            progress=1,
            meta={
                "event": "shadow_review_submitted",
                "job_id": job_id,
                "workflow_name": workflow_name or "",
            },
        )

    def _loop_session_id(self, data: dict[str, Any]) -> str:
        session = data.get("session") or data.get("session_id")
        if session:
            self._run_session_id = str(session)
        if self._run_session_id is None:
            self._run_session_id = "active"
        return self._run_session_id

    def _review_session_id_from(self, data: dict[str, Any]) -> str:
        session = data.get("session") or data.get("session_id")
        if session:
            self._review_session_id = str(session)
        if self._review_session_id is None:
            self._review_session_id = "active"
        return self._review_session_id


_SEVERITY_NAMES = ("critical", "high", "medium", "low", "info")


def find_visual_devflow_command(
    explicit_command: str | None = None,
    *,
    search_from: str | Path | None = None,
) -> str | None:
    """Find the Visual DevFlow control command without installing anything."""

    search_root = Path(search_from or Path.cwd()).resolve()
    if explicit_command is not None:
        return _resolve_command_candidate(explicit_command, search_root)

    candidates = [
        os.environ.get("MUSCLE_VISUAL_DEVFLOW_BIN"),
        os.environ.get("VISUAL_DEVFLOW_BIN"),
        shutil.which("visual-devflow"),
        str(search_root / "bin" / "visual-devflow"),
        str(search_root.parent / "visual-devflow" / "bin" / "visual-devflow"),
        str(Path.home() / "Documents" / "Projects" / "visual-devflow" / "bin" / "visual-devflow"),
    ]
    for candidate in candidates:
        resolved = _resolve_command_candidate(candidate, search_root)
        if resolved:
            return resolved
    return None


def _resolve_command_candidate(candidate: str | None, search_root: Path) -> str | None:
    if not candidate:
        return None
    if os.sep not in candidate and (os.altsep is None or os.altsep not in candidate):
        found = shutil.which(candidate)
        return found
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = search_root / path
    if path.is_file() and os.access(path, os.X_OK):
        return str(path)
    return None


def enable_visual_devflow(
    project_path: str | Path,
    *,
    open_dashboard: bool = True,
    command: str | None = None,
) -> dict[str, Any]:
    """Run Visual DevFlow's shared enable command and return structured status."""

    resolved_project = Path(project_path).resolve()
    visual_command = find_visual_devflow_command(command, search_from=resolved_project)
    if not visual_command:
        return {
            "ok": False,
            "status": "missing-command",
            "projectDir": str(resolved_project),
            "message": (
                "Visual DevFlow command not found. Install it or set "
                "MUSCLE_VISUAL_DEVFLOW_BIN=/path/to/visual-devflow."
            ),
        }

    args = [visual_command, "enable", "--project", str(resolved_project), "--json"]
    if open_dashboard:
        args.append("--open")

    try:
        result = subprocess.run(
            args,
            cwd=resolved_project,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return {
            "ok": False,
            "status": "failed",
            "projectDir": str(resolved_project),
            "command": visual_command,
            "message": str(exc),
        }

    payload = _parse_visual_command_output(result.stdout)
    payload.setdefault("ok", result.returncode == 0)
    payload.setdefault("status", "enabled" if result.returncode == 0 else "failed")
    payload["command"] = visual_command
    payload["projectDir"] = str(payload.get("projectDir") or resolved_project)
    payload["returncode"] = result.returncode
    if result.returncode != 0:
        payload["ok"] = False
        payload["stderr"] = result.stderr.strip()
    return payload


def _parse_visual_command_output(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    match = re.search(r"https?://[^\s]+", text)
    return {"url": match.group(0) if match else None, "output": text}
