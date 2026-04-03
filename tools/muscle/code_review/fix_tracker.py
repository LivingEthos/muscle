"""
Fix Tracker - Tracks fix attempts and validates effectiveness.

Records fixes applied, their outcomes, and whether patterns recur.

Architecture Decision Record (ADR):
- Tracks fix success/failure per pattern
- Records tokens spent for cost analysis
- Validates fixes reduce issue recurrence
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.muscle.project_memory import ProjectMemory

logger = logging.getLogger(__name__)

DEFAULT_FIX_TRACKER_DIR = ".muscle/fix_tracker"


@dataclass
class FixAttempt:
    id: int | None
    pattern: str
    file_path: str
    fix_description: str
    was_applied: bool
    was_successful: bool
    tokens_spent: int
    recurrence_count: int
    created_at: str


class FixTracker:
    def __init__(self, tracker_path: str | None = None):
        self.tracker_path = Path(tracker_path) if tracker_path else Path(DEFAULT_FIX_TRACKER_DIR)
        self.tracker_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.tracker_path / "fix_tracker.db"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fix_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    fix_description TEXT NOT NULL,
                    was_applied INTEGER DEFAULT 0,
                    was_successful INTEGER DEFAULT 0,
                    tokens_spent INTEGER DEFAULT 0,
                    recurrence_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_fix_pattern ON fix_attempts(pattern)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pattern_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL UNIQUE,
                    total_attempts INTEGER DEFAULT 0,
                    successful_attempts INTEGER DEFAULT 0,
                    failed_attempts INTEGER DEFAULT 0,
                    avg_tokens_spent INTEGER DEFAULT 0,
                    last_attempted TEXT,
                    outcome_trend TEXT DEFAULT 'stable'
                )
            """)

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"FixTracker init error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def record_fix_attempt(
        self,
        pattern: str,
        file_path: str,
        fix_description: str,
        was_applied: bool,
        was_successful: bool,
        tokens_spent: int = 0,
    ) -> int:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            now = datetime.now().isoformat()

            cursor.execute(
                """
                INSERT INTO fix_attempts
                (pattern, file_path, fix_description, was_applied, was_successful, tokens_spent, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    pattern,
                    file_path,
                    fix_description,
                    int(was_applied),
                    int(was_successful),
                    tokens_spent,
                    now,
                ),
            )

            self._update_pattern_outcomes(conn, pattern, was_successful, tokens_spent)

            conn.commit()
            return cursor.lastrowid or 0
        except sqlite3.Error as e:
            logger.error(f"Failed to record fix attempt: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    def _update_pattern_outcomes(
        self, conn: sqlite3.Connection, pattern: str, success: bool, tokens_spent: int
    ) -> None:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM pattern_outcomes WHERE pattern = ?", (pattern,))
        row = cursor.fetchone()

        now = datetime.now().isoformat()

        if row:
            cursor.execute(
                """
                UPDATE pattern_outcomes
                SET total_attempts = total_attempts + 1,
                    successful_attempts = successful_attempts + ?,
                    failed_attempts = failed_attempts + ?,
                    avg_tokens_spent = (avg_tokens_spent * total_attempts + ?) / (total_attempts + 1),
                    last_attempted = ?
                WHERE pattern = ?
            """,
                (int(success), int(not success), tokens_spent, now, pattern),
            )
        else:
            cursor.execute(
                """
                INSERT INTO pattern_outcomes
                (pattern, total_attempts, successful_attempts, failed_attempts, avg_tokens_spent, last_attempted)
                VALUES (?, 1, ?, ?, ?, ?)
            """,
                (pattern, int(success), int(not success), tokens_spent, now),
            )

    def record_recurrence(self, pattern: str) -> None:
        """Increment recurrence count when same issue appears again after fix."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE fix_attempts
                SET recurrence_count = recurrence_count + 1
                WHERE pattern = ? AND was_successful = 1
                ORDER BY created_at DESC
                LIMIT 1
            """,
                (pattern,),
            )

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to record recurrence: {e}")
        finally:
            if conn:
                conn.close()

    def get_fix_success_rate(self, pattern: str) -> float:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT total_attempts, successful_attempts FROM pattern_outcomes
                WHERE pattern = ?
            """,
                (pattern,),
            )

            row = cursor.fetchone()
            if row and row["total_attempts"] > 0:
                return float(row["successful_attempts"]) / float(row["total_attempts"])
            return 0.0
        except sqlite3.Error as e:
            logger.error(f"Failed to get fix success rate: {e}")
            return 0.0
        finally:
            if conn:
                conn.close()

    def is_pattern_resolved(self, pattern: str, recurrence_threshold: int = 2) -> bool:
        """Check if pattern no longer recurs after fixes."""
        rate = self.get_fix_success_rate(pattern)
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT MAX(recurrence_count) as max_recurrence FROM fix_attempts
                WHERE pattern = ? AND was_successful = 1
            """,
                (pattern,),
            )

            row = cursor.fetchone()
            max_recurrence = row["max_recurrence"] if row else 0

            return rate >= 0.7 and max_recurrence < recurrence_threshold
        except sqlite3.Error as e:
            logger.error(f"Failed to check pattern resolution: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def get_statistics(self) -> dict:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(was_successful) as successes,
                       SUM(tokens_spent) as total_tokens
                FROM fix_attempts
                WHERE was_applied = 1
            """)

            fix_row = cursor.fetchone()

            cursor.execute("""
                SELECT COUNT(*) as patterns_with_fixes
                FROM pattern_outcomes
                WHERE successful_attempts > 0
            """)

            pattern_row = cursor.fetchone()

            return {
                "total_fix_attempts": fix_row["total"] or 0,
                "successful_fixes": fix_row["successes"] or 0,
                "total_tokens_spent": fix_row["total_tokens"] or 0,
                "patterns_fixed": pattern_row["patterns_with_fixes"] or 0,
                "success_rate": (float(fix_row["successes"] or 0) / float(fix_row["total"] or 1)),
            }
        except sqlite3.Error as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
        finally:
            if conn:
                conn.close()


# -----------------------------------------------------------------------------
# Legacy import (MUS-012)
# -----------------------------------------------------------------------------


def import_from_project_memory(project_memory: ProjectMemory, project_path: str) -> dict:
    """
    Import fix tracking data from legacy .muscle/fix_tracker/fix_tracker.db into ProjectMemory.

    This is a convenience wrapper that runs only the fix_tracker import step
    of LegacyImporter.

    Returns
    -------
    dict
        Import stats dict with keys: imported, skipped, errors.
    """
    from tools.muscle.legacy_importer import LegacyImporter

    importer = LegacyImporter(project_memory, project_path)
    importer._import_fix_tracker()
    return importer.stats.get("fix_tracker", {"imported": 0, "skipped": 0, "errors": 0})
