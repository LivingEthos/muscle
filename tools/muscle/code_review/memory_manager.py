"""
Memory Manager - Updates CLAUDE.md, AGENT.md, and MEMORY.md with learnings using M2.7 intelligence.

Uses marker-based editing to only modify MUSCLE-managed sections.

Architecture Decision Record (ADR):
- M2.7-powered summarization to compress memory entries
- M2.7 relevance ranking for smart retrieval
- Bounded edits via markers prevent corruption of user content
- Deduplication before adding new entries
- Pruning of old entries when superseded
- Structured format for easy parsing
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARKER_START = "<!-- MUSCLE_LEARNED_START -->"
MARKER_END = "<!-- MUSCLE_LEARNED_END -->"


class MemoryManager:
    LEARNED_START = "<!-- MUSCLE_LEARNED_START -->"
    LEARNED_END = "<!-- MUSCLE_LEARNED_END -->"

    def __init__(self, project_path: str, m27_client: Any | None = None):
        self.project_path = Path(project_path)
        self.muscle_dir = self.project_path / ".muscle"
        self.muscle_dir.mkdir(parents=True, exist_ok=True)
        self.m27 = m27_client

    def update_claude_md(self, entry: str, category: str = "general") -> bool:
        """Add an entry to CLAUDE.md within markers, optionally summarized by M2.7."""
        if self.m27 and len(entry) > 200:
            entry = self._m27_summarize_entry(entry, category)
        return self._update_memory_file("CLAUDE.md", entry, category)

    def update_agent_md(self, entry: str, category: str = "agent") -> bool:
        """Add an entry to AGENT.md within markers, optionally summarized by M2.7."""
        if self.m27 and len(entry) > 200:
            entry = self._m27_summarize_entry(entry, category)
        return self._update_memory_file("AGENT.md", entry, category)

    def update_memory_md(self, entry: str, category: str = "learned") -> bool:
        """Add an entry to MEMORY.md within markers, optionally summarized by M2.7."""
        if self.m27 and len(entry) > 200:
            entry = self._m27_summarize_entry(entry, category)
        return self._update_memory_file("MEMORY.md", entry, category)

    def _m27_summarize_entry(self, entry: str, category: str) -> str:
        """Use M2.7 to summarize a long entry into a concise form."""
        if not self.m27:
            return entry

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
            )
            return response_text.strip()[:150]  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning(f"M2.7 summarization failed: {e}")
            return entry[:150]

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

    def consolidate_memories(self) -> int:
        """Use M2.7 to consolidate and deduplicate memories, keeping only the most relevant."""
        if not self.m27:
            return 0

        for filename in ["CLAUDE.md", "AGENT.md", "MEMORY.md"]:
            filepath = self.muscle_dir / filename
            if not filepath.exists():
                continue

            content = filepath.read_text()
            section = self._extract_section(content)
            lines = [
                line.strip()
                for line in section.split("\n")
                if line.strip() and line.strip().startswith("-")
            ]

            if len(lines) <= 50:
                continue

            prompt = f"""Analyze these memory entries and consolidate them.
Remove obvious duplicates and entries that are superseded by others.
Return the {min(50, len(lines))} most important unique entries.

Entries:
{chr(10).join(lines)}

Return a JSON array of the consolidated entries:
```json
["consolidated entry 1", "consolidated entry 2", ...]
```"""

            try:
                response_text, _ = self.m27.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are a memory consolidation expert. Return valid JSON array only.",
                    max_tokens=4096,
                    temperature=0.5,
                )

                if "```json" in response_text:
                    start = response_text.find("```json") + 7
                    end = response_text.find("```", start)
                    if end > start:
                        response_text = response_text[start:end].strip()

                consolidated = json.loads(response_text)
                if isinstance(consolidated, list) and consolidated:
                    new_section = "\n".join(f"- {entry}" for entry in consolidated)
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
                    filepath.write_text(new_content)
                    logger.info(
                        f"Consolidated {filename}: {len(lines)} -> {len(consolidated)} entries"
                    )

            except Exception as e:
                logger.warning(f"Memory consolidation failed for {filename}: {e}")

        return 0
