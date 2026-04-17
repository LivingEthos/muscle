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
import string
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.muscle.project_memory import ProjectMemory

from .types import (
    BudgetInfo,
    BudgetMode,
    CodeArtifact,
    EvalMode,
    IterationReport,
    IterationResult,
    LoopStats,
    RunConfig,
    SessionReport,
    SessionStatus,
)

if TYPE_CHECKING:
    from .loop_controller import LoopContext

from .io_safety import atomic_write_json, locked_jsonl_append, update_json_file_locked

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
        safe_id = "".join(
            c for c in session_id.strip() if c in string.ascii_letters + string.digits + "_-"
        )
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
            "working_dir": str(Path.cwd()),
            "max_iterations": config.max_iterations,
            "timeout_seconds": config.timeout_seconds,
            "budget_tokens": config.budget_tokens,
            "budget_mode": config.budget_mode.value,
            "eval_mode": config.eval_mode.value,
            "allow_warnings": config.allow_warnings,
            "interactive": config.interactive,
            "kb_path": config.kb_path,
            "max_cost_per_iteration": config.max_cost_per_iteration,
            "early_exit_on": config.early_exit_on,
            "created_at": datetime.now().isoformat(),
            "status": SessionStatus.RUNNING.value,
        }

        try:
            meta_file = session_dir / "meta.json"
            atomic_write_json(meta_file, meta, ensure_ascii=False, indent=2)
            (session_dir / "iterations.jsonl").touch()
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

        iterations_file = session_dir / "iterations.jsonl"
        safe_errors = [str(e)[:500] for e in (iteration.errors or [])]
        safe_warnings = [str(w)[:500] for w in (iteration.warnings or [])]

        iteration_entry = json.dumps(
            {
                "iteration": iteration.iteration,
                "success": iteration.success,
                "errors": safe_errors,
                "warnings": safe_warnings,
                "token_cost": iteration.token_cost,
                "duration_seconds": iteration.duration_seconds,
                "evolved_strategy": (iteration.evolved_strategy or "")[:1000],
            },
            ensure_ascii=False,
        )

        try:
            locked_jsonl_append(iterations_file, iteration_entry + "\n")
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
            atomic_write_json(context_file, context_data, ensure_ascii=False, indent=2)
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
            atomic_write_json(report_file, report_data, ensure_ascii=False, indent=2)
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
            update_json_file_locked(
                meta_file,
                lambda meta: {**meta, **updates},
                ensure_ascii=False,
                indent=2,
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot update meta file: {e}")

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

    def _load_dict_file(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cannot load JSON from {path}: {e}")
            return None
        if isinstance(data, dict):
            return data
        return None

    def _parse_budget_mode(self, value: str | None) -> BudgetMode:
        for mode in BudgetMode:
            if mode.value == value:
                return mode
        return BudgetMode.UNLIMITED

    def _parse_eval_mode(self, value: str | None) -> EvalMode:
        for mode in EvalMode:
            if mode.value == value:
                return mode
        return EvalMode.ALL

    def _resolve_output_dir(self, meta: dict) -> str:
        output_dir = str(meta.get("output_dir") or ".")
        working_dir = Path(str(meta.get("working_dir") or Path.cwd()))
        output_path = Path(output_dir)
        if not output_path.is_absolute():
            output_path = working_dir / output_path
        return str(output_path.resolve())

    def load_iterations(self, session_id: str) -> list[IterationResult]:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return []

        iterations_file = self.base_dir / session_id / "iterations.jsonl"
        if not iterations_file.exists():
            return []

        iterations: list[IterationResult] = []
        try:
            for line in iterations_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping invalid iteration entry for {session_id}: {e}")
                    continue
                if not isinstance(entry, dict):
                    continue
                iterations.append(
                    IterationResult(
                        iteration=int(entry.get("iteration", len(iterations) + 1)),
                        success=bool(entry.get("success", False)),
                        errors=[str(err) for err in entry.get("errors", [])],
                        warnings=[str(warn) for warn in entry.get("warnings", [])],
                        token_cost=int(entry.get("token_cost", 0)),
                        duration_seconds=float(entry.get("duration_seconds", 0.0)),
                        evolved_strategy=entry.get("evolved_strategy") or None,
                    )
                )
        except OSError as e:
            logger.warning(f"Cannot read iterations for {session_id}: {e}")
            return []

        return iterations

    def load_resume_context(self, session_id: str) -> LoopContext | None:
        from .loop_controller import LoopContext

        meta = self.load_session(session_id)
        if not meta:
            return None

        iterations = self.load_iterations(session_id)
        report_data = self._load_dict_file(self.base_dir / session_id / "report.json") or {}
        context_data = self._load_dict_file(self.base_dir / session_id / "context.json") or {}

        current_iteration = max(
            int(meta.get("last_iteration", 0)),
            max((iteration.iteration for iteration in iterations), default=0),
            int(meta.get("total_iterations", 0)),
        )
        total_tokens = int(
            meta.get("total_tokens")
            or report_data.get("total_tokens")
            or sum(iteration.token_cost for iteration in iterations)
        )
        total_duration_seconds = float(
            meta.get("total_duration_seconds")
            or report_data.get("total_duration_seconds")
            or sum(iteration.duration_seconds for iteration in iterations)
        )

        budget_tokens = meta.get("budget_tokens")
        if budget_tokens is None:
            budget_info = report_data.get("budget_info")
            if isinstance(budget_info, dict):
                budget_tokens = budget_info.get("limit", 0)

        stored_max_iterations = int(meta.get("max_iterations", 20))
        effective_max_iterations = stored_max_iterations
        if current_iteration >= stored_max_iterations:
            effective_max_iterations = current_iteration + max(1, stored_max_iterations)

        evolved_strategy = context_data.get("evolved_strategy")
        if not evolved_strategy:
            evolved_strategy = next(
                (
                    iteration.evolved_strategy
                    for iteration in reversed(iterations)
                    if iteration.evolved_strategy
                ),
                None,
            )

        config = RunConfig(
            task=str(meta.get("task") or "untitled"),
            language=meta.get("language"),
            output_dir=self._resolve_output_dir(meta),
            max_iterations=effective_max_iterations,
            timeout_seconds=int(meta.get("timeout_seconds", 3600)),
            budget_tokens=int(budget_tokens or 0),
            budget_mode=self._parse_budget_mode(meta.get("budget_mode")),
            eval_mode=self._parse_eval_mode(meta.get("eval_mode")),
            allow_warnings=bool(meta.get("allow_warnings", False)),
            interactive=bool(meta.get("interactive", False)),
            kb_path=meta.get("kb_path"),
            max_cost_per_iteration=meta.get("max_cost_per_iteration"),
            early_exit_on=meta.get("early_exit_on"),
        )

        return LoopContext(
            session_id=session_id,
            config=config,
            stats=LoopStats(
                total_iterations=current_iteration,
                total_tokens=total_tokens,
                total_duration_seconds=total_duration_seconds,
                status=SessionStatus.RUNNING,
            ),
            evolved_strategy=evolved_strategy,
            iterations=iterations,
            current_iteration=current_iteration,
        )

    def mark_resumed(self, session_id: str) -> None:
        meta = self.load_session(session_id)
        if not meta:
            return

        resume_count = int(meta.get("resume_count", 0)) + 1
        self._update_meta(
            session_id,
            {
                "status": SessionStatus.RUNNING.value,
                "resume_count": resume_count,
                "resumed_at": datetime.now().isoformat(),
            },
        )

    def load_evolved_strategy(self, session_id: str) -> str | None:
        try:
            session_id = self._sanitize_session_id(session_id)
        except ValueError:
            return None

        context_file = self.base_dir / session_id / "context.json"
        ctx = self._load_dict_file(context_file)
        if isinstance(ctx, dict) and "evolved_strategy" in ctx:
            return ctx.get("evolved_strategy")
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


# -----------------------------------------------------------------------------
# Legacy import (MUS-012)
# -----------------------------------------------------------------------------


def import_from_project_memory(project_memory: ProjectMemory, project_path: str) -> dict:
    """
    Import session data from legacy .muscle/sessions/ into ProjectMemory.

    This is a convenience wrapper that runs only the sessions import step
    of LegacyImporter.

    Returns
    -------
    dict
        Import stats dict with keys: imported, skipped, errors.
    """
    from tools.muscle.legacy_importer import LegacyImporter

    importer = LegacyImporter(project_memory, project_path)
    importer._import_sessions()
    return importer.stats.get("sessions", {"imported": 0, "skipped": 0, "errors": 0})
