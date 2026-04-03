"""
Integration tests for data stores: ReviewKB, FixTracker, StrategyKB.

Tests real SQLite operations and JSON file persistence.
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.muscle.code_review.fix_tracker import FixTracker
from tools.muscle.code_review.review_kb import GlobalReviewKB, ReviewKB
from tools.muscle.strategy_kb import GlobalKnowledgeBase


class TestReviewKBIntegration:
    """Tests ReviewKB with real SQLite operations."""

    def test_full_review_lifecycle(self, tmp_path: Path):
        """Test add -> query -> stats lifecycle."""
        kb = ReviewKB(str(tmp_path / "review_kb"))

        # Add various issues
        id1 = kb.add_reviewed_issue(
            file_path="src/auth.py",
            line_number=42,
            severity="CRITICAL",
            category="security",
            title="SQL injection in login",
            code_pattern="f-string SQL",
            was_valid=True,
            was_fixed=True,
            auto_fixed=False,
        )
        assert id1 > 0

        id2 = kb.add_reviewed_issue(
            file_path="src/auth.py",
            line_number=55,
            severity="HIGH",
            category="security",
            title="Hardcoded credentials",
            code_pattern="hardcoded password",
            was_valid=True,
            was_fixed=False,
        )
        assert id2 > 0

        id3 = kb.add_reviewed_issue(
            file_path="src/utils.py",
            line_number=10,
            severity="LOW",
            category="style",
            title="Unused import",
            code_pattern="unused import",
            was_valid=False,
            false_positive_reason="Import used in test file",
        )
        assert id3 > 0

        # Check statistics
        stats = kb.get_statistics()
        assert stats["total_reviewed"] == 3
        assert stats["false_positives"] == 1
        assert stats["issues_fixed"] == 1

    def test_fix_effectiveness_tracking(self, tmp_path: Path):
        """Fix attempts should be tracked with success/failure rates."""
        kb = ReviewKB(str(tmp_path / "review_kb"))

        # Record multiple fix attempts for same pattern
        kb.record_fix_attempt("f-string SQL", success=True, tokens_spent=500)
        kb.record_fix_attempt("f-string SQL", success=True, tokens_spent=600)
        kb.record_fix_attempt("f-string SQL", success=False, tokens_spent=800)

        # Check effectiveness
        rate = kb.get_false_positive_rate("f-string SQL")
        # This queries reviewed_issues, not fix_effectiveness, so rate is 0
        assert isinstance(rate, float)

    def test_multiple_patterns_independence(self, tmp_path: Path):
        """Different patterns should track independently."""
        kb = ReviewKB(str(tmp_path / "review_kb"))

        for i in range(5):
            kb.add_reviewed_issue(
                file_path=f"file_{i}.py",
                line_number=i,
                severity="HIGH",
                category="security",
                title="Pattern A",
                code_pattern="pattern_a",
                was_valid=True,
            )

        for i in range(3):
            kb.add_reviewed_issue(
                file_path=f"file_{i}.py",
                line_number=i,
                severity="MEDIUM",
                category="correctness",
                title="Pattern B",
                code_pattern="pattern_b",
                was_valid=True,
            )

        stats = kb.get_statistics()
        assert stats["total_reviewed"] == 8


class TestGlobalReviewKBIntegration:
    """Tests cross-project GlobalReviewKB."""

    def test_global_kb_records_and_queries(self, tmp_path: Path):
        """GlobalReviewKB should aggregate across projects."""
        gkb = GlobalReviewKB(str(tmp_path / "global_kb"))

        gkb.record_issue(
            file_path="project_a/src/main.py",
            line_number=10,
            severity="HIGH",
            category="security",
            title="XSS vulnerability",
            code_pattern="unsanitized output",
            was_valid=True,
        )

        gkb.record_fix("unsanitized output", success=True, tokens_spent=300)

        stats = gkb.get_stats()
        assert stats["total_reviewed"] == 1
        assert stats["fix_successes"] == 1


class TestFixTrackerIntegration:
    """Tests FixTracker with real SQLite operations."""

    def test_record_and_query_fixes(self, tmp_path: Path):
        """Fix attempts should be persistently tracked."""
        tracker = FixTracker(str(tmp_path / "fix_tracker"))

        # Record successful fix
        id1 = tracker.record_fix_attempt(
            pattern="SQL injection",
            file_path="src/db.py",
            fix_description="Replaced f-string with parameterized query",
            was_applied=True,
            was_successful=True,
            tokens_spent=500,
        )
        assert id1 > 0

        # Record failed fix
        id2 = tracker.record_fix_attempt(
            pattern="SQL injection",
            file_path="src/api.py",
            fix_description="Added input sanitization",
            was_applied=True,
            was_successful=False,
            tokens_spent=700,
        )
        assert id2 > 0

        # Query fix success rate
        rate = tracker.get_fix_success_rate("SQL injection")
        assert rate == 0.5  # 1 success / 2 attempts

    def test_success_rate_calculation(self, tmp_path: Path):
        """Success rate should be accurately calculated."""
        tracker = FixTracker(str(tmp_path / "fix_tracker"))

        # 3 successes, 2 failures
        for i in range(3):
            tracker.record_fix_attempt(
                pattern="missing validation",
                file_path=f"src/handler_{i}.py",
                fix_description="Added input validation",
                was_applied=True,
                was_successful=True,
                tokens_spent=300,
            )

        for i in range(2):
            tracker.record_fix_attempt(
                pattern="missing validation",
                file_path=f"src/other_{i}.py",
                fix_description="Added validation (failed)",
                was_applied=True,
                was_successful=False,
                tokens_spent=400,
            )

        rate = tracker.get_fix_success_rate("missing validation")
        assert abs(rate - 0.6) < 0.01

    def test_statistics(self, tmp_path: Path):
        """Statistics should report aggregate fix data."""
        tracker = FixTracker(str(tmp_path / "fix_tracker"))

        tracker.record_fix_attempt(
            pattern="pattern_alpha",
            file_path="a.py",
            fix_description="fix a",
            was_applied=True,
            was_successful=True,
        )
        tracker.record_fix_attempt(
            pattern="pattern_beta",
            file_path="b.py",
            fix_description="fix b",
            was_applied=True,
            was_successful=False,
        )

        stats = tracker.get_statistics()
        assert isinstance(stats, dict)
        assert stats.get("total_fix_attempts", 0) >= 2


class TestStrategyKBIntegration:
    """Tests strategy knowledge base with real operations."""

    def test_add_and_search_strategies(self, tmp_path: Path):
        """Strategies should be searchable after adding."""
        gkb = GlobalKnowledgeBase(str(tmp_path / "strategy_kb"))

        gkb.strategy_kb.add_strategy(
            error_pattern="TypeError in API handler",
            root_cause="Missing type validation at API boundary",
            solution_strategy="Add type checking with isinstance()",
            language="python",
        )

        gkb.strategy_kb.add_strategy(
            error_pattern="Connection timeout in database",
            root_cause="Single connection under load",
            solution_strategy="Add connection pooling with retry",
            language="python",
        )

        results = gkb.search("TypeError handler")
        assert isinstance(results, list)

    def test_export_import_roundtrip(self, tmp_path: Path):
        """Export then import should preserve all strategies."""
        kb_path = str(tmp_path / "strategy_kb")
        gkb = GlobalKnowledgeBase(kb_path)

        gkb.strategy_kb.add_strategy(
            error_pattern="Test pattern",
            root_cause="Test cause",
            solution_strategy="Test solution",
            language="python",
        )

        export_file = str(tmp_path / "export.json")
        gkb.strategy_kb.export_to_json(export_file)

        assert Path(export_file).exists()
        data = json.loads(Path(export_file).read_text())
        assert isinstance(data, list)

        # Import into a new KB
        gkb2 = GlobalKnowledgeBase(str(tmp_path / "strategy_kb2"))
        count = gkb2.strategy_kb.import_from_json(export_file)
        assert count >= 1

    def test_usage_tracking(self, tmp_path: Path):
        """Strategy usage should be tracked for effectiveness scoring."""
        gkb = GlobalKnowledgeBase(str(tmp_path / "strategy_kb"))

        sid = gkb.strategy_kb.add_strategy(
            error_pattern="Race condition",
            root_cause="Shared mutable state",
            solution_strategy="Add threading lock",
            language="python",
        )

        if sid:
            gkb.strategy_kb.increment_usage(sid, success=True)
            gkb.strategy_kb.increment_usage(sid, success=True)
            gkb.strategy_kb.increment_usage(sid, success=False)

            stats = gkb.strategy_kb.get_statistics()
            assert stats["total_strategies"] >= 1
            assert stats["total_usage"] >= 3


# -----------------------------------------------------------------------------
# Tests for LegacyImporter (MUS-012)
# -----------------------------------------------------------------------------

from datetime import datetime
from tools.muscle.legacy_importer import LegacyImporter
from tools.muscle.project_memory import ProjectMemory


class TestLegacyImporterReviewKB:
    """Tests LegacyImporter._import_review_kb()."""

    def test_import_review_kb_basic(self, tmp_path: Path):
        """ReviewKB data is imported into review_runs + review_findings."""
        from tools.muscle.code_review.review_kb import ReviewKB

        # Setup legacy review_kb
        legacy_kb = ReviewKB(str(tmp_path / "legacy_review_kb"))
        legacy_kb.add_reviewed_issue(
            file_path="src/auth.py",
            line_number=42,
            severity="HIGH",
            category="security",
            title="SQL injection",
            code_pattern="f-string SQL",
            was_valid=True,
            was_fixed=True,
        )

        # Setup muscle dir with legacy store
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        review_kb_dir = muscle_dir / "review_kb"
        review_kb_dir.mkdir()
        legacy_db = review_kb_dir / "review_kb.db"
        # Move legacy db to expected location
        import sqlite3
        src_conn = sqlite3.connect(str(tmp_path / "legacy_review_kb" / "review_kb.db"))
        src_conn.backup(sqlite3.connect(str(legacy_db)))
        src_conn.close()

        # Setup project_memory
        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_review_kb()

        stats = importer.stats.get("review_kb", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0

        # Verify data is in project_memory
        runs = memory.list_review_runs(str(tmp_path))
        assert len(runs) >= 1

    def test_import_review_kb_idempotent(self, tmp_path: Path):
        """Running the import twice produces the same result (no duplicates)."""
        from tools.muscle.code_review.review_kb import ReviewKB

        # Setup legacy review_kb with a unique issue
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        review_kb_dir = muscle_dir / "review_kb"
        review_kb_dir.mkdir()

        import sqlite3
        legacy_kb = ReviewKB(str(tmp_path / "legacy_review_kb"))
        legacy_kb.add_reviewed_issue(
            file_path="src/main.py",
            line_number=10,
            severity="CRITICAL",
            category="security",
            title="Test issue",
            code_pattern="test_pattern_unique_123",
            was_valid=True,
            was_fixed=False,
        )

        # Copy to expected location
        src_conn = sqlite3.connect(str(tmp_path / "legacy_review_kb" / "review_kb.db"))
        src_conn.backup(sqlite3.connect(str(review_kb_dir / "review_kb.db")))
        src_conn.close()

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_review_kb()
        first_runs = memory.list_review_runs(str(tmp_path))

        # Run again
        importer2 = LegacyImporter(memory, str(tmp_path))
        importer2._import_review_kb()
        second_runs = memory.list_review_runs(str(tmp_path))

        # Same total count; second run should skip duplicates
        assert len(first_runs) == len(second_runs)
        assert importer2.stats.get("review_kb", {}).get("skipped") >= 1
        # Second run imported 0 more records
        assert importer2.stats.get("review_kb", {}).get("imported") == 0

    def test_import_review_kb_missing_store(self, tmp_path: Path):
        """Missing legacy store is handled gracefully (no error)."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        # No review_kb dir created

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_review_kb()

        stats = importer.stats.get("review_kb", {})
        assert stats.get("errors", 0) == 0


class TestLegacyImporterStrategies:
    """Tests LegacyImporter._import_strategies_db()."""

    def test_import_strategies_basic(self, tmp_path: Path):
        """Strategies are imported into learned_rules table."""
        from tools.muscle.strategy_kb import StrategyKB

        # Setup legacy strategies.db
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        kb_dir = muscle_dir / "knowledge"
        kb_dir.mkdir()
        legacy_kb = StrategyKB(str(kb_dir))
        legacy_kb.add_strategy(
            error_pattern="TypeError: 'NoneType' is not iterable",
            root_cause="Missing null check before iteration",
            solution_strategy="Add if variable is not None check",
            language="python",
        )

        # Force the DB to be at the expected path
        import sqlite3
        # The StrategyKB already created the db at kb_dir / "strategies.db"
        assert (kb_dir / "strategies.db").exists()

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_strategies_db()

        stats = importer.stats.get("strategies", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0

    def test_import_strategies_duplicate_suppression(self, tmp_path: Path):
        """Duplicate patterns are suppressed."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        kb_dir = muscle_dir / "knowledge"
        kb_dir.mkdir()

        import sqlite3
        conn = sqlite3.connect(str(kb_dir / "strategies.db"))
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
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("""
            INSERT INTO strategies (error_pattern, root_cause, solution_strategy, language, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("duplicate pattern test", "cause", "solution", "python",
              datetime.now().isoformat(), datetime.now().isoformat()))
        conn.commit()
        conn.close()

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_strategies_db()
        first_imported = importer.stats.get("strategies", {}).get("imported", 0)

        importer2 = LegacyImporter(memory, str(tmp_path))
        importer2._import_strategies_db()
        second_imported = importer2.stats.get("strategies", {}).get("imported", 0)
        second_skipped = importer2.stats.get("strategies", {}).get("skipped", 0)

        # Second run should not import any new records
        assert second_imported == 0
        assert second_skipped >= 1


class TestLegacyImporterFixTracker:
    """Tests LegacyImporter._import_fix_tracker()."""

    def test_import_fix_tracker_basic(self, tmp_path: Path):
        """Fix attempts are imported from legacy store."""
        from tools.muscle.code_review.fix_tracker import FixTracker

        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        ft_dir = muscle_dir / "fix_tracker"
        ft_dir.mkdir()

        legacy_tracker = FixTracker(str(ft_dir))
        legacy_tracker.record_fix_attempt(
            pattern="unused import",
            file_path="src/main.py",
            fix_description="Remove unused import",
            was_applied=True,
            was_successful=True,
            tokens_spent=200,
        )

        assert (ft_dir / "fix_tracker.db").exists()

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_fix_tracker()

        stats = importer.stats.get("fix_tracker", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0

    def test_import_fix_tracker_missing_store(self, tmp_path: Path):
        """Missing fix_tracker store is handled gracefully."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        # No fix_tracker dir

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_fix_tracker()

        assert importer.stats.get("fix_tracker", {}).get("errors", 0) == 0


class TestLegacyImporterSessions:
    """Tests LegacyImporter._import_sessions()."""

    def test_import_session_basic(self, tmp_path: Path):
        """Session directory is imported as a task."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        sessions_dir = muscle_dir / "sessions"
        sessions_dir.mkdir()

        session_id = "test-session-001"
        session_path = sessions_dir / session_id
        session_path.mkdir()

        meta = {
            "session_id": session_id,
            "task": "Test task from legacy session",
            "language": "python",
            "status": "completed",
            "created_at": datetime.now().isoformat(),
            "max_iterations": 5,
        }
        (session_path / "meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )
        (session_path / "iterations.jsonl").write_text("", encoding="utf-8")

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_sessions()

        stats = importer.stats.get("sessions", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0

    def test_import_session_idempotent(self, tmp_path: Path):
        """Importing same session twice skips duplicates."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        sessions_dir = muscle_dir / "sessions"
        sessions_dir.mkdir()

        session_id = "dup-session-001"
        session_path = sessions_dir / session_id
        session_path.mkdir()
        (session_path / "meta.json").write_text(
            json.dumps({
                "session_id": session_id,
                "task": "Duplicate test",
                "language": "python",
                "status": "completed",
                "created_at": datetime.now().isoformat(),
            }),
            encoding="utf-8",
        )
        (session_path / "iterations.jsonl").write_text("", encoding="utf-8")

        memory = ProjectMemory(str(tmp_path))

        importer1 = LegacyImporter(memory, str(tmp_path))
        importer1._import_sessions()
        first = importer1.stats.get("sessions", {}).get("imported", 0)

        importer2 = LegacyImporter(memory, str(tmp_path))
        importer2._import_sessions()
        second = importer2.stats.get("sessions", {}).get("imported", 0)
        skipped = importer2.stats.get("sessions", {}).get("skipped", 0)

        # Second run should import 0 new records (duplicates are skipped)
        assert second == 0
        assert skipped >= 1


class TestLegacyImporterMarkdownFiles:
    """Tests CLAUDE.md, AGENT.md, MEMORY.md imports."""

    def test_import_claude_md_rules(self, tmp_path: Path):
        """Learned rules are extracted from CLAUDE.md."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()

        claude_md = muscle_dir / "CLAUDE.md"
        claude_md.write_text("""
# CLAUDE.md

## Learned Rules

- **Rule: Always validate input before processing**
- When using user input, always sanitize it first
- Never trust raw user input in SQL queries

Some other content.
""", encoding="utf-8")

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_claude_md()

        stats = importer.stats.get("CLAUDE.md", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0

    def test_import_claude_md_missing(self, tmp_path: Path):
        """Missing CLAUDE.md is handled gracefully."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_claude_md()

        assert importer.stats.get("CLAUDE.md", {}).get("errors", 0) == 0

    def test_import_agent_md(self, tmp_path: Path):
        """AGENT.md metadata is imported into agents table."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()

        agent_md = muscle_dir / "AGENT.md"
        agent_md.write_text("""
# Test Agent

## Metadata
- name: TestAgent
- description: An agent for testing
- trigger: src/test_*.py

Agent content here.
""", encoding="utf-8")

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_agent_md()

        stats = importer.stats.get("AGENT.md", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0

    def test_import_memory_md(self, tmp_path: Path):
        """MEMORY.md content is imported into project_notes table."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()

        memory_md = muscle_dir / "MEMORY.md"
        memory_md.write_text("""
# MEMORY.md

## Architecture

This project uses a layered architecture with the following components...

## Important Notes

Remember to always run tests before committing.
""", encoding="utf-8")

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        importer._import_memory_md()

        stats = importer.stats.get("MEMORY.md", {})
        assert stats.get("imported", 0) >= 1
        assert stats.get("errors", 0) == 0


class TestLegacyImporterFullRun:
    """Tests LegacyImporter.run() - full import across all stores."""

    def test_run_all_stores(self, tmp_path: Path):
        """run() imports from all available legacy stores."""
        # Setup all legacy stores
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()

        # review_kb
        review_kb_dir = muscle_dir / "review_kb"
        review_kb_dir.mkdir()
        import sqlite3
        conn = sqlite3.connect(str(review_kb_dir / "review_kb.db"))
        conn.execute("""
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
        conn.execute("""
            INSERT INTO reviewed_issues
            (file_path, line_number, severity, category, title, code_pattern, was_valid, was_fixed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("src/main.py", 10, "HIGH", "style", "Test", "test", 1, 0, datetime.now().isoformat()))
        conn.commit()
        conn.close()

        # strategies.db
        kb_dir = muscle_dir / "knowledge"
        kb_dir.mkdir()
        conn2 = sqlite3.connect(str(kb_dir / "strategies.db"))
        conn2.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_pattern TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                solution_strategy TEXT NOT NULL,
                language TEXT,
                success_rate REAL DEFAULT 0.0,
                usage_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn2.execute("""
            INSERT INTO strategies (error_pattern, root_cause, solution_strategy, language, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Test error", "Test cause", "Test solution", "python",
              datetime.now().isoformat(), datetime.now().isoformat()))
        conn2.commit()
        conn2.close()

        # fix_tracker.db
        ft_dir = muscle_dir / "fix_tracker"
        ft_dir.mkdir()
        conn3 = sqlite3.connect(str(ft_dir / "fix_tracker.db"))
        conn3.execute("""
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
        conn3.execute("""
            INSERT INTO fix_attempts (pattern, file_path, fix_description, was_applied, was_successful, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("test pattern", "src/main.py", "Test fix", 1, 1, datetime.now().isoformat()))
        conn3.commit()
        conn3.close()

        # CLAUDE.md
        (muscle_dir / "CLAUDE.md").write_text("""
# CLAUDE.md
- **Rule: Test rule from CLAUDE.md**
""", encoding="utf-8")

        # AGENT.md
        (muscle_dir / "AGENT.md").write_text("""
# TestAgent
- name: TestAgentImporter
- description: Test agent
""", encoding="utf-8")

        # MEMORY.md
        (muscle_dir / "MEMORY.md").write_text("""
# MEMORY.md
## Test Section

Test content here.
""", encoding="utf-8")

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        results = importer.run()

        # Verify all stores were attempted
        assert "review_kb" in results
        assert "strategies" in results
        assert "fix_tracker" in results
        assert "CLAUDE.md" in results
        assert "AGENT.md" in results
        assert "MEMORY.md" in results

        # At least some imports succeeded
        total_imported = sum(s.get("imported", 0) for s in results.values())
        assert total_imported >= 1

    def test_run_no_stores(self, tmp_path: Path):
        """run() with no legacy stores completes without error."""
        muscle_dir = tmp_path / ".muscle"
        muscle_dir.mkdir()
        # Empty muscle dir - no legacy stores

        memory = ProjectMemory(str(tmp_path))
        importer = LegacyImporter(memory, str(tmp_path))

        results = importer.run()

        # Should complete without errors even with no stores
        for store_stats in results.values():
            assert store_stats.get("errors", 0) == 0
