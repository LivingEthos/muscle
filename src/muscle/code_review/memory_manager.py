"""
MemoryManager - Internal markdown tracking for .muscle/ workspace artifacts.

DB-FIRST ARCHITECTURE: project_memory.db is the SOURCE OF TRUTH.
The internal markdown files managed here are BOUNDED INTERNAL ARTIFACTS only:
- .muscle/CLAUDE.md  - Internal structured rules (Do/Don't/Project Skills)
- .muscle/AGENT.md   - Internal agent reference tracking
- .muscle/MEMORY.md  - Internal session logs, archived rules, pattern history

These files are:
  - NOT treated as authoritative
  - Readable for backward compatibility with existing code
  - NOT the primary record for any decision
  - NOT consulted for root CLAUDE.md publishing decisions

All authoritative decisions flow through project_memory.db.
ClaudePublisher publishes to root CLAUDE.md using DB-backed data directly.

Marker-based editing is used to only modify MUSCLE-managed sections.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..io_safety import advisory_file_lock, atomic_write_text, update_text_file_locked
from .host_memory_templates import INTERNAL_SEED
from .thinking_policy import thinking_for

logger = logging.getLogger(__name__)

MARKER_START = "<!-- MUSCLE_LEARNED_START -->"
MARKER_END = "<!-- MUSCLE_LEARNED_END -->"
RULES_START = "<!-- MUSCLE_RULES_START -->"
RULES_END = "<!-- MUSCLE_RULES_END -->"
MEMORY_SECTION_START = "<!-- MUSCLE_MEMORY_START -->"
MEMORY_SECTION_END = "<!-- MUSCLE_MEMORY_END -->"


def _get_claude_publisher_module() -> type | None:
    """Lazy import to avoid circular dependencies."""
    try:
        from ..claude_publisher import ClaudePublisher

        return ClaudePublisher
    except ImportError:
        return None


class MemoryManager:
    """
    Internal markdown tracking for .muscle/ workspace artifacts.

    INTERNAL ONLY: This class manages bounded internal artifacts.
    project_memory.db is the authoritative source of truth.
    """

    LEARNED_START = "<!-- MUSCLE_LEARNED_START -->"
    LEARNED_END = "<!-- MUSCLE_LEARNED_END -->"

    def __init__(self, project_path: str, m27_client: Any | None = None):
        self.project_path = Path(project_path)
        self.muscle_dir = self.project_path / ".muscle"
        self.muscle_dir.mkdir(parents=True, exist_ok=True)
        self.m27 = m27_client

    def update_claude_md(self, entry: str, category: str = "general") -> bool:
        """INTERNAL TRACKING: Add an entry to .muscle/CLAUDE.md within markers.

        This is internal tracking only. DB is the authoritative source."""
        if self.m27 and len(entry) > 200:
            entry = self._m27_summarize_entry(entry, category)
        return self._update_memory_file("CLAUDE.md", entry, category)

    def update_agent_md(self, entry: str, category: str = "agent") -> bool:
        """INTERNAL TRACKING: Add an entry to .muscle/AGENT.md within markers.

        This is internal tracking only. DB is the authoritative source."""
        if self.m27 and len(entry) > 200:
            entry = self._m27_summarize_entry(entry, category)
        return self._update_memory_file("AGENT.md", entry, category)

    def update_memory_md(self, entry: str, category: str = "learned") -> bool:
        """INTERNAL TRACKING: Add an entry to .muscle/MEMORY.md within markers.

        This is internal tracking only. DB is the authoritative source."""
        if self.m27 and len(entry) > 200:
            entry = self._m27_summarize_entry(entry, category)
        return self._update_memory_file("MEMORY.md", entry, category)

    @staticmethod
    def _truncate_clean(text: str, limit: int = 150) -> str:
        """Truncate to at most ``limit`` chars on a clean boundary.

        Never cut mid-word, and never cut inside a markup tag like ``<...>`` or
        a bracketed token like ``[...]``/``(...)`` — back up to the last safe
        whitespace boundary before any open-but-unclosed delimiter.
        """
        text = text.strip()
        if len(text) <= limit:
            return text

        head = text[:limit]
        # If the cut point lands inside an open (unclosed) delimiter, back up to
        # before that delimiter so we never leave a dangling tag/token.
        for open_ch, close_ch in (("<", ">"), ("[", "]"), ("(", ")")):
            last_open = head.rfind(open_ch)
            if last_open != -1 and head.find(close_ch, last_open) == -1:
                head = head[:last_open]

        # Break on the last whitespace boundary so we don't cut mid-word.
        cut = head.rstrip()
        last_space = cut.rfind(" ")
        if last_space > 0:
            cut = cut[:last_space]
        return cut.rstrip()

    def _m27_summarize_entry(self, entry: str, category: str) -> str:
        """Use M2.7 to summarize a long entry into a concise form.

        Distinguishes three paths so callers/operators can tell them apart:
        no LLM configured (debug log), LLM failure (warning + clean-truncated
        original), and LLM success (clean-truncated summary)."""
        if not self.m27:
            logger.debug("No M2.7 client configured; truncating entry without summarization")
            return self._truncate_clean(entry)

        prompt = f"""Summarize this memory entry to be concise but preserve key information.

Category: {category}
Original entry:
{entry}

Return a summarized version (max 150 characters) that preserves:
- The core insight or lesson
- Any specific file paths or patterns mentioned
- Severity or importance if relevant

Return ONLY the summarized text, no quotes or explanation."""

        try:
            response_text, _ = self.m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a technical summarizer. Return concise summaries.",
                max_tokens=256,
                temperature=0.5,
                thinking=thinking_for("memory_consolidation"),
            )
            return self._truncate_clean(response_text)
        except Exception as e:
            logger.warning(f"M2.7 summarization failed: {e}")
            return self._truncate_clean(entry)

    def _update_memory_file(self, filename: str, entry: str, category: str) -> bool:
        filepath = self.muscle_dir / filename
        duplicate_found = False

        def updater(current: str) -> str:
            nonlocal duplicate_found
            content = current or self._create_file_with_markers(filename)
            existing = self._extract_section(content)
            if self._is_duplicate(existing, entry):
                duplicate_found = True
                return content
            new_entry = self._format_entry(entry, category)
            return self._insert_entry(content, new_entry, category)

        update_text_file_locked(filepath, updater, default_content="")
        if duplicate_found:
            logger.debug(f"Duplicate entry in {filename}, skipping")
            return False
        logger.info(f"Updated {filename} with {category} entry")
        return True

    def _create_file_with_markers(self, filename: str) -> str:
        # Seed CLAUDE.md / AGENT.md internal files with the Methodology block.
        # MEMORY.md remains a pure log (no behavioral seed) so session-history
        # readers aren't confused by prescriptive content.
        seed = INTERNAL_SEED if filename in ("CLAUDE.md", "AGENT.md") else ""
        return f"""# {filename.replace(".md", "")}

<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE managed section - DO NOT EDIT OUTSIDE MARKERS -->
{seed}<!-- MUSCLE_LEARNED_END -->
"""

    def _extract_section(self, content: str) -> str:
        match = re.search(
            rf"{re.escape(self.LEARNED_START)}(.*?){re.escape(self.LEARNED_END)}",
            content,
            re.DOTALL,
        )
        return match.group(1) if match else ""

    def _is_duplicate(self, section: str, entry: str) -> bool:
        """Check exact and semantic duplicates in the managed section."""
        entry_lower = entry.lower().strip()
        entry_files = set(re.findall(r"[\w/\\.-]+\.(?:py|js|ts|go|rs|java|cpp|c|h)\b", entry_lower))
        entry_title_words: set[str] = set()
        for match in re.finditer(r"[:\-\]]\s*([^\n]{10,80})", entry_lower):
            entry_title_words.update(match.group(1).split()[:5])

        for line in section.split("\n"):
            line_lower = line.lower().strip()
            if not line_lower or line_lower.startswith("<!--"):
                continue
            if len(entry_lower) < 100 and entry_lower in line_lower:
                return True
            line_files = set(
                re.findall(r"[\w/\\.-]+\.(?:py|js|ts|go|rs|java|cpp|c|h)\b", line_lower)
            )
            if entry_files and line_files and entry_files == line_files:
                line_title_words: set[str] = set()
                for match in re.finditer(r"[:\-\]]\s*([^\n]{10,80})", line_lower):
                    line_title_words.update(match.group(1).split()[:5])
                if len(entry_title_words & line_title_words) >= 3:
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

    def get_relevant_memories(self, context: str, max_memories: int = 5) -> list[dict[str, str]]:
        """Get memories most relevant to a given context using M2.7 ranking."""
        memories = self._get_all_memories()

        if not memories:
            return []

        if self.m27:
            return self._m27_rank_memories(context, memories, max_memories)
        return self._fallback_rank_memories(context, memories, max_memories)

    def _get_all_memories(self) -> list[dict[str, str]]:
        """Retrieve all memories from the managed section of each memory file."""
        memories = []
        for filename in ["CLAUDE.md", "AGENT.md", "MEMORY.md"]:
            filepath = self.muscle_dir / filename
            if filepath.exists():
                content = filepath.read_text()
                section = self._extract_section(content)
                for line in section.split("\n"):
                    line = line.strip()
                    if line.startswith("-"):
                        memories.append(
                            {
                                "source": filename,
                                "content": line,
                            }
                        )
        return memories

    def _m27_rank_memories(
        self, context: str, memories: list[dict[str, str]], max_memories: int
    ) -> list[dict[str, str]]:
        """Use M2.7 to rank memories by relevance to context."""
        assert self.m27 is not None, "M27 client should be set"
        m27 = self.m27
        memories_text = json.dumps(memories[:20], indent=2)

        prompt = f"""Given this current context:
{context}

And these stored memories:
{memories_text}

Rank the top {max_memories} memories most relevant to this context.
Consider:
1. How directly the memory relates to the context
2. How recent and actionable the memory is
3. Whether the memory provides warnings or lessons learned

Return a JSON array of memory contents (the original content strings), ordered by relevance:
```json
["most relevant memory content", "second most relevant", ...]
```"""

        try:
            response_text, _ = m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a memory relevance expert. Return valid JSON array only.",
                max_tokens=2048,
                temperature=0.3,
                thinking=thinking_for("memory_consolidation"),
            )

            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()

            ranked_contents = json.loads(response_text)

            if isinstance(ranked_contents, list):
                content_to_memory = {m["content"]: m for m in memories}
                ranked_memories = []
                for content in ranked_contents[:max_memories]:
                    if content in content_to_memory:
                        ranked_memories.append(content_to_memory[content])
                return ranked_memories

        except Exception as e:
            logger.warning(f"M2.7 memory ranking failed: {e}")

        return self._fallback_rank_memories(context, memories, max_memories)

    def _fallback_rank_memories(
        self, context: str, memories: list[dict[str, str]], max_memories: int
    ) -> list[dict[str, str]]:
        """Fallback: simple keyword-based ranking."""
        context_lower = context.lower()
        context_words = set(context_lower.split())

        scored = []
        for memory in memories:
            content_lower = memory["content"].lower()
            score = sum(1 for word in context_words if word in content_lower)
            score += 2 if "avoid" in content_lower else 0
            score += 1 if any(w in content_lower for w in ["error", "bug", "issue", "fail"]) else 0
            scored.append((score, memory))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:max_memories]]

    def summarize_memories_for_context(self, context: str) -> str:
        """Use M2.7 to generate a summary of relevant memories for a context."""
        memories = self.get_relevant_memories(context, max_memories=10)

        if not memories:
            return ""

        if self.m27:
            return self._m27_summarize_for_context(context, memories)

        return self._fallback_summarize_for_context(context, memories)

    def _m27_summarize_for_context(self, context: str, memories: list[dict[str, str]]) -> str:
        """Use M2.7 to generate a context-aware summary of memories."""
        assert self.m27 is not None, "M27 client should be set"
        m27 = self.m27
        memories_text = "\n".join(f"- {m['content']}" for m in memories)

        prompt = f"""Given this current task:
{context}

And these relevant memories from past reviews:
{memories_text}

Generate a brief summary (2-3 sentences) of the key lessons learned that apply to this task.
Focus on actionable insights and specific warnings.

Return ONLY the summary, no quotes or explanation."""

        try:
            response_text, _ = m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a technical summarizer. Be concise and actionable.",
                max_tokens=512,
                temperature=0.5,
                thinking=thinking_for("memory_consolidation"),
            )
            return response_text.strip()  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning(f"M2.7 memory summarization failed: {e}")
            return self._fallback_summarize_for_context(context, memories)

    def _fallback_summarize_for_context(self, context: str, memories: list[dict[str, str]]) -> str:
        """Fallback: simple concatenation of memory contents."""
        relevant = [m["content"] for m in memories[:5]]
        return " ".join(relevant)

    def prune_old_entries(self, filename: str, max_entries: int = 100) -> int:
        """Remove old entries if section exceeds max_entries."""
        filepath = self.muscle_dir / filename
        if not filepath.exists():
            return 0

        removed = 0

        def updater(content: str) -> str:
            nonlocal removed
            section = self._extract_section(content)
            lines = [line for line in section.split("\n") if line.strip()]

            if len(lines) <= max_entries:
                return content

            lines_to_keep = lines[-max_entries:]
            new_section = "\n".join(lines_to_keep)

            pattern = rf"({re.escape(self.LEARNED_START)}\n)(.*?)({re.escape(self.LEARNED_END)})"
            new_content = re.sub(
                pattern,
                lambda m: f"{m.group(1)}{new_section}\n{m.group(3)}",
                content,
                flags=re.DOTALL,
            )
            removed = len(lines) - len(lines_to_keep)
            return new_content

        update_text_file_locked(filepath, updater, default_content="")
        if removed:
            logger.info(f"Pruned {removed} old entries from {filename}")
        return removed

    @staticmethod
    def _is_memory_line(entry: str) -> bool:
        """Validate that a consolidated entry matches the real memory-line shape.

        Memory entries are written as ``- [YYYY-MM-DD] [category] ...``. The LLM
        may return bullets without the leading ``- ``; we accept those (we add
        the bullet back), but require the ``[date] [category]`` prefix so an LLM
        cannot smuggle in arbitrary text that doesn't match the file format.
        """
        candidate = entry.strip()
        candidate = candidate[2:].strip() if candidate.startswith("- ") else candidate
        return bool(re.match(r"^\[\d{4}-\d{2}-\d{2}\]\s*\[[^\]]+\]", candidate))

    def consolidate_memories(self) -> int:
        """Use M2.7 to consolidate and deduplicate memories, keeping only the most relevant.

        Returns the total number of entries removed across all files. Aborts a
        file (without writing) if the LLM would delete more than half the
        entries, and backs up the original before any overwrite."""
        if not self.m27:
            return 0

        total_removed = 0

        for filename in ["CLAUDE.md", "AGENT.md", "MEMORY.md"]:
            filepath = self.muscle_dir / filename
            if not filepath.exists():
                continue

            removed = self._consolidate_file(filepath, filename)
            total_removed += removed

        return total_removed

    def _consolidate_file(self, filepath: Path, filename: str) -> int:
        """Consolidate a single memory file under an advisory lock. Returns removed count."""
        with advisory_file_lock(filepath):
            if not filepath.exists():
                return 0
            content = filepath.read_text()
            section = self._extract_section(content)
            lines = [
                line.strip()
                for line in section.split("\n")
                if line.strip() and line.strip().startswith("-")
            ]

            old_count = len(lines)
            if old_count <= 50:
                return 0

            prompt = f"""Analyze these memory entries and consolidate them.
Remove obvious duplicates and entries that are superseded by others.
Return the {min(50, old_count)} most important unique entries.

Entries:
{chr(10).join(lines)}

Return a JSON array of the consolidated entries:
```json
["consolidated entry 1", "consolidated entry 2", ...]
```"""

            try:
                assert self.m27 is not None
                response_text, _ = self.m27.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are a memory consolidation expert. Return valid JSON array only.",
                    max_tokens=4096,
                    temperature=0.5,
                    thinking=thinking_for("memory_consolidation"),
                )

                if "```json" in response_text:
                    start = response_text.find("```json") + 7
                    end = response_text.find("```", start)
                    if end > start:
                        response_text = response_text[start:end].strip()

                try:
                    consolidated = json.loads(response_text)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning(f"Consolidation for {filename}: invalid JSON from LLM: {exc}")
                    return 0

                if not (isinstance(consolidated, list) and consolidated):
                    logger.warning(f"Consolidation for {filename}: empty/invalid result, aborting")
                    return 0

                # Reject entries that don't match the real memory-line shape so
                # the LLM cannot replace the file with arbitrary content.
                valid_entries = [
                    str(entry) for entry in consolidated if self._is_memory_line(str(entry))
                ]
                if not valid_entries:
                    logger.warning(
                        f"Consolidation for {filename}: no entries matched memory-line "
                        f"format, aborting (no write)"
                    )
                    return 0

                # Back up the original before deciding to overwrite or abort, so
                # the pre-consolidation state is always recoverable.
                backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                try:
                    atomic_write_text(backup_path, content)
                except Exception as exc:  # pragma: no cover - backup is best-effort precondition
                    logger.warning(
                        f"Consolidation for {filename}: backup failed ({exc}); aborting (no write)"
                    )
                    return 0

                new_count = len(valid_entries)
                if new_count < old_count * 0.5:
                    logger.warning(
                        f"Consolidation for {filename} would delete >50% of entries "
                        f"({old_count} -> {new_count}); aborting (no write, original backed up)"
                    )
                    return 0

                def _entry_line(entry: str) -> str:
                    stripped = entry.strip()
                    return stripped if stripped.startswith("- ") else f"- {stripped}"

                new_section = "\n".join(_entry_line(entry) for entry in valid_entries)
                pattern = (
                    rf"({re.escape(self.LEARNED_START)}\n)(.*?)({re.escape(self.LEARNED_END)})"
                )

                def make_replacement(section: str) -> Any:
                    return lambda m: f"{m.group(1)}{section}\n{m.group(3)}"

                new_content = re.sub(
                    pattern,
                    make_replacement(new_section),
                    content,
                    flags=re.DOTALL,
                )
                atomic_write_text(filepath, new_content)
                removed = old_count - new_count
                logger.info(f"Consolidated {filename}: {old_count} -> {new_count} entries")
                return removed

            except Exception as e:
                logger.warning(f"Memory consolidation failed for {filename}: {e}")
                return 0

    # ---- Structured CLAUDE.md / MEMORY.md methods ----

    def _ensure_claude_md_content(self, content: str) -> str:
        """Pure transform: ensure CLAUDE.md content has the structured rules section.

        Folded into locked updaters so ensure+read+insert is one atomic operation."""
        if not content:
            return f"# CLAUDE\n\n{self._rules_section_template()}\n"
        if RULES_START in content:
            return content
        # File exists but lacks rules markers -- append the section
        return content.rstrip("\n") + "\n\n" + self._rules_section_template() + "\n"

    @staticmethod
    def _rules_section_template() -> str:
        return (
            f"{RULES_START}\n"
            "## MUSCLE Learned Rules\n\n"
            "### Do\n\n"
            "### Don't\n\n"
            "### Project Skills\n\n"
            f"{RULES_END}"
        )

    def _ensure_memory_md_content(self, content: str) -> str:
        """Pure transform: ensure MEMORY.md content has the structured sections.

        Folded into locked updaters so ensure+read+insert is one atomic operation."""
        if not content:
            return f"# MEMORY\n\n{self._memory_section_template()}\n"
        if MEMORY_SECTION_START in content:
            return content
        return content.rstrip("\n") + "\n\n" + self._memory_section_template() + "\n"

    @staticmethod
    def _memory_section_template() -> str:
        return (
            f"{MEMORY_SECTION_START}\n"
            "## Pattern History\n\n"
            "## Archived Rules\n\n"
            "## Fix History\n\n"
            "## Review Sessions\n\n"
            f"{MEMORY_SECTION_END}"
        )

    def _extract_rules_section(self, content: str) -> str:
        """Extract content between RULES_START and RULES_END."""
        match = re.search(
            rf"{re.escape(RULES_START)}(.*?){re.escape(RULES_END)}",
            content,
            re.DOTALL,
        )
        return match.group(1) if match else ""

    def write_rule(
        self,
        rule_text: str,
        rule_type: str,
        severity: str,
        confidence: str,
        validated_count: int,
    ) -> bool:
        """INTERNAL TRACKING: Write a rule to .muscle/CLAUDE.md under ### Do or ### Don't.

        This is internal tracking only. DB is the authoritative source for rules."""
        filepath = self.muscle_dir / "CLAUDE.md"
        written = False

        entry = f"- {rule_text} (confidence: {confidence}, validated: {validated_count}x)"
        header = "### Do" if rule_type == "do" else "### Don't"

        def updater(current: str) -> str:
            nonlocal written
            content = self._ensure_claude_md_content(current)
            rules_section = self._extract_rules_section(content)
            # Dedup check (case-insensitive)
            if rule_text.lower() in rules_section.lower():
                return content
            written = True
            # Insert entry after the target header, before the next ### header
            return self._insert_under_header(content, header, entry)

        update_text_file_locked(filepath, updater, default_content="")
        return written

    def _insert_under_header(self, content: str, header: str, entry: str) -> str:
        """Insert an entry line under a specific ### header, before the next ### or end marker."""
        lines = content.split("\n")
        result: list[str] = []
        inserted = False

        i = 0
        while i < len(lines):
            result.append(lines[i])
            if not inserted and lines[i].strip() == header:
                # Find the insertion point: after any existing entries, before next ### or RULES_END
                i += 1
                # Skip blank lines and existing entries under this header
                while i < len(lines):
                    line = lines[i]
                    if line.startswith("### ") or line.strip() == RULES_END:
                        break
                    result.append(line)
                    i += 1
                # Insert the new entry (with blank line before next section)
                result.append(entry)
                inserted = True
                continue  # Don't increment i again, we already advanced
            i += 1

        return "\n".join(result)

    def write_skill_ref(self, skill_name: str, skill_path: str) -> bool:
        """Add a skill reference under ### Project Skills. Deduplicates."""
        filepath = self.muscle_dir / "CLAUDE.md"
        entry = f"- `{skill_path}` \u2014 {skill_name}"
        written = False

        def updater(current: str) -> str:
            nonlocal written
            content = self._ensure_claude_md_content(current)
            rules_section = self._extract_rules_section(content)
            if skill_path.lower() in rules_section.lower():
                return content
            written = True
            return self._insert_under_header(content, "### Project Skills", entry)

        update_text_file_locked(filepath, updater, default_content="")
        return written

    def read_rules(self) -> list[dict]:
        """INTERNAL TRACKING: Parse rules from .muscle/CLAUDE.md into list of dicts.

        This reads from internal markdown for backward compatibility.
        DB is the authoritative source."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            return []

        content = filepath.read_text()
        rules_section = self._extract_rules_section(content)
        if not rules_section:
            return []

        rules: list[dict] = []
        current_type: str | None = None

        for line in rules_section.split("\n"):
            stripped = line.strip()
            if stripped == "### Do":
                current_type = "do"
            elif stripped == "### Don't":
                current_type = "dont"
            elif stripped == "### Project Skills":
                current_type = None  # skills are not rules
            elif stripped.startswith("- ") and current_type is not None:
                text, confidence, validated_count = self._parse_rule_line(stripped)
                if text:
                    rules.append(
                        {
                            "text": text,
                            "type": current_type,
                            "confidence": confidence,
                            "validated_count": validated_count,
                        }
                    )

        return rules

    @staticmethod
    def _parse_rule_line(line: str) -> tuple[str, str, int]:
        """Parse '- Rule text (confidence: X, validated: Nx)' into (text, confidence, validated_count)."""
        match = re.match(
            r"^- (.+?) \(confidence: ([^,]+), validated: (\d+)x\)$",
            line,
        )
        if match:
            return match.group(1), match.group(2), int(match.group(3))
        return "", "", 0

    def update_rule_validation(self, rule_text: str, validated_count: int, confidence: str) -> bool:
        """INTERNAL TRACKING: Update an existing rule's validation count in .muscle/CLAUDE.md.

        This is internal tracking only. DB is the authoritative source."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            return False

        updated = False

        def updater(content: str) -> str:
            nonlocal updated
            lines = content.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("- ") and rule_text.lower() in stripped.lower():
                    parsed_text, _, _ = self._parse_rule_line(stripped)
                    if parsed_text.lower() == rule_text.lower():
                        lines[i] = (
                            f"- {parsed_text} (confidence: {confidence}, "
                            f"validated: {validated_count}x)"
                        )
                        updated = True
                        break
            return "\n".join(lines) if updated else content

        update_text_file_locked(filepath, updater, default_content="")
        return updated

    def archive_rule(self, rule_text: str, reason: str) -> bool:
        """INTERNAL TRACKING: Remove rule from .muscle/CLAUDE.md, add to .muscle/MEMORY.md.

        This is internal tracking only. DB is the authoritative source."""
        filepath = self.muscle_dir / "CLAUDE.md"
        if not filepath.exists():
            return False

        removed_line: str | None = None

        def remove_updater(content: str) -> str:
            nonlocal removed_line
            lines = content.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("- ") and rule_text.lower() in stripped.lower():
                    parsed_text, _, _ = self._parse_rule_line(stripped)
                    if parsed_text.lower() == rule_text.lower():
                        removed_line = stripped
                        lines.pop(i)
                        return "\n".join(lines)
            return content

        update_text_file_locked(filepath, remove_updater, default_content="")

        if not removed_line:
            return False

        # Add to MEMORY.md under ## Archived Rules
        memory_path = self.muscle_dir / "MEMORY.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        archive_entry = f"- [{timestamp}] {removed_line} — Reason: {reason}"

        def archive_updater(content: str) -> str:
            content = self._ensure_memory_md_content(content)
            return self._insert_under_header(content, "## Archived Rules", archive_entry)

        update_text_file_locked(memory_path, archive_updater, default_content="")
        return True

    def log_review_session(
        self,
        critical: int,
        high: int,
        medium: int,
        low: int,
        actions: list[str],
    ) -> bool:
        """INTERNAL TRACKING: Add a session summary under ## Review Sessions in .muscle/MEMORY.md.

        This is internal tracking only. DB is the authoritative source."""
        memory_path = self.muscle_dir / "MEMORY.md"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        actions_str = "; ".join(actions) if actions else "none"
        entry = (
            f"- [{timestamp}] critical={critical} high={high} medium={medium} low={low} "
            f"| actions: {actions_str}"
        )

        def updater(content: str) -> str:
            content = self._ensure_memory_md_content(content)
            return self._insert_under_header(content, "## Review Sessions", entry)

        update_text_file_locked(memory_path, updater, default_content="")
        return True

    def sync_to_root_claude_md(self) -> bool:
        """DEPRECATED/FALLBACK: Sync from internal markdown to root CLAUDE.md.

        This method reads from .muscle/CLAUDE.md (internal markdown) and is a
        FALLBACK for backward compatibility only.

        PREFERRED PATH: Use ClaudePublisher.publish() directly with DB-backed
        data from LearningPipeline.learn_from_review().

        This method exists for backward compatibility with code that may call it
        directly. The authoritative path is:
          LearningPipeline.learn_from_review() -> _publisher.publish(critical_rules=DB_DATA)

        Returns True if sync succeeded, False otherwise.
        """
        claude_publisher_cls = _get_claude_publisher_module()
        if claude_publisher_cls is None:
            logger.warning("ClaudePublisher not available, skipping sync")
            return False

        try:
            publisher = claude_publisher_cls(str(self.project_path))
            return bool(publisher.update_markers())
        except Exception as e:
            logger.warning(f"Failed to sync to root CLAUDE.md: {e}")
            return False

    def ensure_root_claude_md_markers(self) -> bool:
        """Ensure root CLAUDE.md has MUSCLE_PUBLISHED markers.

        This is a utility for initial setup. The preferred path is
        ClaudePublisher.insert_markers_if_missing() directly.

        Returns True if markers exist or were inserted, False otherwise.
        """
        claude_publisher_cls = _get_claude_publisher_module()
        if claude_publisher_cls is None:
            logger.warning("ClaudePublisher not available")
            return False

        try:
            publisher = claude_publisher_cls(str(self.project_path))
            return bool(publisher.insert_markers_if_missing())
        except Exception as e:
            logger.warning(f"Failed to ensure root markers: {e}")
            return False
