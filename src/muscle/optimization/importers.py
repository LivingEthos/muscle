"""
External benchmark importers for MUSCLE.

Imports project-matched Claude and Codex session data into project-local
benchmark tables so MUSCLE can compare itself against long-term agent behavior
without letting that data directly rewrite project memory.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..project_memory import ProjectMemory

logger = logging.getLogger(__name__)


def get_codex_home() -> Path:
    """Return the Codex data directory, honoring CODEX_HOME env var.

    Shared with host_memory_optimizer (future Codex-aware enhancements).
    """
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


@dataclass
class ImportSummary:
    provider: str
    sessions_imported: int = 0
    turns_imported: int = 0
    new_turn_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable summary."""
        return {
            "sessions_imported": self.sessions_imported,
            "turns_imported": self.turns_imported,
            "new_turn_ids": list(self.new_turn_ids),
        }


class ExternalBenchmarkImporter:
    """Import external agent transcript data scoped to one project."""

    def __init__(self, project_memory: ProjectMemory, project_path: str):
        self._pm = project_memory
        self.project_path = str(Path(project_path).resolve())

    def import_sessions(self, provider: str, since_days: int = 30) -> dict[str, dict[str, int]]:
        """Import Claude and/or Codex sessions tied to this project."""
        detailed = self.import_sessions_with_deltas(provider=provider, since_days=since_days)
        return {
            provider_name: {
                "sessions_imported": int(summary.get("sessions_imported", 0) or 0),
                "turns_imported": int(summary.get("turns_imported", 0) or 0),
            }
            for provider_name, summary in detailed.items()
        }

    def import_sessions_with_deltas(
        self,
        provider: str,
        since_days: int = 30,
    ) -> dict[str, dict[str, Any]]:
        """Import sessions and return per-provider delta information."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, since_days))
        summaries: dict[str, dict[str, Any]] = {}
        providers = ["claude", "codex"] if provider == "all" else [provider]
        for provider_name in providers:
            if provider_name == "claude":
                summary = self._import_claude(cutoff)
            elif provider_name == "codex":
                summary = self._import_codex(cutoff)
            else:
                continue
            summaries[provider_name] = summary.as_dict()
        return summaries

    def _import_codex(self, cutoff: datetime) -> ImportSummary:
        codex_home = get_codex_home()
        sessions_dir = codex_home / "sessions"
        summary = ImportSummary(provider="codex")
        if not sessions_dir.exists():
            return summary

        for file_path in sorted(sessions_dir.rglob("rollout-*.jsonl")):
            if not file_path.is_file():
                continue
            if datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc) < cutoff:
                continue
            imported = self._import_codex_file(file_path)
            if imported["session_imported"]:
                summary.sessions_imported += 1
            summary.turns_imported += imported["turns_imported"]
            summary.new_turn_ids.extend(imported.get("new_turn_ids", []))
        return summary

    def _import_codex_file(self, file_path: Path) -> dict[str, Any]:
        try:
            lines = [
                json.loads(line)
                for line in file_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read Codex benchmark file %s", file_path, exc_info=True)
            return {"session_imported": 0, "turns_imported": 0}

        session_meta = next((line for line in lines if line.get("type") == "session_meta"), None)
        payload = session_meta.get("payload", {}) if isinstance(session_meta, dict) else {}
        session_timestamp = ""
        if isinstance(session_meta, dict):
            session_timestamp = str(session_meta.get("timestamp") or "")
        cwd = str(payload.get("cwd") or "")
        if not self._matches_project(cwd):
            return {"session_imported": 0, "turns_imported": 0}

        external_session_id = str(payload.get("session_id") or file_path.stem)
        session_row_id = self._pm.upsert_external_benchmark_session(
            project_path=self.project_path,
            provider="codex",
            external_session_id=external_session_id,
            source_path=str(file_path),
            project_hint=cwd,
            normalized_project_path=self.project_path,
            started_at=session_timestamp,
            ended_at=str(lines[-1].get("timestamp") or "") if lines else None,
            metadata_json=json.dumps(
                {"originator": payload.get("originator"), "model": payload.get("model")}
            ),
        )

        pending_tools: list[str] = []
        pending_user_text = ""
        turns_imported = 0
        new_turn_ids: list[int] = []
        for entry in lines:
            payload = entry.get("payload", {})
            if entry.get("type") == "response_item" and payload.get("type") == "function_call":
                pending_tools.append(self._normalize_codex_tool(str(payload.get("name") or "")))
                continue
            if (
                entry.get("type") == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") == "user"
            ):
                texts = [
                    str(block.get("text") or "")
                    for block in payload.get("content", [])
                    if isinstance(block, dict) and block.get("type") == "input_text"
                ]
                pending_user_text = " ".join(part for part in texts if part).strip()
                continue
            if entry.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue

            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            last_usage = info.get("last_token_usage")
            if not isinstance(last_usage, dict):
                continue
            input_tokens = int(last_usage.get("input_tokens", 0) or 0)
            cached_tokens = int(last_usage.get("cached_input_tokens", 0) or 0)
            output_tokens = int(last_usage.get("output_tokens", 0) or 0)
            reasoning_tokens = int(last_usage.get("reasoning_output_tokens", 0) or 0)
            total_tokens = max(0, input_tokens + output_tokens + reasoning_tokens)
            timestamp = str(entry.get("timestamp") or "")
            category = self._classify_turn(pending_user_text, pending_tools)
            retry_count = self._retry_count(pending_tools)
            dedup_key = f"codex:{external_session_id}:{timestamp}:{total_tokens}:{retry_count}"

            inserted = self._pm.insert_external_benchmark_turn(
                benchmark_session_id=session_row_id,
                timestamp=timestamp,
                category=category,
                model=str(info.get("model") or payload.get("model") or "unknown"),
                input_tokens=max(0, input_tokens - cached_tokens),
                output_tokens=output_tokens,
                cache_tokens=cached_tokens,
                reasoning_tokens=reasoning_tokens,
                retry_count=retry_count,
                success_signal=retry_count == 0 and total_tokens > 0,
                token_cost=total_tokens,
                tool_names_json=json.dumps(pending_tools),
                metadata_json=json.dumps({"user_message": pending_user_text}),
                dedup_key=dedup_key,
            )
            if inserted:
                turns_imported += 1
                new_turn_ids.append(inserted)
            pending_tools = []
        return {
            "session_imported": 1,
            "turns_imported": turns_imported,
            "new_turn_ids": new_turn_ids,
        }

    def _import_claude(self, cutoff: datetime) -> ImportSummary:
        claude_root = Path(
            os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")
        ).expanduser()
        project_dir = claude_root / "projects" / self._sanitize_project_path(self.project_path)
        summary = ImportSummary(provider="claude")
        if not project_dir.exists():
            return summary

        for file_path in sorted(project_dir.glob("*.jsonl")):
            if datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc) < cutoff:
                continue
            imported = self._import_claude_file(file_path)
            if imported["session_imported"]:
                summary.sessions_imported += 1
            summary.turns_imported += imported["turns_imported"]
            summary.new_turn_ids.extend(imported.get("new_turn_ids", []))
        return summary

    def _import_claude_file(self, file_path: Path) -> dict[str, Any]:
        try:
            entries = [
                json.loads(line)
                for line in file_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read Claude benchmark file %s", file_path, exc_info=True)
            return {"session_imported": 0, "turns_imported": 0}

        session_id = file_path.stem
        session_row_id = self._pm.upsert_external_benchmark_session(
            project_path=self.project_path,
            provider="claude",
            external_session_id=session_id,
            source_path=str(file_path),
            normalized_project_path=self.project_path,
            started_at=str(entries[0].get("timestamp") or "") if entries else None,
            ended_at=str(entries[-1].get("timestamp") or "") if entries else None,
            metadata_json=json.dumps({"entry_count": len(entries)}),
        )

        pending_user_message = ""
        turns_imported = 0
        new_turn_ids: list[int] = []
        for entry in entries:
            if entry.get("type") == "user":
                pending_user_message = self._extract_user_text(entry)
                continue
            if entry.get("type") != "assistant":
                continue

            message = entry.get("message", {})
            usage = message.get("usage", {})
            content = message.get("content", [])
            tool_names = [
                str(block.get("name") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            cache_tokens = int(usage.get("cache_read_input_tokens", 0) or 0) + int(
                usage.get("cache_creation_input_tokens", 0) or 0
            )
            timestamp = str(entry.get("timestamp") or "")
            retry_count = self._retry_count(tool_names)
            dedup_key = f"claude:{session_id}:{timestamp}:{message.get('id', '')}"
            inserted = self._pm.insert_external_benchmark_turn(
                benchmark_session_id=session_row_id,
                timestamp=timestamp,
                category=self._classify_turn(pending_user_message, tool_names),
                model=str(message.get("model") or "unknown"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_tokens=cache_tokens,
                reasoning_tokens=0,
                retry_count=retry_count,
                success_signal=retry_count == 0 and output_tokens > 0,
                token_cost=input_tokens + output_tokens,
                tool_names_json=json.dumps(tool_names),
                metadata_json=json.dumps({"user_message": pending_user_message}),
                dedup_key=dedup_key,
            )
            if inserted:
                turns_imported += 1
                new_turn_ids.append(inserted)
        return {
            "session_imported": 1,
            "turns_imported": turns_imported,
            "new_turn_ids": new_turn_ids,
        }

    def _matches_project(self, external_cwd: str) -> bool:
        if not external_cwd:
            return False
        try:
            external_path = Path(external_cwd).resolve()
            project_path = Path(self.project_path)
            return external_path == project_path or project_path in external_path.parents
        except OSError:
            return False

    @staticmethod
    def _sanitize_project_path(project_path: str) -> str:
        return project_path.strip("/").replace("/", "-")

    @staticmethod
    def _normalize_codex_tool(raw_name: str) -> str:
        if raw_name in {"apply_patch", "apply_diff", "write_file"}:
            return "edit"
        if raw_name in {"read_file", "read_dir"}:
            return "read"
        if raw_name == "exec_command":
            return "bash"
        if "agent" in raw_name:
            return "agent"
        return raw_name or "tool"

    @staticmethod
    def _retry_count(tool_names: list[str]) -> int:
        edit_seen = False
        verify_seen = False
        retries = 0
        for tool_name in tool_names:
            is_edit = tool_name in {"edit", "apply_patch", "write"}
            is_verify = tool_name in {"bash", "test", "lint", "read"}
            if is_edit:
                if verify_seen:
                    retries += 1
                edit_seen = True
                verify_seen = False
            elif is_verify and edit_seen:
                verify_seen = True
        return retries

    @staticmethod
    def _classify_turn(user_message: str, tool_names: list[str]) -> str:
        lowered = user_message.lower()
        if any(tool in {"edit", "apply_patch", "write"} for tool in tool_names):
            if "fix" in lowered or "bug" in lowered or "error" in lowered:
                return "repair"
            return "code"
        if any(tool in {"bash", "test", "lint"} for tool in tool_names):
            return "verify"
        if "plan" in lowered or "approach" in lowered:
            return "planning"
        if "search" in lowered or "why" in lowered or "understand" in lowered:
            return "analysis"
        if any(tool == "agent" for tool in tool_names):
            return "delegation"
        return "general"

    @staticmethod
    def _extract_user_text(entry: dict[str, Any]) -> str:
        message = entry.get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return " ".join(part for part in parts if part).strip()
        return ""
