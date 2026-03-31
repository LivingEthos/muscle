"""
Strategy Knowledge Base - Persistent storage for learned strategies.

Architecture Decision Record (ADR):
- Two-tier knowledge: project-specific and global strategies
- SQLite for structured data storage
- sqlite-vss for vector similarity search on error patterns
- Stores root causes, solutions, and usage statistics
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_KB_DIR = ".scle/knowledge"
GLOBAL_KB_DIR = "~/.scle/global"
MAX_TOP_K = 100
MAX_PATH_LENGTH = 4096


@dataclass
class Strategy:
    id: int | None
    error_pattern: str
    root_cause: str
    solution_strategy: str
    language: str | None
    success_rate: float
    usage_count: int
    created_at: str
    updated_at: str


class StrategyKB:
    def __init__(
        self,
        kb_path: str | None = None,
        enable_vector_search: bool = False,
    ):
        if kb_path:
            kb_path = os.path.abspath(kb_path)
            if len(kb_path) > MAX_PATH_LENGTH:
                raise ValueError(f"kb_path exceeds maximum length of {MAX_PATH_LENGTH}")
        self.kb_path = Path(kb_path) if kb_path else Path(DEFAULT_KB_DIR)
        try:
            self.kb_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create kb directory: {e}")
            raise
        self.db_path = self.kb_path / "strategies.db"
        self.enable_vector_search = enable_vector_search and self._check_vss()

        self._init_db()

    def _check_vss(self) -> bool:
        import importlib.util

        if importlib.util.find_spec("sqlite_vss") is None:
            logger.warning("sqlite-vss not installed, vector search disabled")
            return False
        return True

    def _get_connection(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
        if self.enable_vector_search:
            try:
                conn.enable_load_extension(True)
                conn.load_extension("sqlite_vss")
            except Exception as e:
                logger.warning(f"Failed to load sqlite-vss: {e}")
        return conn

    def _init_db(self) -> None:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_pattern TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    solution_strategy TEXT NOT NULL,
                    language TEXT,
                    success_rate REAL DEFAULT 0.0,
                    usage_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    embedding BLOB
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_pattern ON strategies(error_pattern)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_language ON strategies(language)
            """)

            if self.enable_vector_search:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS strategies_vss USING vss0(
                        embedding(384)
                    )
                """)

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def add_strategy(
        self,
        error_pattern: str,
        root_cause: str,
        solution_strategy: str,
        language: str | None = None,
        embedding: bytes | None = None,
    ) -> int:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            now = datetime.now().isoformat()

            cursor.execute(
                """
                INSERT INTO strategies (error_pattern, root_cause, solution_strategy, language, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (error_pattern, root_cause, solution_strategy, language, embedding, now, now),
            )

            strategy_id = cursor.lastrowid

            if embedding and self.enable_vector_search:
                try:
                    cursor.execute(
                        """
                        INSERT INTO strategies_vss(rowid, embedding) VALUES (?, ?)
                    """,
                        (strategy_id, embedding),
                    )
                except Exception as e:
                    logger.warning(f"Failed to insert vector: {e}")

            conn.commit()
            logger.info(
                f"Added strategy {strategy_id}: {error_pattern[:50] if error_pattern else 'empty'}..."
            )
            return strategy_id or 0
        except sqlite3.Error as e:
            logger.error(f"Failed to add strategy: {e}")
            if conn:
                conn.rollback()
            return 0
        finally:
            if conn:
                conn.close()

    def find_similar_strategies(
        self,
        error_pattern: str,
        language: str | None = None,
        top_k: int = 3,
    ) -> list[Strategy]:
        if top_k < 1:
            top_k = 1
        elif top_k > MAX_TOP_K:
            top_k = MAX_TOP_K

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM strategies
                WHERE (? IS NULL OR language = ?)
                ORDER BY usage_count DESC, success_rate DESC
                LIMIT ?
            """,
                (language, language, top_k),
            )

            rows = cursor.fetchall()
            return [
                Strategy(
                    id=row["id"],
                    error_pattern=row["error_pattern"],
                    root_cause=row["root_cause"],
                    solution_strategy=row["solution_strategy"],
                    language=row["language"],
                    success_rate=row["success_rate"],
                    usage_count=row["usage_count"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            logger.error(f"Failed to find similar strategies: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def find_by_pattern(self, pattern: str, language: str | None = None) -> list[Strategy]:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            search_pattern = f"%{pattern}%"
            cursor.execute(
                """
                SELECT * FROM strategies
                WHERE error_pattern LIKE ? AND (? IS NULL OR language = ?)
                ORDER BY usage_count DESC
                LIMIT 10
            """,
                (search_pattern, language, language),
            )

            rows = cursor.fetchall()
            return [
                Strategy(
                    id=row["id"],
                    error_pattern=row["error_pattern"],
                    root_cause=row["root_cause"],
                    solution_strategy=row["solution_strategy"],
                    language=row["language"],
                    success_rate=row["success_rate"],
                    usage_count=row["usage_count"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]
        except sqlite3.Error as e:
            logger.error(f"Failed to find by pattern: {e}")
            return []
        finally:
            if conn:
                conn.close()

    def increment_usage(self, strategy_id: int, success: bool) -> None:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                UPDATE strategies
                SET usage_count = usage_count + 1,
                    success_rate = CASE
                        WHEN usage_count = 0 THEN ?
                        ELSE (success_rate * usage_count + ?) / (usage_count + 1)
                    END,
                    updated_at = ?
                WHERE id = ?
            """,
                (
                    1.0 if success else 0.0,
                    1.0 if success else 0.0,
                    datetime.now().isoformat(),
                    strategy_id,
                ),
            )

            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to increment usage: {e}")
            if conn:
                conn.rollback()
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
                       SUM(usage_count) as total_usage,
                       AVG(success_rate) as avg_success
                FROM strategies
            """)

            row = cursor.fetchone()
            return {
                "total_strategies": row["total"] or 0,
                "total_usage": row["total_usage"] or 0,
                "average_success_rate": row["avg_success"] or 0.0,
            }
        except sqlite3.Error as e:
            logger.error(f"Failed to get statistics: {e}")
            return {"total_strategies": 0, "total_usage": 0, "average_success_rate": 0.0}
        finally:
            if conn:
                conn.close()

    def export_to_json(self, path: str) -> None:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM strategies")
            rows = cursor.fetchall()

            strategies = []
            for row in rows:
                strategies.append(
                    {
                        "error_pattern": row["error_pattern"],
                        "root_cause": row["root_cause"],
                        "solution_strategy": row["solution_strategy"],
                        "language": row["language"],
                        "success_rate": row["success_rate"],
                        "usage_count": row["usage_count"],
                    }
                )

            try:
                Path(path).write_text(json.dumps(strategies, indent=2), encoding="utf-8")
                logger.info(f"Exported {len(strategies)} strategies to {path}")
            except OSError as e:
                logger.error(f"Failed to write export file: {e}")
                raise
        except sqlite3.Error as e:
            logger.error(f"Failed to export strategies: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def import_from_json(self, path: str) -> int:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read import file: {e}")
            return 0

        if not isinstance(data, list):
            logger.error("Import data must be a list")
            return 0

        count = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            if (
                not item.get("error_pattern")
                or not item.get("root_cause")
                or not item.get("solution_strategy")
            ):
                continue
            self.add_strategy(
                error_pattern=item["error_pattern"],
                root_cause=item["root_cause"],
                solution_strategy=item["solution_strategy"],
                language=item.get("language"),
            )
            count += 1

        logger.info(f"Imported {count} strategies from {path}")
        return count

    def clear(self) -> None:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM strategies")
            conn.commit()
            logger.info("Cleared all strategies from knowledge base")
        except sqlite3.Error as e:
            logger.error(f"Failed to clear strategies: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()


class GlobalKnowledgeBase:
    def __init__(self, global_kb_path: str | None = None):
        self.global_path = (
            Path(global_kb_path) if global_kb_path else Path(GLOBAL_KB_DIR).expanduser()
        )
        try:
            self.global_path.mkdir(parents=True, exist_ok=True)
            self.strategy_kb = StrategyKB(str(self.global_path))
        except OSError as e:
            logger.error(f"Failed to initialize global knowledge base: {e}")
            raise

    def search(
        self,
        error_pattern: str,
        language: str | None = None,
        top_k: int = 5,
    ) -> list[Strategy]:
        return self.strategy_kb.find_similar_strategies(error_pattern, language, top_k)

    def add_solution(
        self,
        error_pattern: str,
        root_cause: str,
        solution: str,
        language: str | None = None,
    ) -> int:
        return self.strategy_kb.add_strategy(error_pattern, root_cause, solution, language)

    def contribute_to_community(self, export_path: str) -> None:
        self.strategy_kb.export_to_json(export_path)
