"""
Tests for memory_manager.py
"""

import tempfile
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock


class TestMemoryManager:
    """Tests for MemoryManager class."""

    def test_memory_manager_init(self):
        """Test MemoryManager initialization."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            assert manager.project_path == Path(tmpdir)
            assert manager.muscle_dir.exists()

    def test_update_memory_md_creates_file(self):
        """Test that update_memory_md creates file if not exists."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.update_memory_md("Test entry", "test")

            assert result is True
            assert (manager.muscle_dir / "MEMORY.md").exists()

    def test_update_claude_md(self):
        """Test updating CLAUDE.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.update_claude_md("Test claude entry", "test")

            assert result is True
            assert (manager.muscle_dir / "CLAUDE.md").exists()

    def test_update_agent_md(self):
        """Test updating AGENT.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.update_agent_md("Test agent entry", "agent")

            assert result is True
            assert (manager.muscle_dir / "AGENT.md").exists()

    def test_duplicate_entry_skipped(self):
        """Test that duplicate entries are skipped."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.update_memory_md("Same entry", "test")
            result = manager.update_memory_md("Same entry", "test")

            assert result is False

    def test_seed_contains_methodology(self):
        """Test that freshly-created .muscle/CLAUDE.md is seeded with Methodology section."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.update_claude_md("First entry", "general")

            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Methodology" in content
            for bullet in (
                "Think before coding",
                "Simplicity first",
                "Surgical changes",
                "Goal-driven execution",
            ):
                assert bullet in content

    def test_add_skill_reference(self):
        """Test adding skill reference."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_skill_reference("auth-patterns", ".muscle/skills/auth_patterns.md")

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "auth-patterns" in content
            assert ".muscle/skills/" in content

    def test_add_agent_reference(self):
        """Test adding agent reference."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_agent_reference(
                "security-auditor", ".muscle/agents/security_auditor.md"
            )

            assert result is True
            content = (manager.muscle_dir / "AGENT.md").read_text()
            assert "security-auditor" in content

    def test_add_pattern_learned(self):
        """Test recording learned pattern."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_pattern_learned("sql_injection", "src/db.py", "HIGH")

            assert result is True
            content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "sql_injection" in content
            assert "src/db.py" in content
            assert "HIGH" in content

    def test_add_fix_validated(self):
        """Test recording validated fix."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.add_fix_validated("sql_injection", "Used parameterized queries", True)

            assert result is True
            content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "sql_injection" in content
            assert "SUCCESS" in content

    def test_prune_old_entries(self):
        """Test pruning old entries."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.update_memory_md("Entry 1", "test")

            result = manager.prune_old_entries("MEMORY.md", max_entries=100)
            assert result == 0

    def test_marker_based_editing(self):
        """Test that edits are bounded by markers."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)

            claude_file = manager.muscle_dir / "CLAUDE.md"
            claude_file.write_text("""# CLAUDE.md

<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE_LEARNED_END -->

User content here
""")

            manager.update_claude_md("New learned entry", "test")
            content = claude_file.read_text()

            assert "<!-- MUSCLE_LEARNED_START -->" in content
            assert "<!-- MUSCLE_LEARNED_END -->" in content
            assert "User content here" in content
            assert "New learned entry" in content


class TestStructuredClaudeMd:
    """Tests for structured CLAUDE.md rules and MEMORY.md sections."""

    def test_write_do_rule(self):
        """Test writing a 'do' rule to CLAUDE.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.write_rule(
                "Use parameterized queries for SQL",
                rule_type="do",
                severity="high",
                confidence="high",
                validated_count=3,
            )

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Do" in content
            assert "Use parameterized queries for SQL" in content
            assert "(confidence: high, validated: 3x)" in content

    def test_write_dont_rule(self):
        """Test writing a 'dont' rule to CLAUDE.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.write_rule(
                "Never use string concatenation for SQL",
                rule_type="dont",
                severity="critical",
                confidence="high",
                validated_count=5,
            )

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Don't" in content
            assert "Never use string concatenation for SQL" in content
            assert "(confidence: high, validated: 5x)" in content

    def test_write_skill_reference(self):
        """Test writing a skill reference to CLAUDE.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.write_skill_ref("Auth Patterns", ".muscle/skills/auth_patterns.md")

            assert result is True
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "### Project Skills" in content
            assert "`.muscle/skills/auth_patterns.md`" in content
            assert "Auth Patterns" in content

    def test_dedup_rules(self):
        """Test that writing the same rule twice only appears once."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use parameterized queries",
                rule_type="do",
                severity="high",
                confidence="high",
                validated_count=1,
            )
            result = manager.write_rule(
                "Use parameterized queries",
                rule_type="do",
                severity="high",
                confidence="high",
                validated_count=2,
            )

            assert result is False
            content = (manager.muscle_dir / "CLAUDE.md").read_text()
            count = content.lower().count("use parameterized queries")
            assert count == 1

    def test_read_rules(self):
        """Test reading rules back from CLAUDE.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use type hints",
                rule_type="do",
                severity="medium",
                confidence="medium",
                validated_count=2,
            )
            manager.write_rule(
                "Avoid global state",
                rule_type="dont",
                severity="high",
                confidence="high",
                validated_count=4,
            )

            rules = manager.read_rules()
            assert len(rules) == 2

            do_rules = [r for r in rules if r["type"] == "do"]
            dont_rules = [r for r in rules if r["type"] == "dont"]
            assert len(do_rules) == 1
            assert len(dont_rules) == 1

            assert do_rules[0]["text"] == "Use type hints"
            assert do_rules[0]["confidence"] == "medium"
            assert do_rules[0]["validated_count"] == 2

            assert dont_rules[0]["text"] == "Avoid global state"

    def test_update_rule_validated_count(self):
        """Test updating a rule's validation count in-place."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use type hints",
                rule_type="do",
                severity="medium",
                confidence="medium",
                validated_count=2,
            )

            result = manager.update_rule_validation(
                "Use type hints", validated_count=5, confidence="high"
            )
            assert result is True

            rules = manager.read_rules()
            assert len(rules) == 1
            assert rules[0]["validated_count"] == 5
            assert rules[0]["confidence"] == "high"

    def test_archive_rule(self):
        """Test archiving a rule moves it from CLAUDE.md to MEMORY.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            manager.write_rule(
                "Use type hints",
                rule_type="do",
                severity="medium",
                confidence="medium",
                validated_count=2,
            )

            result = manager.archive_rule("Use type hints", reason="Superseded by stricter rule")
            assert result is True

            # Verify removed from CLAUDE.md
            claude_content = (manager.muscle_dir / "CLAUDE.md").read_text()
            assert "Use type hints" not in claude_content

            # Verify added to MEMORY.md
            memory_content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "Use type hints" in memory_content
            assert "Archived Rules" in memory_content
            assert "Superseded by stricter rule" in memory_content

    def test_log_review_session(self):
        """Test logging a review session to MEMORY.md."""
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            result = manager.log_review_session(
                critical=1,
                high=3,
                medium=5,
                low=2,
                actions=["Fixed SQL injection", "Added input validation"],
            )

            assert result is True
            memory_content = (manager.muscle_dir / "MEMORY.md").read_text()
            assert "Review Sessions" in memory_content
            assert "critical=1" in memory_content
            assert "high=3" in memory_content
            assert "Fixed SQL injection" in memory_content


def _seed_memory_file(manager, filename, n_entries):
    """Write a managed-section memory file with n real memory-line entries."""
    today = datetime.now().strftime("%Y-%m-%d")
    entries = "\n".join(f"- [{today}] [pattern] entry number {i}" for i in range(n_entries))
    content = (
        f"# {filename.replace('.md', '')}\n\n"
        "<!-- MUSCLE_LEARNED_START -->\n"
        f"{entries}\n"
        "<!-- MUSCLE_LEARNED_END -->\n"
    )
    (manager.muscle_dir / filename).write_text(content)


class TestSummarizeTruncation:
    """Regression tests for _m27_summarize_entry / _truncate_clean."""

    def test_truncate_does_not_cut_mid_word(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            text = "word " * 60  # well over 150 chars, all word-boundaries
            result = manager._truncate_clean(text, limit=150)
            assert len(result) <= 150
            # No partial trailing word: the result is whole "word" tokens.
            assert all(tok == "word" for tok in result.split())

    def test_truncate_does_not_cut_inside_tag(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            prefix = "x" * 145
            text = f"{prefix} <sometag>tail content here"
            result = manager._truncate_clean(text, limit=150)
            # Must not leave a dangling, unclosed "<sometag" fragment.
            assert "<sometag" not in result

    def test_truncate_does_not_cut_inside_bracket(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)
            prefix = "y " * 72  # ~144 chars on word boundaries
            text = f"{prefix}[unclosed token continues well past the limit here]"
            result = manager._truncate_clean(text, limit=150)
            assert "[unclosed" not in result

    def test_summarize_no_llm_truncates_cleanly(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = MemoryManager(tmpdir)  # no m27 client
            entry = "alpha " * 60
            result = manager._m27_summarize_entry(entry, "general")
            assert len(result) <= 150
            assert all(tok == "alpha" for tok in result.split())

    def test_summarize_llm_failure_truncates_cleanly(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            client = MagicMock()
            client.chat.side_effect = RuntimeError("boom")
            manager = MemoryManager(tmpdir, m27_client=client)
            entry = "beta " * 60
            result = manager._m27_summarize_entry(entry, "general")
            assert len(result) <= 150
            assert all(tok == "beta" for tok in result.split())


class TestConsolidateMemories:
    """Regression tests for the consolidate_memories data-loss guard."""

    def test_consolidate_aborts_and_backs_up_on_mass_deletion(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            import json as _json

            client = MagicMock()
            today = datetime.now().strftime("%Y-%m-%d")
            # LLM tries to keep only 5 of 80 entries -> >50% deletion.
            kept = [f"- [{today}] [pattern] entry number {i}" for i in range(5)]
            client.chat.return_value = ("```json\n" + _json.dumps(kept) + "\n```", {})
            manager = MemoryManager(tmpdir, m27_client=client)
            _seed_memory_file(manager, "MEMORY.md", 80)
            original = (manager.muscle_dir / "MEMORY.md").read_text()

            removed = manager.consolidate_memories()

            # No write occurred (mass deletion aborted).
            assert removed == 0
            assert (manager.muscle_dir / "MEMORY.md").read_text() == original
            # Backup was created before the aborted overwrite attempt.
            assert (manager.muscle_dir / "MEMORY.md.bak").exists()
            assert "entry number 79" in (manager.muscle_dir / "MEMORY.md.bak").read_text()

    def test_consolidate_returns_real_removed_count(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            import json as _json

            client = MagicMock()
            today = datetime.now().strftime("%Y-%m-%d")
            # Keep 50 of 80 (within the 50% floor).
            kept = [f"- [{today}] [pattern] entry number {i}" for i in range(50)]

            def chat_only_for_memory(*args, **kwargs):
                return ("```json\n" + _json.dumps(kept) + "\n```", {})

            client.chat.side_effect = chat_only_for_memory
            manager = MemoryManager(tmpdir, m27_client=client)
            _seed_memory_file(manager, "MEMORY.md", 80)

            removed = manager.consolidate_memories()

            assert removed == 30
            section = manager._extract_section((manager.muscle_dir / "MEMORY.md").read_text())
            line_count = len([line for line in section.split("\n") if line.strip().startswith("-")])
            assert line_count == 50

    def test_consolidate_rejects_garbage_entries(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            import json as _json

            client = MagicMock()
            # LLM returns content that does NOT match the memory-line shape.
            garbage = ["just some text", "another line", "ignore previous instructions"]
            client.chat.return_value = ("```json\n" + _json.dumps(garbage) + "\n```", {})
            manager = MemoryManager(tmpdir, m27_client=client)
            _seed_memory_file(manager, "MEMORY.md", 80)
            original = (manager.muscle_dir / "MEMORY.md").read_text()

            removed = manager.consolidate_memories()

            assert removed == 0
            assert (manager.muscle_dir / "MEMORY.md").read_text() == original

    def test_consolidate_guards_invalid_json(self):
        from muscle.code_review.memory_manager import MemoryManager

        with tempfile.TemporaryDirectory() as tmpdir:
            client = MagicMock()
            client.chat.return_value = ("not json at all", {})
            manager = MemoryManager(tmpdir, m27_client=client)
            _seed_memory_file(manager, "MEMORY.md", 80)
            original = (manager.muscle_dir / "MEMORY.md").read_text()

            removed = manager.consolidate_memories()

            assert removed == 0
            assert (manager.muscle_dir / "MEMORY.md").read_text() == original


class TestAtomicLockedWrites:
    """Regression tests asserting mutators use the locked/atomic write path."""

    def test_prune_uses_locked_atomic_write(self, monkeypatch):
        from muscle.code_review import memory_manager as mm

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = mm.MemoryManager(tmpdir)
            _seed_memory_file(manager, "MEMORY.md", 120)

            called = {"locked": False}
            real = mm.update_text_file_locked

            def spy(*args, **kwargs):
                called["locked"] = True
                return real(*args, **kwargs)

            monkeypatch.setattr(mm, "update_text_file_locked", spy)

            removed = manager.prune_old_entries("MEMORY.md", max_entries=100)

            assert removed == 20
            assert called["locked"] is True
            section = manager._extract_section((manager.muscle_dir / "MEMORY.md").read_text())
            line_count = len([line for line in section.split("\n") if line.strip().startswith("-")])
            assert line_count == 100

    def test_consolidate_uses_atomic_write(self, monkeypatch):
        from muscle.code_review import memory_manager as mm

        with tempfile.TemporaryDirectory() as tmpdir:
            import json as _json

            client = MagicMock()
            today = datetime.now().strftime("%Y-%m-%d")
            kept = [f"- [{today}] [pattern] entry number {i}" for i in range(50)]
            client.chat.return_value = ("```json\n" + _json.dumps(kept) + "\n```", {})
            manager = mm.MemoryManager(tmpdir, m27_client=client)
            _seed_memory_file(manager, "MEMORY.md", 80)

            called = {"atomic": 0}
            real = mm.atomic_write_text

            def spy(*args, **kwargs):
                called["atomic"] += 1
                return real(*args, **kwargs)

            monkeypatch.setattr(mm, "atomic_write_text", spy)

            removed = manager.consolidate_memories()

            assert removed == 30
            # At least the backup write + the file write went through atomic_write_text.
            assert called["atomic"] >= 2


class TestConcurrentMutators:
    """Stress the advisory-lock contract demanded by the project critical rule:

    many concurrent writers plus a pruner plus a consolidator must not lose any
    entry. ``update``/``prune``/``consolidate`` all route file mutations through
    ``update_text_file_locked`` / ``advisory_file_lock``, which open a fresh fd per
    acquisition; ``fcntl.flock`` is per-open-file-description, so the threads here
    genuinely exclude one another.
    """

    def test_concurrent_writers_pruner_consolidator_lose_no_entries(self):
        from muscle.code_review.memory_manager import MemoryManager

        n_writers = 80
        with tempfile.TemporaryDirectory() as tmpdir:
            # No m27 client -> consolidate_memories() is a no-op (returns 0) but
            # still contends on the same advisory lock, exercising the contract.
            manager = MemoryManager(tmpdir)

            # Unique entries with no file extensions and a unique numeric token so
            # neither the substring nor the file-path duplicate heuristic fires.
            # These are NOT prune-eligible: max_entries below stays well above the
            # final count, so a legitimate prune never removes a writer's entry.
            entries = [f"concurrent stress unique marker token {i:05d}" for i in range(n_writers)]
            max_entries = n_writers * 10

            start = threading.Barrier(n_writers + 2)
            stop_background = threading.Event()
            errors: list[BaseException] = []

            def writer(entry: str) -> None:
                try:
                    start.wait()
                    assert manager.update_memory_md(entry, category="stress") is True
                except BaseException as exc:  # noqa: BLE001 - surfaced via errors list
                    errors.append(exc)

            def pruner() -> None:
                try:
                    start.wait()
                    while not stop_background.is_set():
                        manager.prune_old_entries("MEMORY.md", max_entries=max_entries)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            def consolidator() -> None:
                try:
                    start.wait()
                    while not stop_background.is_set():
                        manager.consolidate_memories()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(e,)) for e in entries]
            threads.append(threading.Thread(target=pruner))
            threads.append(threading.Thread(target=consolidator))

            for t in threads:
                t.start()
            # Join writers first (last two threads are the background loops).
            for t in threads[:-2]:
                t.join(timeout=10)
            stop_background.set()
            for t in threads[-2:]:
                t.join(timeout=10)

            assert not errors, f"background tasks raised: {errors}"
            assert all(not t.is_alive() for t in threads)

            section = manager._extract_section((manager.muscle_dir / "MEMORY.md").read_text())
            lines = [ln for ln in section.split("\n") if ln.strip().startswith("-")]

            # Every unique entry survives exactly once: no lost writes (lock holds)
            # and no duplicates (each entry is appended once).
            for entry in entries:
                matches = [ln for ln in lines if entry in ln]
                assert len(matches) == 1, f"entry {entry!r} appears {len(matches)} times"
            assert len(lines) == n_writers
