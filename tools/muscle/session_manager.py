"""
Session Manager - Handles persistence and concurrency.

Architecture Decision Record (ADR):
- Sessions stored in .muscle/sessions/<session_id>/
- Each iteration snapshot saved for debugging and resume
- Concurrent sessions supported via session IDs
- Graceful handling of interrupted sessions
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .types import (
    BudgetInfo,
    CodeArtifact,
    IterationReport,
    IterationResult,
    RunConfig,
    SessionReport,
    SessionStatus,
)

if TYPE_CHECKING:
    from .loop_controller import LoopContext

logger = logging.getLogger(__name__)

DEFAULT_SESSION_DIR = ".muscle/sessions"


class SessionManager:
    def __init__(self, base_dir: str = DEFAULT_SESSION_DIR):
        self.base_dir = Path(base_dir)
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Cannot create session directory: {e}")
            raise

    def _sanitize_session_id(self, session_id: str) -> str:
        safe_id = "".join(c for c in session_id if c.isalnum() or c in "_-")
        if not safe_id or safe_id.startswith("."):
            raise ValueError(f"Invalid session ID: {session_id}")
        return safe_id

    def create_session(self, config: RunConfig) -> str:
        safe_task = config.task[:100] if config.task else "untitled"
        safe_task = "".join(c for c in safe_task if c.isprintable())
        task_slug = safe_task[:20].replace(" ", "_").replace("/", "_").replace("\\", "_")
        base_session_id = self._sanitize_session_id(
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{task_slug}"
        )
        session_id = base_session_id

        try:
            session_dir = self.base_dir / session_id
            suffix = 2
            while session_dir.exists():
                session_id = self._sanitize_session_id(f"{base_session_id}_{suffix}")
                session_dir = self.base_dir / session_id
                suffix += 1
            session_dir.mkdir(parents=True, exist_ok=False)
        except OSError as e:
            logger.error(f"Cannot create session directory: {e}")
            raise

        meta = {
            "session_id": session_id,
            "task": config.task[:500] if config.task else "untitled",
            "language": config.language,
            "output_dir": config.output_dir,
            "max_iterations": config.max_iterations,
            "timeout_seconds": config.timeout_seconds,
            "budget_mode": config.budget_mode.value,
            "eval_mode": config.eval_mode.value,
            "created_at": datetime.now().isoformat(),
            "status": SessionStatus.RUNNING.value,
        }

        try:
            meta_file = session_dir / "meta.json"
            meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            (session_dir / "iterations.json").write_text("[]", encoding="utf-8")
            (session_dir / "artifacts").mkdir(exist_ok=True)
        except OSError as e:
            logger.error(f"Cannot write session files: {e}")
            raise

        logger.info(f"Created session {session_id} at {session_dir}")
        return session_id

    def save_iteration(self, session_id: str, iteration: IterationResult) -> None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError as e:
            logger.warning(f"Invalid session ID: {e}")
            return

        session_dir = self.base_dir / session_id
        if not session_dir.exists():
            logger.warning(f"Session {session_id} not found")
            return

        iterations_file = session_dir / "iterations.json"
        try:
            iterations = json.loads(iterations_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot read iterations file: {e}, starting fresh")
            iterations = []

        safe_errors = [str(e)[:500] for e in (iteration.errors or [])]
        safe_warnings = [str(w)[:500] for w in (iteration.warnings or [])]

        iterations.append(
            {
                "iteration": iteration.iteration,
                "success": iteration.success,
                "errors": safe_errors,
                "warnings": safe_warnings,
                "token_cost": iteration.token_cost,
                "duration_seconds": iteration.duration_seconds,
                "evolved_strategy": (iteration.evolved_strategy or "")[:1000],
            }
        )

        try:
            iterations_file.write_text(
                json.dumps(iterations, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as e:
            logger.error(f"Cannot write iterations file: {e}")

        if iteration.artifacts_dir:
            try:
                dest = session_dir / "artifacts" / f"iteration_{iteration.iteration:03d}"
                artifacts_path = Path(iteration.artifacts_dir)
                if artifacts_path.exists():
                    shutil.copytree(artifacts_path, dest, dirs_exist_ok=True)
            except OSError as e:
                logger.warning(f"Cannot copy artifacts: {e}")

        self._update_meta(session_id, {"last_iteration": iteration.iteration})

    def save_final_context(self, ctx: LoopContext) -> None:
        try:
            session_id = self._sanitize_session_id(ctx.session_id)
        except ValueError as e:
            logger.warning(f"Invalid session ID: {e}")
            return

        session_dir = self.base_dir / session_id
        if not session_dir.exists():
            return

        self._update_meta(
            session_id,
            {
                "status": ctx.stats.status.value,
                "total_iterations": ctx.stats.total_iterations,
                "total_tokens": ctx.stats.total_tokens,
                "total_duration_seconds": ctx.stats.total_duration_seconds,
                "completed_at": datetime.now().isoformat(),
            },
        )

        context_file = session_dir / "context.json"
        context_data = {
            "session_id": ctx.session_id,
            "task": (ctx.config.task or "")[:500],
            "evolved_strategy": (ctx.evolved_strategy or "")[:1000],
            "iterations_count": len(ctx.iterations),
        }
        try:
            context_file.write_text(
                json.dumps(context_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as e:
            logger.error(f"Cannot write context file: {e}")

    def save_session_report(self, session_id: str, report: SessionReport) -> None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError as e:
            logger.warning(f"Invalid session ID: {e}")
            return

        session_dir = self.base_dir / session_id
        if not session_dir.exists():
            logger.warning(f"Session {session_id} not found")
            return

        def safe_dict(d: dict) -> dict:
            return {k: v for k, v in d.items() if k is not None}

        def iter_report_to_dict(ir: IterationReport) -> dict:
            return safe_dict(
                {
                    "iteration": ir.iteration,
                    "success": ir.success,
                    "errors": [str(e)[:500] for e in (ir.errors or [])],
                    "warnings": [str(w)[:500] for w in (ir.warnings or [])],
                    "token_cost": ir.token_cost,
                    "duration_seconds": ir.duration_seconds,
                    "files_generated": [str(f)[:255] for f in (ir.files_generated or [])],
                    "evolved_strategy": (ir.evolved_strategy or "")[:1000],
                }
            )

        def budget_info_to_dict(bi: BudgetInfo | None) -> dict | None:
            if bi is None:
                return None
            return safe_dict(
                {
                    "mode": bi.mode.value if bi.mode else "unknown",
                    "limit": bi.limit,
                    "spent": bi.spent,
                    "remaining": bi.remaining,
                    "percentage": bi.percentage,
                }
            )

        def artifact_to_dict(artifact: CodeArtifact) -> dict:
            return safe_dict(
                {
                    "file_path": (artifact.file_path or "")[:255],
                    "content_hash": (artifact.content_hash or "")[:64],
                    "language": (artifact.language or "")[:50],
                    "lines": artifact.lines,
                }
            )

        report_data = safe_dict(
            {
                "session_id": report.session_id,
                "task": (report.task or "")[:500],
                "status": report.status.value if report.status else "unknown",
                "total_iterations": report.total_iterations,
                "total_tokens": report.total_tokens,
                "total_duration_seconds": report.total_duration_seconds,
                "iterations": [iter_report_to_dict(ir) for ir in (report.iterations or [])],
                "final_strategy": (report.final_strategy or "")[:1000],
                "artifacts": [artifact_to_dict(a) for a in (report.artifacts or [])],
                "budget_info": budget_info_to_dict(report.budget_info),
                "git_commit": (report.git_commit or "")[:64],
            }
        )

        try:
            report_file = session_dir / "report.json"
            report_file.write_text(
                json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info(f"Saved session report to {report_file}")
        except OSError as e:
            logger.error(f"Cannot write report file: {e}")

    def _update_meta(self, session_id: str, updates: dict) -> None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return

        session_dir = self.base_dir / session_id
        meta_file = session_dir / "meta.json"
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot read meta file: {e}")
            return

        meta.update(updates)
        try:
            meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.error(f"Cannot write meta file: {e}")

    def list_sessions(self) -> list[dict]:
        sessions = []
        try:
            for session_dir in sorted(self.base_dir.iterdir(), reverse=True):
                if session_dir.is_dir():
                    meta_file = session_dir / "meta.json"
                    if meta_file.exists():
                        try:
                            sessions.append(json.loads(meta_file.read_text(encoding="utf-8")))
                        except (json.JSONDecodeError, OSError) as e:
                            logger.warning(f"Cannot read session {session_dir.name}: {e}")
        except OSError as e:
            logger.error(f"Cannot list sessions: {e}")
        return sessions

    def load_session(self, session_id: str) -> dict | None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return None

        session_dir = self.base_dir / session_id
        meta_file = session_dir / "meta.json"
        if not meta_file.exists():
            return None
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot load session {session_id}: {e}")
            return None

    def load_evolved_strategy(self, session_id: str) -> str | None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return None

        context_file = self.base_dir / session_id / "context.json"
        if not context_file.exists():
            return None
        try:
            ctx = json.loads(context_file.read_text(encoding="utf-8"))
            if isinstance(ctx, dict) and "evolved_strategy" in ctx:
                return ctx.get("evolved_strategy")
            return None
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot load evolved strategy for {session_id}: {e}")
            return None

    def delete_session(self, session_id: str) -> bool:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return False

        session_dir = self.base_dir / session_id
        if session_dir.exists():
            try:
                shutil.rmtree(session_dir)
                logger.info(f"Deleted session {session_id}")
                return True
            except OSError as e:
                logger.error(f"Cannot delete session {session_id}: {e}")
        return False

    def get_session_artifacts(self, session_id: str) -> Path | None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return None

        artifacts_dir = self.base_dir / session_id / "artifacts"
        return artifacts_dir if artifacts_dir.exists() else None
