"""
Foresight preflight workflow.

Architecture Decision Record (ADR):
- Keep foresight explicit and opt-in; normal review/run paths do not call it.
- Treat project_memory.db as the authoritative long-term source, opened read-only.
- Write only bounded short-term generated state under `.muscle/` and never
  mutate learned memory, host files, model packs, or promotion rules.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

SHORT_TERM_FILENAME = "MUSCLE_SHORT_TERM.md"
SHORT_TERM_MAX_CHARS = 8000
TASK_MAX_CHARS = 2000
TARGET_SAMPLE_LIMIT = 8

FORESIGHT_GUARDRAILS = [
    "Foresight is opt-in only; normal `muscle run` and `muscle review` paths do not call it.",
    "No network access or credentials are required.",
    "Project memory remains authoritative in `.muscle/project_memory.db`.",
    "The only generated file is `.muscle/MUSCLE_SHORT_TERM.md`.",
    "Do not mutate CLAUDE.md, AGENTS.md, MEMORY.md, model packs, or learned rules.",
    "Promotion into durable memory requires a later explicit, benchmarked flow.",
]


def build_foresight_report(
    project_path: str | Path,
    task: str,
    *,
    target_path: str | Path | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Build a bounded project-local foresight preflight report.

    Args:
        project_path: Project root used for `.muscle/` state.
        task: User-supplied task or change description.
        target_path: Optional task target. Defaults to the project root.
        write: Whether to persist `.muscle/MUSCLE_SHORT_TERM.md` when possible.

    Returns:
        Structured report suitable for CLI JSON output.
    """

    resolved_project = Path(project_path).resolve()
    resolved_target = Path(target_path).resolve() if target_path is not None else resolved_project
    normalized_task = _truncate_text(task.strip() or "Unspecified task", TASK_MAX_CHARS)
    generated_at = _now_iso()

    memory = _read_project_memory_summary(resolved_project)
    target = _inspect_target(resolved_project, resolved_target)
    preflight = _build_preflight_actions(normalized_task, target, memory)
    content = _render_short_term_markdown(
        project_path=resolved_project,
        task=normalized_task,
        target=target,
        memory=memory,
        preflight=preflight,
        generated_at=generated_at,
    )

    muscle_dir = resolved_project / ".muscle"
    short_term_path = muscle_dir / SHORT_TERM_FILENAME
    warnings: list[str] = []
    short_term_written = False

    if write and memory["muscle_dir_exists"]:
        short_term_path.write_text(content, encoding="utf-8")
        status = "written"
        short_term_written = True
    elif write:
        status = "not-initialized"
        warnings.append(
            "No `.muscle/` directory found; generated preflight was not persisted. "
            "Run `muscle init` first to enable project-local state."
        )
    else:
        status = "preview"

    return {
        "ok": True,
        "status": status,
        "project_path": str(resolved_project),
        "task": normalized_task,
        "target": target,
        "memory": memory,
        "preflight": preflight,
        "guardrails": FORESIGHT_GUARDRAILS,
        "short_term_path": str(short_term_path),
        "short_term_written": short_term_written,
        "short_term_max_chars": SHORT_TERM_MAX_CHARS,
        "content_chars": len(content),
        "generated_at": generated_at,
        "warnings": warnings,
        "network_required": False,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    suffix = "\n[truncated]"
    return value[: max(0, limit - len(suffix))].rstrip() + suffix


def _read_project_memory_summary(project_path: Path) -> dict[str, Any]:
    muscle_dir = project_path / ".muscle"
    db_path = muscle_dir / "project_memory.db"
    summary: dict[str, Any] = {
        "muscle_dir_exists": muscle_dir.is_dir(),
        "project_memory_db_exists": db_path.exists(),
        "status": "missing-db",
        "schema_version": None,
        "counts": {},
        "latest_review": None,
        "error": None,
    }
    if not db_path.exists():
        summary["status"] = "missing-muscle-dir" if not muscle_dir.exists() else "missing-db"
        return summary

    db_uri = f"file:{quote(str(db_path.resolve()))}?mode=ro"
    try:
        conn = sqlite3.connect(db_uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            summary["schema_version"] = _query_schema_version(conn)
            summary["counts"] = _query_project_counts(conn, str(project_path))
            summary["latest_review"] = _query_latest_review(conn, str(project_path))
            summary["status"] = "available"
        finally:
            conn.close()
    except sqlite3.Error as exc:
        summary["status"] = "unreadable"
        summary["error"] = str(exc)
    return summary


def _query_schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row and row[0] is not None else None


def _query_project_counts(conn: sqlite3.Connection, project_path: str) -> dict[str, int]:
    table_map = {
        "tasks": "tasks",
        "review_runs": "review_runs",
        "learned_rules": "learned_rules",
        "skills": "skills",
        "agents": "agents",
        "optimization_decisions": "optimization_decisions",
    }
    counts: dict[str, int] = {}
    for key, table in table_map.items():
        try:
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_path = ?",  # noqa: S608
                (project_path,),
            )
            row = cursor.fetchone()
            counts[key] = int(row[0]) if row else 0
        except sqlite3.Error:
            counts[key] = 0
    return counts


def _query_latest_review(conn: sqlite3.Connection, project_path: str) -> dict[str, Any] | None:
    try:
        cursor = conn.execute(
            """
            SELECT id, created_at, review_mode, target_path, findings_count, token_cost
            FROM review_runs
            WHERE project_path = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (project_path,),
        )
        row = cursor.fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _inspect_target(project_path: Path, target_path: Path) -> dict[str, Any]:
    exists = target_path.exists()
    target: dict[str, Any] = {
        "path": str(target_path),
        "display_path": _display_path(project_path, target_path),
        "exists": exists,
        "kind": "missing",
        "sample_entries": [],
    }
    if not exists:
        return target
    if target_path.is_file():
        target["kind"] = "file"
        target["suffix"] = target_path.suffix
        target["size_bytes"] = target_path.stat().st_size
        return target
    if target_path.is_dir():
        target["kind"] = "directory"
        target["sample_entries"] = _sample_directory_entries(project_path, target_path)
        return target
    target["kind"] = "other"
    return target


def _sample_directory_entries(project_path: Path, target_path: Path) -> list[str]:
    ignored = {".git", ".muscle", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv"}
    entries: list[str] = []
    try:
        children = sorted(target_path.iterdir(), key=lambda child: child.name.lower())
    except OSError:
        return entries
    for child in children:
        if child.name in ignored:
            continue
        entries.append(_display_path(project_path, child))
        if len(entries) >= TARGET_SAMPLE_LIMIT:
            break
    return entries


def _display_path(project_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_path.resolve())) or "."
    except (OSError, ValueError):
        return str(path)


def _build_preflight_actions(
    task: str,
    target: dict[str, Any],
    memory: dict[str, Any],
) -> list[str]:
    actions = [
        "Restate the task scope and expected output before editing.",
        "Inspect the current git diff for every file before changing it.",
        "Prefer existing MUSCLE helpers and project-local state over new subsystems.",
    ]

    if target["exists"]:
        actions.append(f"Start with target `{target['display_path']}` ({target['kind']}).")
    else:
        actions.append(f"Resolve missing target `{target['display_path']}` before implementation.")

    if memory["project_memory_db_exists"]:
        actions.append(
            "Use `.muscle/project_memory.db` as read-only context for prior project state."
        )
    else:
        actions.append(
            "Proceed without durable memory context; do not create learned memory implicitly."
        )

    lowered_task = task.lower()
    if "test" in lowered_task or "gate" in lowered_task or "release" in lowered_task:
        actions.append("Define the smallest targeted verification command before full gates.")
    if "plugin" in lowered_task or "command" in lowered_task:
        actions.append("Keep CLI behavior, plugin command docs, and manifest parity aligned.")

    actions.extend(
        [
            "Keep generated short-term state bounded and project-local.",
            "Do not promote observations into long-term memory without a later benchmarked flow.",
        ]
    )
    return actions[:8]


def _render_short_term_markdown(
    *,
    project_path: Path,
    task: str,
    target: dict[str, Any],
    memory: dict[str, Any],
    preflight: list[str],
    generated_at: str,
) -> str:
    latest_review = memory.get("latest_review") or {}
    counts = memory.get("counts") or {}
    lines = [
        "# MUSCLE Short-Term Foresight",
        "",
        f"Generated: `{generated_at}`",
        f"Project: `{project_path}`",
        "",
        (
            "This file is generated short-term project-local state. It is not "
            "authoritative memory. Authoritative long-term state remains "
            "`.muscle/project_memory.db`."
        ),
        "",
        (
            "Do not promote this content into CLAUDE.md, AGENTS.md, MEMORY.md, "
            "model packs, or learned rules without an explicit benchmarked "
            "promotion flow."
        ),
        "",
        "## Task",
        "",
        task,
        "",
        "## Target",
        "",
        f"- Path: `{target['display_path']}`",
        f"- Kind: `{target['kind']}`",
        f"- Exists: `{'yes' if target['exists'] else 'no'}`",
        "",
        "## Project Memory Context",
        "",
        f"- `.muscle/` exists: `{'yes' if memory['muscle_dir_exists'] else 'no'}`",
        (
            "- `project_memory.db` exists: "
            f"`{'yes' if memory['project_memory_db_exists'] else 'no'}`"
        ),
        f"- Memory status: `{memory['status']}`",
        f"- Schema version: `{memory.get('schema_version') or 'unknown'}`",
        f"- Review runs: `{counts.get('review_runs', 0)}`",
        f"- Learned rules: `{counts.get('learned_rules', 0)}`",
        f"- Optimization decisions: `{counts.get('optimization_decisions', 0)}`",
        "",
    ]
    if latest_review:
        lines.extend(
            [
                "Latest review:",
                f"- Run: `#{latest_review.get('id')}` `{latest_review.get('review_mode')}`",
                f"- Target: `{latest_review.get('target_path')}`",
                f"- Findings: `{latest_review.get('findings_count')}`",
                "",
            ]
        )
    sample_entries = target.get("sample_entries") or []
    if sample_entries:
        lines.extend(["Target sample:", *[f"- `{entry}`" for entry in sample_entries], ""])

    lines.extend(
        [
            "## Preflight",
            "",
            *[f"{idx}. {action}" for idx, action in enumerate(preflight, start=1)],
            "",
            "## Guardrails",
            "",
            *[f"- {guardrail}" for guardrail in FORESIGHT_GUARDRAILS],
            "",
        ]
    )
    return _truncate_text("\n".join(lines), SHORT_TERM_MAX_CHARS)
