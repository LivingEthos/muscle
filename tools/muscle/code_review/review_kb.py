"""
Review Knowledge Base - Learns from past code reviews.

Stores reviewed issues, resolutions, and effectiveness data
to improve future reviews and avoid re-reviewing the same patterns.

Architecture Decision Record (ADR):
- Extends StrategyKB patterns for review-specific data
- Tracks false positive rates per pattern
- Stores fix success rates
- Global KB for cross-project learning
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

DEFAULT_REVIEW_KB_DIR = ".muscle/review_kb"
GLOBAL_REVIEW_KB_DIR = "~/.muscle/global_review"


@dataclass
class ReviewedIssue:
    id: int | None
    file_path: str
    line_number: int
    severity: str
    category: str
    title: str
    code_pattern: str
    was_valid: bool
    was_fixed: bool
    auto_fixed: bool
    false_positive_reason: str | None
    created_at: str


class ReviewKB:
    def __init__(self, kb_path: str | None = None):
        self.kb_path = Path(kb_path) if kb_path else Path(DEFAULT_REVIEW_KB_DIR)
        self.kb_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.kb_path / "review_kb.db"
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
                CREATE TABLE IF NOT EXISTS reviewed_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    line_number INTEGER,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    code_pattern TEXT,
                    was_valid INTEGER DEFAULT 1,
                    was_fixed INTEGER DEFAULT 0,
                    auto_fixed INTEGER DEFAULT 0,
                    false_positive_reason TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_issue_pattern ON reviewed_issues(code_pattern)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_issue_file ON reviewed_issues(file_path)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fix_effectiveness (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL,
                    fix_attempts INTEGER DEFAULT 0,
                    fix_successes INTEGER DEFAULT 0,
                    avg_tokens_spent INTEGER DEFAULT 0,
                    last_attempted TEXT
                )
            """)

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"ReviewKB init error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def add_reviewed_issue(
        self,
        file_path: str,
        line_number: int,
        severity: str,
        category: str,
        title: str,
        code_pattern: str,
        was_valid: bool,
        was_fixed: bool = False,
        auto_fixed: bool = False,
        false_positive_reason: str | None = None,
    ) -> int:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            now = datetime.now().isoformat()

            cursor.execute(
                """
                INSERT INTO reviewed_issues
                (file_path, line_number, severity, category, title, code_pattern,
                 was_valid, was_fixed, auto_fixed, false_positive_reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    file_path,
                    line_number,
                    severity,
                    category,
                    title,
                    code_pattern,
                    int(was_valid),
                    int(was_fixed),
                    int(auto_fixed),
                    false_positive_reason,
                    now,
                ),
            )

            conn.commit()
            return cursor.lastrowid or 0
        except sqlite3.Error as e:
            logger.error(f"Failed to add reviewed issue: {e}")
            return 0
        finally:
            if conn:
                conn.close()

    def record_fix_attempt(self, pattern: str, success: bool, tokens_spent: int) -> None:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, fix_attempts, fix_successes FROM fix_effectiveness
                WHERE pattern = ?
            """,
                (pattern,),
            )
            row = cursor.fetchone()

            now = datetime.now().isoformat()

            if row:
                cursor.execute(
                    """
                    UPDATE fix_effectiveness
                    SET fix_attempts = fix_attempts + 1,
                        fix_successes = fix_successes + ?,
                        avg_tokens_spent = (avg_tokens_spent * fix_attempts + ?) / (fix_attempts + 1),
                        last_attempted = ?
                    WHERE pattern = ?
                """,
                    (int(success), tokens_spent, now, pattern),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO fix_effectiveness
                    (pattern, fix_attempts, fix_successes, avg_tokens_spent, last_attempted)
                    VALUES (?, 1, ?, ?, ?)
                """,
                    (pattern, int(success), tokens_spent, now),
                )

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to record fix attempt: {e}")
        finally:
            if conn:
                conn.close()

    def get_false_positive_rate(self, pattern: str) -> float:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN was_valid = 0 THEN 1 ELSE 0 END) as false_pos
                FROM reviewed_issues
                WHERE code_pattern = ?
            """,
                (pattern,),
            )

            row = cursor.fetchone()
            if row and row["total"] > 0:
                false_pos: float = float(row["false_pos"] or 0)
                total: float = float(row["total"] or 1)
                return false_pos / total
            return 0.0
        except sqlite3.Error as e:
            logger.error(f"Failed to get false positive rate: {e}")
            return 0.0
        finally:
            if conn:
                conn.close()

    def should_skip_pattern(self, pattern: str, threshold: float = 0.7) -> bool:
        rate = self.get_false_positive_rate(pattern)
        return rate >= threshold

    def get_fix_success_rate(self, pattern: str) -> float:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT fix_attempts, fix_successes FROM fix_effectiveness
                WHERE pattern = ?
            """,
                (pattern,),
            )

            row = cursor.fetchone()
            if row and row["fix_attempts"] > 0:
                successes: float = float(row["fix_successes"] or 0)
                attempts: float = float(row["fix_attempts"] or 1)
                return successes / attempts
            return 0.0
        except sqlite3.Error as e:
            logger.error(f"Failed to get fix success rate: {e}")
            return 0.0
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
                       SUM(CASE WHEN was_valid = 0 THEN 1 ELSE 0 END) as false_pos,
                       SUM(CASE WHEN was_fixed = 1 THEN 1 ELSE 0 END) as fixed,
                       SUM(CASE WHEN auto_fixed = 1 THEN 1 ELSE 0 END) as auto_fixed
                FROM reviewed_issues
            """)

            issue_row = cursor.fetchone()

            cursor.execute("""
                SELECT COUNT(*) as total_patterns,
                       SUM(fix_attempts) as total_attempts,
                       SUM(fix_successes) as total_successes
                FROM fix_effectiveness
            """)

            fix_row = cursor.fetchone()

            return {
                "total_reviewed": issue_row["total"] or 0,
                "false_positives": issue_row["false_pos"] or 0,
                "issues_fixed": issue_row["fixed"] or 0,
                "auto_fixed": issue_row["auto_fixed"] or 0,
                "unique_patterns": fix_row["total_patterns"] or 0,
                "fix_attempts": fix_row["total_attempts"] or 0,
                "fix_successes": fix_row["total_successes"] or 0,
            }
        except sqlite3.Error as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
        finally:
            if conn:
                conn.close()


class GlobalReviewKB:
    def __init__(self, global_kb_path: str | None = None):
        self.global_path = (
            Path(global_kb_path) if global_kb_path else Path(GLOBAL_REVIEW_KB_DIR).expanduser()
        )
        self.global_path.mkdir(parents=True, exist_ok=True)
        self.review_kb = ReviewKB(str(self.global_path))

    def record_issue(
        self,
        file_path: str,
        line_number: int,
        severity: str,
        category: str,
        title: str,
        code_pattern: str,
        was_valid: bool,
        was_fixed: bool = False,
        auto_fixed: bool = False,
        false_positive_reason: str | None = None,
    ) -> int:
        return self.review_kb.add_reviewed_issue(
            file_path=file_path,
            line_number=line_number,
            severity=severity,
            category=category,
            title=title,
            code_pattern=code_pattern,
            was_valid=was_valid,
            was_fixed=was_fixed,
            auto_fixed=auto_fixed,
            false_positive_reason=false_positive_reason,
        )

    def record_fix(self, pattern: str, success: bool, tokens_spent: int) -> None:
        self.review_kb.record_fix_attempt(pattern, success, tokens_spent)

    def get_stats(self) -> dict:
        return self.review_kb.get_statistics()


# -----------------------------------------------------------------------------
# Legacy import (MUS-012)
# -----------------------------------------------------------------------------


def import_from_project_memory(project_memory: ProjectMemory, project_path: str) -> dict:
    """
    Import review data from legacy .muscle/review_kb/review_kb.db into ProjectMemory.

    This is a convenience wrapper that runs only the review_kb import step
    of LegacyImporter.

    Returns
    -------
    dict
        Import stats dict with keys: imported, skipped, errors.
    """
    from tools.muscle.legacy_importer import LegacyImporter

    importer = LegacyImporter(project_memory, project_path)
    importer._import_review_kb()
    return importer.stats.get("review_kb", {"imported": 0, "skipped": 0, "errors": 0})
