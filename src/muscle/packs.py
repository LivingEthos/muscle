"""Content-addressed task-context packs for reuse across MUSCLE subtasks (Phase B.5).

A ``Pack`` bundles the distilled context a delegation needs — task description,
acceptance criteria, scope files, type signatures, issue-centered code excerpts,
and relevant project-memory rules — into a single markdown file addressed by
the sha256 of its *canonical* (timestamp-free) body.

The pack body is written to disk under ``.muscle/packs/<id>.md`` with a
wall-clock ``Created:`` line so it's readable; the ``content_sha`` stored in
the ``Pack`` dataclass and in the ``packs`` table is computed over the
canonical body only, so identical inputs produce identical pack ids
regardless of when they were built.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .project_memory import ProjectMemory

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .optimization.context_budgeter import ContextBudgeter

logger = logging.getLogger(__name__)

PACK_CONSUMERS = "/muscle:review, /muscle:fix, /muscle:verify"
PACK_ID_LEN = 16
MAX_TASK_TITLE_LEN = 80
MAX_RULES = 20
MAX_EXCERPT_LINES_PER_FILE = 60
MAX_EXCERPT_FILES = 20
SKIP_DIR_PARTS = frozenset(
    {".git", ".muscle", "__pycache__", ".venv", "node_modules", "dist", "build"}
)
SIGNATURE_RE = re.compile(r"^(async\s+def|def|class)\s+[\w_]+.*:", re.MULTILINE)


@dataclass
class Pack:
    """In-memory representation of a content-addressed context pack."""

    id: str
    path: Path
    task: str
    scope: list[Path]
    acceptance: str
    content_sha: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PackBuilder:
    """Assemble a :class:`Pack` from a task description and a scope path."""

    def __init__(self, project_path: Path, context_budgeter: ContextBudgeter) -> None:
        self._project = Path(project_path)
        self._budgeter = context_budgeter
        self._pm = ProjectMemory(str(project_path))

    def build(self, task: str, scope: Path, acceptance: str = "") -> Pack:
        """Assemble a pack. Deterministic: same inputs produce the same pack id.

        Steps:
        1. Collect files in scope (recursive if dir, single if file).
        2. Ask the context budgeter for issue-centered windows per file.
        3. Extract Python ``def``/``class`` signatures from scope files.
        4. Pull relevant rules from project_memory.db matching scope paths.
        5. Render a canonical (timestamp-free) body for hashing, and a
           timestamped body for on-disk storage.
        """
        scope_files = self._collect_scope_files(scope)
        excerpts = self._collect_excerpts(task, scope_files)
        signatures = self._extract_signatures(scope_files)
        rules = self._relevant_rules(scope_files)

        canonical = self._render_markdown(
            task=task,
            acceptance=acceptance,
            scope_files=scope_files,
            excerpts=excerpts,
            signatures=signatures,
            rules=rules,
            created_at=None,
        )
        content_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        pack_id = content_sha[:PACK_ID_LEN]

        created_at = datetime.now(timezone.utc)
        body = self._render_markdown(
            task=task,
            acceptance=acceptance,
            scope_files=scope_files,
            excerpts=excerpts,
            signatures=signatures,
            rules=rules,
            created_at=created_at,
        )

        packs_dir = self._project / ".muscle" / "packs"
        packs_dir.mkdir(parents=True, exist_ok=True)
        path = packs_dir / f"{pack_id}.md"
        path.write_text(body, encoding="utf-8")

        pack = Pack(
            id=pack_id,
            path=path,
            task=task,
            scope=scope_files,
            acceptance=acceptance,
            content_sha=content_sha,
            created_at=created_at,
        )
        PackStore(self._project).put(pack)
        return pack

    def _collect_scope_files(self, scope: Path) -> list[Path]:
        scope = Path(scope)
        if scope.is_file():
            return [scope]
        if not scope.exists():
            return []
        return sorted(p for p in scope.rglob("*") if p.is_file() and self._include(p))

    @staticmethod
    def _include(path: Path) -> bool:
        return not any(part in SKIP_DIR_PARTS for part in path.parts)

    def _collect_excerpts(self, task: str, files: list[Path]) -> dict[str, str]:
        """Return {relative_path: code excerpt} via the context budgeter.

        ``ContextBudgeter.build_semantic_review_budget`` expects a file's full
        text plus structured issue dicts; we have a free-form task string and
        no static-analyzer issues yet, so we call it in *proactive* mode which
        selects risk-cue windows without requiring issues. This mirrors the
        spec's intent ("issue-centered windows") while fitting the real API.
        """
        out: dict[str, str] = {}
        for f in files[:MAX_EXCERPT_FILES]:
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            if not text.strip():
                continue
            try:
                budget = self._budgeter.build_semantic_review_budget(
                    file_path=str(f),
                    code_content=text,
                    issues=[],
                    proactive=True,
                )
            except Exception:  # noqa: BLE001 - budgeter is defensive by contract
                logger.debug("budgeter failed for %s", f, exc_info=True)
                continue
            content = (budget.content or "").strip()
            if not content:
                continue
            # Keep excerpts bounded — the full body is on disk if needed.
            lines = content.splitlines()[:MAX_EXCERPT_LINES_PER_FILE]
            try:
                rel = str(f.relative_to(self._project))
            except ValueError:
                rel = str(f)
            out[rel] = "\n".join(lines)
        # Ignore the task argument for now — the budgeter doesn't use it.
        # Reference it to keep the signature meaningful for future iterations.
        del task
        return out

    def _extract_signatures(self, files: list[Path]) -> dict[str, list[str]]:
        """Return {relative_path: [def/class signature lines]} for Python files."""
        out: dict[str, list[str]] = {}
        for f in files:
            if f.suffix != ".py":
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            matches = [m.group(0).rstrip() for m in SIGNATURE_RE.finditer(text)]
            if not matches:
                continue
            try:
                rel = str(f.relative_to(self._project))
            except ValueError:
                rel = str(f)
            out[rel] = matches
        return out

    def _relevant_rules(self, files: list[Path]) -> list[str]:
        """Query project_memory.db for rules relevant to the scope files.

        Note: the real schema uses ``learned_rules`` (not ``rules``) with
        columns ``rule_text``, ``status``, ``promoted_to_claude_md``,
        ``recurrence_count``, ``success_rate`` — not the ``rules`` /
        ``scope_path`` / ``promoted`` / ``score`` shape the spec assumes.
        Scope is tracked implicitly via ``project_path`` (the project root),
        not per-file, so we return the project-wide promoted rules ordered
        by recurrence count and success rate. If the DB is missing (e.g.
        migrations haven't run yet) we return an empty list rather than fail.
        """
        if not files:
            return []
        db = self._project / ".muscle" / "project_memory.db"
        if not db.exists():
            return []
        try:
            with self._pm.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT rule_text FROM learned_rules
                    WHERE project_path = ?
                      AND status = 'active'
                      AND promoted_to_claude_md = 1
                    ORDER BY recurrence_count DESC, success_rate DESC
                    LIMIT ?
                    """,
                    (str(self._project), MAX_RULES),
                ).fetchall()
        except Exception:  # noqa: BLE001 - missing table / other DB errors
            logger.debug("learned_rules query failed for %s", db, exc_info=True)
            return []
        return [row[0] for row in rows if row and row[0]]

    def _render_markdown(
        self,
        task: str,
        acceptance: str,
        scope_files: list[Path],
        excerpts: dict[str, str],
        signatures: dict[str, list[str]],
        rules: list[str],
        created_at: datetime | None,
    ) -> str:
        """Render the pack body.

        When ``created_at`` is None the output is *canonical* — stable across
        wall-clock time — and suitable for content-hashing. When a concrete
        datetime is supplied, it's embedded in the Manifest section for the
        on-disk copy.
        """
        lines: list[str] = [
            f"# Pack - {task[:MAX_TASK_TITLE_LEN]}",
            "",
            "## Task",
            task,
            "",
        ]
        if acceptance:
            lines.extend(["## Acceptance criteria", acceptance, ""])

        lines.append("## Scope")
        for f in scope_files:
            try:
                rel = f.relative_to(self._project)
            except ValueError:
                rel = f
            lines.append(f"- `{rel}`")
        lines.append("")

        if signatures:
            lines.append("## Type signatures")
            for path, sigs in sorted(signatures.items()):
                lines.append(f"### `{path}`")
                lines.extend(f"- `{s}`" for s in sigs)
                lines.append("")

        if excerpts:
            lines.append("## Code excerpts")
            for path, snippet in sorted(excerpts.items()):
                lines.append(f"### `{path}`")
                lines.append("```")
                lines.append(snippet)
                lines.append("```")
                lines.append("")

        if rules:
            lines.append("## Conventions")
            lines.extend(f"- {r}" for r in rules)
            lines.append("")

        lines.append("## Manifest")
        lines.append(f"Consumed by: {PACK_CONSUMERS}")
        if created_at is not None:
            lines.append(f"Created: {created_at.isoformat()}")
        return "\n".join(lines) + "\n"


class PackStore:
    """Metadata store for packs.

    Pack bodies live on disk under ``.muscle/packs/<id>.md``; this class
    tracks ``(id, path, task, content_sha, created_at)`` rows in the
    project_memory ``packs`` table (see migration ``_0016_packs``).
    """

    def __init__(self, project_path: Path) -> None:
        self._project = Path(project_path)
        self._dir = self._project / ".muscle" / "packs"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pm = ProjectMemory(str(project_path))

    def get(self, pack_id: str) -> Pack | None:
        """Return a :class:`Pack` for ``pack_id`` if it exists on disk.

        Rehydrates task/acceptance/created_at from the DB when a row is
        present; otherwise returns a minimal reconstruction from the file.
        """
        path = self._dir / f"{pack_id}.md"
        if not path.exists():
            return None

        task = ""
        acceptance = ""
        created_at = datetime.now(timezone.utc)
        content_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            with self._pm.connection() as conn:
                row = conn.execute(
                    "SELECT task, content_sha, created_at FROM packs WHERE id = ?",
                    (pack_id,),
                ).fetchone()
        except Exception:  # noqa: BLE001 - DB may not be migrated
            logger.debug("packs lookup failed for %s", pack_id, exc_info=True)
            row = None
        if row is not None:
            task = row[0] or ""
            if row[1]:
                content_sha = row[1]
            try:
                created_at = datetime.fromisoformat(row[2])
            except (TypeError, ValueError):
                pass

        return Pack(
            id=pack_id,
            path=path,
            task=task,
            scope=[],
            acceptance=acceptance,
            content_sha=content_sha,
            created_at=created_at,
        )

    def put(self, pack: Pack) -> None:
        """Persist pack metadata to the ``packs`` table."""
        try:
            with self._pm.connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO packs "
                    "(id, path, task, content_sha, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        pack.id,
                        str(pack.path),
                        pack.task,
                        pack.content_sha,
                        pack.created_at.isoformat(),
                    ),
                )
        except Exception:  # noqa: BLE001 - keep builder working if DB absent
            logger.debug("packs INSERT failed for %s", pack.id, exc_info=True)

    def list(self) -> list[Pack]:
        """Return every pack currently on disk, newest-first-ish (filename sort)."""
        out: list[Pack] = []
        for p in sorted(self._dir.glob("*.md")):
            pack = self.get(p.stem)
            if pack is not None:
                out.append(pack)
        return out

    def gc(self, older_than: timedelta) -> int:
        """Remove packs older than ``older_than``. Returns the number deleted."""
        cutoff = datetime.now(timezone.utc) - older_than
        removed = 0
        try:
            with self._pm.connection() as conn:
                rows = conn.execute(
                    "SELECT id, path FROM packs WHERE created_at < ?",
                    (cutoff.isoformat(),),
                ).fetchall()
                for pack_id, path_str in rows:
                    try:
                        Path(path_str).unlink()
                        removed += 1
                    except OSError:
                        logger.debug("failed to unlink %s", path_str, exc_info=True)
                    conn.execute("DELETE FROM packs WHERE id = ?", (pack_id,))
        except Exception:  # noqa: BLE001
            logger.debug("pack gc failed", exc_info=True)
        return removed
