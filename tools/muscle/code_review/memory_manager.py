"""
Memory Manager - Updates CLAUDE.md, AGENT.md, and MEMORY.md with learnings.

Uses marker-based editing to only modify MUSCLE-managed sections.

Architecture Decision Record (ADR):
- Bounded edits via markers prevent corruption of user content
- Deduplication before adding new entries
- Pruning of old entries when superseded
- Structured format for easy parsing
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_START = "<!-- MUSCLE_LEARNED_START -->"
MARKER_END = "<!-- MUSCLE_LEARNED_END -->"


class MemoryManager:
    LEARNED_START = "<!-- MUSCLE_LEARNED_START -->"
    LEARNED_END = "<!-- MUSCLE_LEARNED_END -->"

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.muscle_dir = self.project_path / ".muscle"
        self.muscle_dir.mkdir(parents=True, exist_ok=True)

    def update_claude_md(self, entry: str, category: str = "general") -> bool:
        """Add an entry to CLAUDE.md within markers."""
        return self._update_memory_file("CLAUDE.md", entry, category)

    def update_agent_md(self, entry: str, category: str = "agent") -> bool:
        """Add an entry to AGENT.md within markers."""
        return self._update_memory_file("AGENT.md", entry, category)

    def update_memory_md(self, entry: str, category: str = "learned") -> bool:
        """Add an entry to MEMORY.md within markers."""
        return self._update_memory_file("MEMORY.md", entry, category)

    def _update_memory_file(self, filename: str, entry: str, category: str) -> bool:
        filepath = self.muscle_dir / filename

        if not filepath.exists():
            filepath.write_text(self._create_file_with_markers(category))

        content = filepath.read_text()
        existing = self._extract_section(content)

        if self._is_duplicate(existing, entry):
            logger.debug(f"Duplicate entry in {filename}, skipping")
            return False

        new_entry = self._format_entry(entry, category)
        updated_content = self._insert_entry(content, new_entry, category)

        filepath.write_text(updated_content)
        logger.info(f"Updated {filename} with {category} entry")
        return True

    def _create_file_with_markers(self, filename: str) -> str:
        return f"""# {filename.replace(".md", "")}

<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE managed section - DO NOT EDIT OUTSIDE MARKERS -->
<!-- MUSCLE_LEARNED_END -->
"""

    def _extract_section(self, content: str) -> str:
        match = re.search(
            rf"{re.escape(self.LEARNED_START)}(.*?){re.escape(self.LEARNED_END)}",
            content,
            re.DOTALL,
        )
        return match.group(1) if match else ""

    def _is_duplicate(self, section: str, entry: str) -> bool:
        entry_lower = entry.lower().strip()
        for line in section.split("\n"):
            if entry_lower in line.lower():
                return True
        return False

    def _format_entry(self, entry: str, category: str) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d")
        return f"- [{timestamp}] [{category}] {entry}"

    def _insert_entry(self, content: str, new_entry: str, category: str) -> str:
        pattern = rf"({re.escape(self.LEARNED_START)}\n)(.*?)({re.escape(self.LEARNED_END)})"

        def replacement(match: re.Match[str]) -> str:
            start = match.group(1)
            existing = match.group(2).rstrip("\n")
            end = match.group(3)

            if existing:
                return f"{start}{existing}\n{new_entry}\n{end}"
            return f"{start}{new_entry}\n{end}"

        return re.sub(pattern, replacement, content, flags=re.DOTALL)

    def add_skill_reference(self, skill_name: str, skill_path: str) -> bool:
        """Add a skill reference to CLAUDE.md."""
        entry = f"Use skill `{skill_name}` from `.muscle/skills/` for related tasks. See `{skill_path}`."
        return self.update_claude_md(entry, category="skill")

    def add_agent_reference(self, agent_name: str, agent_path: str) -> bool:
        """Add an agent reference to AGENT.md."""
        entry = f"Invoke agent `{agent_name}` for {agent_name.replace('_', ' ')} tasks. See `{agent_path}`."
        return self.update_agent_md(entry, category="agent")

    def add_pattern_learned(self, pattern: str, file_path: str, severity: str) -> bool:
        """Record a pattern that was learned."""
        entry = f"Avoid `{pattern}` in `{file_path}` - {severity} severity issue"
        return self.update_memory_md(entry, category="pattern")

    def add_fix_validated(self, pattern: str, fix_description: str, success: bool) -> bool:
        """Record that a fix was validated."""
        status = "SUCCESS" if success else "FAILED"
        entry = f"Fix for `{pattern}`: {fix_description} - {status}"
        return self.update_memory_md(entry, category="fix_validation")

    def prune_old_entries(self, filename: str, max_entries: int = 100) -> int:
        """Remove old entries if section exceeds max_entries."""
        filepath = self.muscle_dir / filename
        if not filepath.exists():
            return 0

        content = filepath.read_text()
        section = self._extract_section(content)
        lines = [line for line in section.split("\n") if line.strip()]

        if len(lines) <= max_entries:
            return 0

        lines_to_keep = lines[-max_entries:]
        new_section = "\n".join(lines_to_keep)

        pattern = rf"({re.escape(self.LEARNED_START)}\n)(.*?)({re.escape(self.LEARNED_END)})"
        new_content = re.sub(
            pattern,
            lambda m: f"{m.group(1)}{new_section}\n{m.group(3)}",
            content,
            flags=re.DOTALL,
        )

        filepath.write_text(new_content)
        removed = len(lines) - len(lines_to_keep)
        logger.info(f"Pruned {removed} old entries from {filename}")
        return removed
