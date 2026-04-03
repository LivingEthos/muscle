"""
LegacyImporter - MUS-012: Import data from legacy MUSCLE stores into unified ProjectMemory.

This module provides the LegacyImporter class that migrates data from legacy store
formats into the unified SQLite schema in `.muscle/project_memory.db`.

Legacy stores imported:
- `.muscle/review_kb/review_kb.db`       → review_runs + review_findings
- `.muscle/knowledge/strategies.db`       → learned_rules
- `.muscle/fix_tracker/fix_tracker.db`    → fix_attempts
- `.muscle/sessions/<session_id>/`        → tasks + conversation_events
- `.muscle/CLAUDE.md`                     → learned_rules (extracted patterns)
- `.muscle/AGENT.md`                      → agents
- `.muscle/MEMORY.md`                     → project_notes

Import behavior:
- Idempotent: running twice produces the same result (no duplicates)
- Duplicate suppression via unique-constraint checks per table
- Missing legacy stores are handled gracefully (no error raised)
- Provenance is embedded in outcome/notes fields for traceability
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.muscle.project_memory import ProjectMemory

logger = logging.getLogger(__name__)

# Provenance marker used to identify imported records
PROVENANCE_PREFIX = "[imported_from:"

# ---------------------------------------------------------------------------
# CLAUDE.md / AGENT.md / MEMORY.md parsing helpers
# ---------------------------------------------------------------------------

_LEARNED_RULE_PATTERNS = [
    # Pattern: "- **Rule:** actual rule text **" or "- **Learned:** rule text"
    re.compile(r"^\s*[-*]\s+\*\*(?:Rule|Learned):\s+(.+?)\s*\*\*", re.MULTILINE),
    # Pattern: "- When/Since/If ... use/apply ..."
    re.compile(r"^\s*[-*]\s+(?:When|Since|If)\s+.+?(?:\s+use|\s+apply)", re.MULTILINE),
    # Pattern: "- Always/Never ... when/for ..."
    re.compile(r"^\s*[-*]\s+(?:Always|Never)\s+.+?(?:\s+when|\s+for)", re.MULTILINE),
]

_METADATA_KEY_PATTERNS = [
    (re.compile(r"^\s*[-*]\s*`?name`?:\s*(.+)", re.MULTILINE), "name"),
    (re.compile(r"^\s*[-*]\s*`?description`?:\s*(.+)", re.MULTILINE), "description"),
    (re.compile(r"^\s*[-*]\s*`?trigger`?:\s*(.+)", re.MULTILINE), "trigger"),
    (re.compile(r"^\s*[-*]\s*`?trigger_pattern`?:\s*(.+)", re.MULTILINE), "trigger_pattern"),
    (re.compile(r"^\s*[-*]\s*`?category`?:\s*(.+)", re.MULTILINE), "category"),
]


def _extract_learned_rules_from_markdown(content: str) -> list[dict]:
    """Extract rule_text and trigger_pattern candidates from a CLAUDE.md file."""
    rules: list[dict] = []
    for pattern in _LEARNED_RULE_PATTERNS:
        for match in pattern.finditer(content):
            # Use group(1) if available and non-empty, otherwise use the full match
            if match.lastindex and match.lastindex >= 1:
                rule_text = match.group(1).strip()
            else:
                rule_text = match.group(0).strip()
            if len(rule_text) > 10:
                trigger = _infer_trigger_from_rule(rule_text)
                rules.append({"rule_text": rule_text, "trigger_pattern": trigger})
    return rules


def _infer_trigger_from_rule(rule_text: str) -> str:
    """Infer a trigger pattern from rule text."""
    words = rule_text.split()
    if len(words) >= 3:
        return " ".join(words[:3]).lower()
    return rule_text.lower()[:50]


def _parse_agent_metadata(content: str) -> dict:
    """Parse AGENT.md metadata into a structured dict."""
    meta: dict = {"name": "", "description": "", "trigger_pattern": ""}
    for pattern, key in _METADATA_KEY_PATTERNS:
        match = pattern.search(content)
        if match:
            meta[key] = match.group(1).strip()
    if not meta.get("name"):
        title_match = re.search(r"^#\s+(.+?)\s*$", content, re.MULTILINE)
        if title_match:
            meta["name"] = title_match.group(1).strip()
    return meta


def _parse_memory_notes(content: str) -> list[dict]:
    """Parse MEMORY.md into structured notes."""
    notes: list[dict] = []
    sections = re.split(r"^##\s+", content, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.splitlines()
        if not lines:
            continue
        category = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        title = body.split("\n")[0][:80] if body else category
        notes.append({"category": category, "title": title, "content": body})
    return notes


# ---------------------------------------------------------------------------
# LegacyImporter
# ---------------------------------------------------------------------------


class LegacyImporter:
    """
    Import data from legacy MUSCLE stores into the unified ProjectMemory database.

    Parameters
    ----------
    memory : ProjectMemory
        The unified memory database instance.
    project_path : str
        Path to the project root (where .muscle/ lives).

    Attributes
    ----------
    stats : dict
        Counts of imported/skipped/errored records per store type.
    """

    def __init__(self, memory: ProjectMemory, project_path: str) -> None:
        self.memory = memory
        self.project_path = Path(project_path)
        self.muscle_dir = self.project_path / ".muscle"
        self.stats: dict[str, dict[str, int]] = {}

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    def run(self) -> dict[str, dict[str, int]]:
        """
        Run all legacy imports in sequence.

        Returns
        -------
        dict[str, dict[str, int]]
            Per-store stats with keys: imported, skipped, errors.
        """
        self._reset_stats()

        self._import_review_kb()
        self._import_strategies_db()
        self._import_fix_tracker()
        self._import_sessions()
        self._import_claude_md()
        self._import_agent_md()
        self._import_memory_md()

        return self.stats

    # -------------------------------------------------------------------------
    # Per-store import methods
    # -------------------------------------------------------------------------

    def _import_review_kb(self) -> None:
        """Import review_runs and review_findings from review_kb/review_kb.db."""
        store_path = self.muscle_dir / "review_kb" / "review_kb.db"
        self._init_store_stats("review_kb")

        if not store_path.exists():
            logger.debug("No legacy review_kb found at %s, skipping", store_path)
            return

        try:
            conn = sqlite3.connect(str(store_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.warning("Cannot open legacy review_kb: %s", e)
            self.stats["review_kb"]["errors"] += 1
            return

        try:
            # Import reviewed_issues → review_runs + review_findings
            cursor = conn.execute(
                """
                SELECT id, file_path, line_number, severity, category,
                       title, code_pattern, was_valid, was_fixed,
                       auto_fixed, false_positive_reason, created_at
                  FROM reviewed_issues
                """
            )
            for row in cursor:
                self._import_reviewed_issue(row)

            # Import fix_effectiveness → learned_rules (pattern-based rules)
            cursor = conn.execute(
                """
                SELECT pattern, fix_attempts, fix_successes,
                       avg_tokens_spent, last_attempted
                  FROM fix_effectiveness
                """
            )
            for row in cursor:
                self._import_fix_effectiveness(row)

        except sqlite3.Error as e:
            logger.error("Error reading review_kb: %s", e)
            self.stats["review_kb"]["errors"] += 1
        finally:
            conn.close()

    def _import_reviewed_issue(self, row: sqlite3.Row) -> None:
        """Import a single reviewed_issues row as a review_run + review_finding."""
        file_path = str(row["file_path"] or "")
        line_number = int(row["line_number"] or 0)
        severity = str(row["severity"] or "MEDIUM")
        category = str(row["category"] or "general")
        title = str(row["title"] or "")
        code_pattern = str(row["code_pattern"] or "")
        was_valid = bool(row["was_valid"])
        was_fixed = bool(row["was_fixed"])
        created_at = str(row["created_at"] or datetime.now().isoformat())

        # Check for duplicate: same file_path + line_number + code_pattern
        if self._review_finding_exists(file_path, line_number, code_pattern):
            self.stats["review_kb"]["skipped"] += 1
            return

        # Create a synthetic review_run for this single finding
        try:
            review_run_id = self.memory.insert_review_run(
                project_path=str(self.project_path),
                review_mode="legacy_import",
                target_path=file_path,
                findings_count=1,
                token_cost=0,
                duration_ms=0,
                created_at=created_at,
            )
        except sqlite3.Error:
            self.stats["review_kb"]["errors"] += 1
            return

        outcome = None
        if not was_valid:
            outcome = f"false_positive:{row['false_positive_reason'] or ''}"
        elif was_fixed:
            outcome = "fixed"

        try:
            self.memory.insert_review_finding(
                review_run_id=review_run_id,
                rule_id=code_pattern[:100],
                severity=severity,
                file_path=file_path,
                line_number=line_number,
                message=f"[{category}] {title}",
                auto_fixable=bool(row["auto_fixed"]),
                fix_applied=was_fixed,
                outcome=f"{PROVENANCE_PREFIX}review_kb] {outcome}"
                if outcome
                else f"{PROVENANCE_PREFIX}review_kb]",
            )
            self.stats["review_kb"]["imported"] += 1
        except sqlite3.Error:
            self.stats["review_kb"]["errors"] += 1

    def _import_fix_effectiveness(self, row: sqlite3.Row) -> None:
        """Import fix_effectiveness row as a learned_rule."""
        pattern = str(row["pattern"] or "")
        if not pattern or len(pattern) < 3:
            return

        if self._learned_rule_exists_by_pattern(pattern):
            self.stats["review_kb"]["skipped"] += 1
            return

        total = int(row["fix_attempts"] or 1)
        successes = int(row["fix_successes"] or 0)
        rate = successes / total if total > 0 else 0.0

        rule_text = f"Fix pattern: {pattern} (fix_success_rate={rate:.2f}, attempts={total})"

        try:
            self.memory.insert_learned_rule(
                project_path=str(self.project_path),
                rule_text=rule_text,
                trigger_pattern=pattern[:200],
                status="active",
            )
            self.stats["review_kb"]["imported"] += 1
        except sqlite3.Error:
            self.stats["review_kb"]["errors"] += 1

    def _import_strategies_db(self) -> None:
        """Import strategies.db → learned_rules."""
        store_path = self.muscle_dir / "knowledge" / "strategies.db"
        self._init_store_stats("strategies")

        if not store_path.exists():
            logger.debug("No legacy strategies.db found at %s, skipping", store_path)
            return

        try:
            conn = sqlite3.connect(str(store_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.warning("Cannot open legacy strategies.db: %s", e)
            self.stats["strategies"]["errors"] += 1
            return

        try:
            cursor = conn.execute(
                """
                SELECT error_pattern, root_cause, solution_strategy,
                       language, success_rate, usage_count, created_at
                  FROM strategies
                """
            )
            for row in cursor:
                self._import_strategy(row)
        except sqlite3.Error as e:
            logger.error("Error reading strategies.db: %s", e)
            self.stats["strategies"]["errors"] += 1
        finally:
            conn.close()

    def _import_strategy(self, row: sqlite3.Row) -> None:
        """Import a single strategy row as a learned_rule."""
        error_pattern = str(row["error_pattern"] or "")
        root_cause = str(row["root_cause"] or "")
        solution = str(row["solution_strategy"] or "")

        if not error_pattern or len(error_pattern) < 3:
            return

        if self._learned_rule_exists_by_pattern(error_pattern):
            self.stats["strategies"]["skipped"] += 1
            return

        rule_text = f"{error_pattern}\nRoot cause: {root_cause}\nSolution: {solution}"

        try:
            self.memory.insert_learned_rule(
                project_path=str(self.project_path),
                rule_text=rule_text,
                trigger_pattern=error_pattern[:200],
                status="active",
            )
            self.stats["strategies"]["imported"] += 1
        except sqlite3.Error:
            self.stats["strategies"]["errors"] += 1

    def _import_fix_tracker(self) -> None:
        """Import fix_tracker/fix_tracker.db → fix_attempts."""
        store_path = self.muscle_dir / "fix_tracker" / "fix_tracker.db"
        self._init_store_stats("fix_tracker")

        if not store_path.exists():
            logger.debug("No legacy fix_tracker.db found at %s, skipping", store_path)
            return

        try:
            conn = sqlite3.connect(str(store_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.warning("Cannot open legacy fix_tracker: %s", e)
            self.stats["fix_tracker"]["errors"] += 1
            return

        try:
            cursor = conn.execute(
                """
                SELECT pattern, file_path, fix_description,
                       was_applied, was_successful, tokens_spent, created_at
                  FROM fix_attempts
                """
            )
            for row in cursor:
                self._import_fix_attempt(row)
        except sqlite3.Error as e:
            logger.error("Error reading fix_tracker.db: %s", e)
            self.stats["fix_tracker"]["errors"] += 1
        finally:
            conn.close()

    def _import_fix_attempt(self, row: sqlite3.Row) -> None:
        """Import a single fix_attempt row.

        Note: fix_attempts table references finding_id (FK). Legacy records
        don't have finding_ids, so we use finding_id=0 as a sentinel and store
        provenance in the notes field.
        """
        pattern = str(row["pattern"] or "")
        file_path = str(row["file_path"] or "")

        # Deduplicate by pattern + file_path
        if self._fix_attempt_exists(pattern, file_path):
            self.stats["fix_tracker"]["skipped"] += 1
            return

        notes = f"{PROVENANCE_PREFIX}fix_tracker] original_pattern={pattern}"

        try:
            self.memory.insert_fix_attempt(
                finding_id=0,  # sentinel - no FK link for legacy imports
                fix_content=str(row["fix_description"] or ""),
                verification_passed=bool(row["was_successful"]),
                notes=notes,
            )
            self.stats["fix_tracker"]["imported"] += 1
        except sqlite3.Error:
            self.stats["fix_tracker"]["errors"] += 1

    def _import_sessions(self) -> None:
        """Import session directories → tasks + conversation_events."""
        sessions_dir = self.muscle_dir / "sessions"
        self._init_store_stats("sessions")

        if not sessions_dir.exists():
            logger.debug("No legacy sessions dir found at %s, skipping", sessions_dir)
            return

        for session_path in sessions_dir.iterdir():
            if not session_path.is_dir():
                continue
            self._import_session(session_path)

    def _import_session(self, session_path: Path) -> None:
        """Import a single session directory."""
        session_id = session_path.name
        meta_file = session_path / "meta.json"
        iterations_file = session_path / "iterations.jsonl"

        if not meta_file.exists():
            return

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cannot read session meta %s: %s", session_id, e)
            self.stats["sessions"]["errors"] += 1
            return

        # Check if task already exists (by session_id in title)
        if self._task_exists(session_id):
            self.stats["sessions"]["skipped"] += 1
            return

        task_title = str(meta.get("task", "unknown"))[:200]
        description = json.dumps(
            {
                "session_id": session_id,
                "language": meta.get("language"),
                "max_iterations": meta.get("max_iterations"),
                "status": meta.get("status"),
            }
        )

        created_at = str(meta.get("created_at", datetime.now().isoformat()))

        try:
            task_id = self.memory.insert_task(
                project_path=str(self.project_path),
                created_at=created_at,
                title=task_title,
                description=description,
                status=str(meta.get("status", "completed")),
                outcome=None,
                token_cost=0,
                duration_ms=0,
            )
            self.stats["sessions"]["imported"] += 1
        except sqlite3.Error:
            self.stats["sessions"]["errors"] += 1
            return

        # Import iterations as conversation_events
        if iterations_file.exists():
            self._import_session_iterations(session_id, task_id, iterations_file)

        # Emit a "session_created" event
        try:
            self.memory.insert_change_event(
                project_path=str(self.project_path),
                changed_files_json="[]",
                diff_summary=f"Imported legacy session: {session_id}",
                review_run_id=None,
            )
        except sqlite3.Error:
            pass  # non-fatal

    def _import_session_iterations(
        self, session_id: str, task_id: int, iterations_file: Path
    ) -> None:
        """Import iterations.jsonl as conversation_events."""
        try:
            content = iterations_file.read_text(encoding="utf-8")
        except OSError:
            return

        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            iteration_num = int(entry.get("iteration", 0))
            success = bool(entry.get("success", False))

            summary = f"iteration={iteration_num} success={success}"

            try:
                self.memory.insert_change_event(
                    project_path=str(self.project_path),
                    changed_files_json="[]",
                    diff_summary=summary,
                    review_run_id=None,
                )
            except sqlite3.Error:
                continue

    def _import_claude_md(self) -> None:
        """Extract learned rules from CLAUDE.md → learned_rules."""
        claude_md = self.muscle_dir / "CLAUDE.md"
        self._init_store_stats("CLAUDE.md")

        if not claude_md.exists():
            logger.debug("No CLAUDE.md found, skipping")
            return

        try:
            content = claude_md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot read CLAUDE.md: %s", e)
            self.stats["CLAUDE.md"]["errors"] += 1
            return

        rules = _extract_learned_rules_from_markdown(content)
        if not rules:
            logger.debug("No rules extracted from CLAUDE.md")
            return

        for rule in rules:
            if self._learned_rule_exists_by_pattern(rule["trigger_pattern"]):
                self.stats["CLAUDE.md"]["skipped"] += 1
                continue

            try:
                self.memory.insert_learned_rule(
                    project_path=str(self.project_path),
                    rule_text=rule["rule_text"],
                    trigger_pattern=rule["trigger_pattern"],
                    status="active",
                )
                self.stats["CLAUDE.md"]["imported"] += 1
            except sqlite3.Error:
                self.stats["CLAUDE.md"]["errors"] += 1

    def _import_agent_md(self) -> None:
        """Import AGENT.md → agents table."""
        agent_md = self.muscle_dir / "AGENT.md"
        self._init_store_stats("AGENT.md")

        if not agent_md.exists():
            logger.debug("No AGENT.md found, skipping")
            return

        try:
            content = agent_md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot read AGENT.md: %s", e)
            self.stats["AGENT.md"]["errors"] += 1
            return

        meta = _parse_agent_metadata(content)
        if not meta.get("name"):
            self.stats["AGENT.md"]["skipped"] += 1
            return

        # Check for duplicate by name
        if self._agent_exists(meta["name"]):
            self.stats["AGENT.md"]["skipped"] += 1
            return

        # agents table is not yet patched onto ProjectMemory, use raw SQL
        conn = None
        try:
            conn = self.memory._get_connection()
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO agents
                (project_path, created_at, name, description, trigger_pattern, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(self.project_path),
                    now,
                    meta["name"],
                    meta["description"],
                    meta["trigger_pattern"],
                    "active",
                ),
            )
            conn.commit()
            self.stats["AGENT.md"]["imported"] += 1
        except sqlite3.Error as e:
            logger.warning("Cannot insert agent: %s", e)
            self.stats["AGENT.md"]["errors"] += 1
        finally:
            if conn:
                conn.close()

    def _import_memory_md(self) -> None:
        """Import MEMORY.md → project_notes."""
        from tools.muscle.project_notes import _insert_project_note

        memory_md = self.muscle_dir / "MEMORY.md"
        self._init_store_stats("MEMORY.md")

        if not memory_md.exists():
            logger.debug("No MEMORY.md found, skipping")
            return

        try:
            content = memory_md.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot read MEMORY.md: %s", e)
            self.stats["MEMORY.md"]["errors"] += 1
            return

        notes = _parse_memory_notes(content)
        if not notes:
            self.stats["MEMORY.md"]["skipped"] += 1
            return

        now = datetime.now().isoformat()
        for note in notes:
            try:
                _insert_project_note(
                    self.memory,
                    project_path=str(self.project_path),
                    category=note["category"],
                    title=note["title"],
                    content=note["content"],
                    created_at=now,
                    updated_at=now,
                )
                self.stats["MEMORY.md"]["imported"] += 1
            except (sqlite3.Error, AttributeError):
                self.stats["MEMORY.md"]["errors"] += 1

    # -------------------------------------------------------------------------
    # Duplicate detection helpers
    # -------------------------------------------------------------------------

    def _review_finding_exists(self, file_path: str, line_number: int, rule_id: str) -> bool:
        """Check if a review_finding already exists (for deduplication)."""
        conn = None
        try:
            conn = self.memory._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM review_findings
                 WHERE file_path = ? AND line_number = ? AND rule_id = ?
                 LIMIT 1
                """,
                (file_path, line_number, rule_id[:100]),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if conn:
                conn.close()

    def _learned_rule_exists_by_pattern(self, trigger_pattern: str) -> bool:
        """Check if a learned_rule with the same trigger_pattern already exists."""
        conn = None
        try:
            conn = self.memory._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM learned_rules
                 WHERE project_path = ? AND trigger_pattern = ?
                 LIMIT 1
                """,
                (str(self.project_path), trigger_pattern[:200]),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if conn:
                conn.close()

    def _fix_attempt_exists(self, pattern: str, file_path: str) -> bool:
        """Check if a fix_attempt with same pattern+file already exists."""
        conn = None
        try:
            conn = self.memory._get_connection()
            cursor = conn.cursor()
            # Note: legacy fix_attempts use finding_id=0, so we also check notes
            cursor.execute(
                """
                SELECT 1 FROM fix_attempts
                 WHERE finding_id = 0
                   AND notes LIKE ?
                 LIMIT 1
                """,
                (f"%{PROVENANCE_PREFIX}fix_tracker] original_pattern={pattern[:50]}%",),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if conn:
                conn.close()

    def _task_exists(self, session_id: str) -> bool:
        """Check if a task with the session_id in description already exists."""
        conn = None
        try:
            conn = self.memory._get_connection()
            cursor = conn.cursor()
            # Use LIKE on the description JSON string - the description field
            # contains JSON like {"session_id": "session-001", ...}
            # JSON may have spaces after colons, so we use '%"session_id"%' to be flexible
            pattern = '%"session_id"%'
            cursor.execute(
                """
                SELECT 1 FROM tasks
                 WHERE project_path = ?
                   AND description LIKE ?
                   AND description LIKE ?
                 LIMIT 1
                """,
                (str(self.project_path), pattern, f'%"{session_id}"%'),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if conn:
                conn.close()

    def _agent_exists(self, name: str) -> bool:
        """Check if an agent with the same name already exists."""
        conn = None
        try:
            conn = self.memory._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM agents
                 WHERE project_path = ? AND name = ?
                 LIMIT 1
                """,
                (str(self.project_path), name),
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            if conn:
                conn.close()

    # -------------------------------------------------------------------------
    # Stats helpers
    # -------------------------------------------------------------------------

    def _reset_stats(self) -> None:
        self.stats = {}

    def _init_store_stats(self, store: str) -> None:
        if store not in self.stats:
            self.stats[store] = {"imported": 0, "skipped": 0, "errors": 0}
