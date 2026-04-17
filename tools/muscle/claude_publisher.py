"""
ClaudePublisher - Publishes DB-backed content to root CLAUDE.md using marker-based editing.

DB-FIRST ARCHITECTURE:
- project_memory.db is the SOURCE OF TRUTH for all published content
- Root CLAUDE.md publishing is driven from DB-backed decisions
- Internal markdown (.muscle/CLAUDE.md) is NOT consulted for publishing

Safe update guarantees:
1. Always creating a backup before writing
2. Preserving user content outside MUSCLE_PUBLISHED markers
3. Enforcing size caps per section (max 50 lines)
4. Deduplicating entries before publishing
5. Supporting both marker insertion and marker updates
6. Automatic consolidation via M2.7 when caps exceeded
7. Audit trail of demotions and consolidations

Architecture Decision Record (ADR):
- Marker-based editing prevents corruption of user content
- Backup before write ensures safe rollback
- Size caps per section prevent CLAUDE.md bloat
- Deduplication keeps content fresh and concise
- M2.7-powered consolidation when caps exceeded
- Consolidation audit trail in project_memory.db
- DB-backed decisions: LearningPipeline passes DB-scored rules to publish()
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .backup_manager import BackupManager

logger = logging.getLogger(__name__)

# Marker constants for root CLAUDE.md
PUBLISHED_START = "<!-- MUSCLE_PUBLISHED_START -->"
PUBLISHED_END = "<!-- MUSCLE_PUBLISHED_END -->"

# Section headers within published region
SECTION_CRITICAL_RULES = "### Critical Rules"
SECTION_MISTAKE_CORRECTIONS = "### Frequent Mistakes"
SECTION_AGENT_CALLS = "### Active Agent Calls"
SECTION_SKILL_CALLS = "### Active Skill Calls"
SECTION_TOOLING_NOTES = "### Tooling Notes"

# Size cap per section
MAX_SECTION_LINES = 50


class ClaudePublisher:
    """Publishes compact learned content to root CLAUDE.md."""

    def __init__(
        self,
        project_path: str,
        backup_manager: BackupManager | None = None,
        m27_client: Any | None = None,
    ):
        """
        Initialize ClaudePublisher.

        Args:
            project_path: Path to the project root.
            backup_manager: Optional shared BackupManager instance. If not provided,
                           one will be created using ProjectMemory.
            m27_client: Optional M2.7 client for consolidation.
        """
        self.project_path = Path(project_path)
        self.claude_md_path = self.project_path / "CLAUDE.md"
        self.m27 = m27_client

        if backup_manager is not None:
            # Use the provided shared BackupManager
            self._backup_manager = backup_manager
        else:
            # Create a shared BackupManager using ProjectMemory
            from .project_memory import ProjectMemory

            pm = ProjectMemory(str(self.project_path))
            self._backup_manager = BackupManager(pm, str(self.project_path))

    @property
    def backup_manager(self) -> BackupManager:
        """Access the backup manager (for backwards compatibility)."""
        return self._backup_manager

    def _get_section_sizes(self) -> dict[str, int]:
        """Get current line count for each section in published region."""
        if not self.claude_md_path.exists():
            return {}

        content = self.claude_md_path.read_text()
        sizes: dict[str, int] = {}

        # Extract content between PUBLISHED_START and PUBLISHED_END
        match = re.search(
            rf"{re.escape(PUBLISHED_START)}(.*?){re.escape(PUBLISHED_END)}",
            content,
            re.DOTALL,
        )
        if not match:
            return {}

        published_content = match.group(1)
        lines = published_content.split("\n")

        current_section: str | None = None
        section_lines: list[str] = []

        for line in lines:
            # Check if this is a section header
            if line.startswith("### "):
                if current_section and section_lines:
                    sizes[current_section] = len(section_lines)
                current_section = line
                section_lines = []
            else:
                section_lines.append(line)

        # Don't forget the last section
        if current_section and section_lines:
            sizes[current_section] = len(section_lines)

        return sizes

    def _consolidate_section(
        self,
        section_name: str,
        entries: list[dict],
        max_entries: int,
    ) -> tuple[list[dict], list[dict]]:
        """Consolidate section entries when they exceed max.

        Returns tuple of (kept_entries, demoted_entries).
        """
        if len(entries) <= max_entries:
            return entries, []

        # Split: keep top max_entries, demote the rest
        kept = entries[:max_entries]
        demoted = entries[max_entries:]

        # Use M2.7 to summarize demoted entries if available
        if self.m27 and demoted:
            demoted = self._m27_summarize_entries(demoted, section_name)

        return kept, demoted

    def _m27_summarize_entries(
        self,
        entries: list[dict],
        section_name: str,
    ) -> list[dict]:
        """Use M2.7 to summarize demoted entries into condensed form."""
        if not self.m27:
            return entries

        # Format entries for summarization
        entries_text = json.dumps(entries, indent=2)

        prompt = f"""These entries from section '{section_name}' in CLAUDE.md need to be consolidated
because they exceed the size cap. Create a condensed version that preserves the key insights.

Entries:
{entries_text}

Return a JSON array of the same number of condensed entries, where each entry:
- Preserves the core insight
- Is max 80 characters
- Removes redundant details
- Prioritizes high-scoring entries

Return ONLY the JSON array, nothing else."""

        try:
            response_text, _ = self.m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a memory consolidation expert. Return valid JSON array only.",
                max_tokens=2048,
                temperature=0.5,
            )

            # Extract JSON from response
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()

            summarized = json.loads(response_text)
            if isinstance(summarized, list) and len(summarized) == len(entries):
                return summarized
        except Exception as e:
            logger.warning(f"M2.7 consolidation failed: {e}")

        return entries

    def _record_consolidation_audit(
        self,
        section_name: str,
        demoted_entries: list[dict],
        reason: str,
    ) -> None:
        """Record consolidation/demotion to audit log."""
        if not demoted_entries:
            return

        try:
            # Write to audit file
            audit_path = self.project_path / ".muscle" / "consolidation_audit.jsonl"
            timestamp = datetime.now().isoformat()

            with open(audit_path, "a") as f:
                for entry in demoted_entries:
                    audit_record = {
                        "timestamp": timestamp,
                        "section": section_name,
                        "reason": reason,
                        "entry": entry,
                    }
                    f.write(json.dumps(audit_record) + "\n")

            logger.info(f"Recorded {len(demoted_entries)} demotions for section {section_name}")
        except Exception as e:
            logger.warning(f"Failed to record consolidation audit: {e}")

    def _check_and_consolidate(
        self,
        critical_rules: list[dict],
        mistake_corrections: list[dict],
        agent_calls: list[dict],
        skill_calls: list[dict],
        tooling_notes: list[str],
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], list[str]]:
        """Check section sizes and consolidate if needed.

        Returns tuple of (critical_rules, mistake_corrections, agent_calls, skill_calls, tooling_notes)
        after consolidation.
        """
        current_sizes = self._get_section_sizes()

        # Calculate new sizes after adding incoming entries
        total_critical = current_sizes.get(SECTION_CRITICAL_RULES, 0) + len(critical_rules)
        total_mistakes = current_sizes.get(SECTION_MISTAKE_CORRECTIONS, 0) + len(
            mistake_corrections
        )
        total_agents = current_sizes.get(SECTION_AGENT_CALLS, 0) + len(agent_calls)
        total_skills = current_sizes.get(SECTION_SKILL_CALLS, 0) + len(skill_calls)
        total_notes = current_sizes.get(SECTION_TOOLING_NOTES, 0) + len(tooling_notes)

        # Consolidate each section that exceeds MAX_SECTION_LINES
        if total_critical > MAX_SECTION_LINES:
            consolidated, demoted = self._consolidate_section(
                SECTION_CRITICAL_RULES,
                critical_rules,
                MAX_SECTION_LINES,
            )
            critical_rules = consolidated
            self._record_consolidation_audit(
                SECTION_CRITICAL_RULES,
                demoted,
                f"exceeded cap ({total_critical} > {MAX_SECTION_LINES})",
            )

        if total_mistakes > MAX_SECTION_LINES:
            consolidated, demoted = self._consolidate_section(
                SECTION_MISTAKE_CORRECTIONS,
                mistake_corrections,
                MAX_SECTION_LINES,
            )
            mistake_corrections = consolidated
            self._record_consolidation_audit(
                SECTION_MISTAKE_CORRECTIONS,
                demoted,
                f"exceeded cap ({total_mistakes} > {MAX_SECTION_LINES})",
            )

        if total_agents > MAX_SECTION_LINES:
            consolidated, demoted = self._consolidate_section(
                SECTION_AGENT_CALLS,
                agent_calls,
                MAX_SECTION_LINES,
            )
            agent_calls = consolidated
            self._record_consolidation_audit(
                SECTION_AGENT_CALLS,
                demoted,
                f"exceeded cap ({total_agents} > {MAX_SECTION_LINES})",
            )

        if total_skills > MAX_SECTION_LINES:
            consolidated, demoted = self._consolidate_section(
                SECTION_SKILL_CALLS,
                skill_calls,
                MAX_SECTION_LINES,
            )
            skill_calls = consolidated
            self._record_consolidation_audit(
                SECTION_SKILL_CALLS,
                demoted,
                f"exceeded cap ({total_skills} > {MAX_SECTION_LINES})",
            )

        if total_notes > MAX_SECTION_LINES:
            consolidated, demoted = self._consolidate_section(
                SECTION_TOOLING_NOTES,
                [{"text": n} for n in tooling_notes],
                MAX_SECTION_LINES,
            )
            tooling_notes = [e["text"] for e in consolidated]
            self._record_consolidation_audit(
                SECTION_TOOLING_NOTES,
                demoted,
                f"exceeded cap ({total_notes} > {MAX_SECTION_LINES})",
            )

        return critical_rules, mistake_corrections, agent_calls, skill_calls, tooling_notes

    def publish(
        self,
        critical_rules: list[dict[str, Any]] | None = None,
        mistake_corrections: list[dict[str, Any]] | None = None,
        agent_calls: list[dict[str, Any]] | None = None,
        skill_calls: list[dict[str, Any]] | None = None,
        tooling_notes: list[str] | None = None,
    ) -> bool:
        """Publish compact sections to root CLAUDE.md.

        Args:
            critical_rules: List of dicts with 'text', 'score', 'validated_count'
            mistake_corrections: List of dicts with 'mistake', 'correction', 'count'
            agent_calls: List of dicts with 'agent_name', 'path', 'use_count'
            skill_calls: List of dicts with 'skill_name', 'path', 'use_count'
            tooling_notes: List of tool configuration notes

        Returns:
            True if publish succeeded, False otherwise
        """
        if not self.claude_md_path.exists():
            logger.warning(f"CLAUDE.md not found at {self.claude_md_path}")
            return False

        # Always create backup before writing (using shared BackupManager)
        try:
            self._backup_manager.create_backup("claude_md")
        except FileNotFoundError:
            # Root CLAUDE.md doesn't exist yet - cannot back up
            logger.warning(f"CLAUDE.md not found at {self.claude_md_path}, cannot backup")
            return False
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            return False

        # Check sizes and consolidate if needed (M2.7 summarization for over-cap sections)
        (
            critical_rules,
            mistake_corrections,
            agent_calls,
            skill_calls,
            tooling_notes,
        ) = self._check_and_consolidate(
            critical_rules=critical_rules or [],
            mistake_corrections=mistake_corrections or [],
            agent_calls=agent_calls or [],
            skill_calls=skill_calls or [],
            tooling_notes=tooling_notes or [],
        )

        try:
            content = self.claude_md_path.read_text()
            updated_content = self._update_published_section(
                content,
                critical_rules=critical_rules or [],
                mistake_corrections=mistake_corrections or [],
                agent_calls=agent_calls or [],
                skill_calls=skill_calls or [],
                tooling_notes=tooling_notes or [],
            )
            self.claude_md_path.write_text(updated_content)
            logger.info("Successfully published to CLAUDE.md")

            self._backup_manager._pm.insert_action_log(
                project_path=str(self.project_path),
                action_type="publish",
                entity_type="claude_md",
                entity_id=None,
                details_json='{"sections": ["critical_rules", "mistake_corrections", "agent_calls", "skill_calls", "tooling_notes"]}',
            )

            return True
        except Exception as e:
            logger.error(f"Failed to publish to CLAUDE.md: {e}")
            return False

    def _update_published_section(
        self,
        content: str,
        critical_rules: list[dict],
        mistake_corrections: list[dict],
        agent_calls: list[dict],
        skill_calls: list[dict],
        tooling_notes: list[str],
    ) -> str:
        """Update the published section while preserving user content outside markers."""
        # If no markers exist, insert them with the published content
        if PUBLISHED_START not in content:
            published_content = self._build_published_content(
                critical_rules,
                mistake_corrections,
                agent_calls,
                skill_calls,
                tooling_notes,
            )
            return self._insert_markers(content, published_content)

        # Update existing markers
        return self._replace_published_section(
            content,
            critical_rules,
            mistake_corrections,
            agent_calls,
            skill_calls,
            tooling_notes,
        )

    def _build_published_content(
        self,
        critical_rules: list[dict],
        mistake_corrections: list[dict],
        agent_calls: list[dict],
        skill_calls: list[dict],
        tooling_notes: list[str],
    ) -> str:
        """Build the compact published content section."""
        lines: list[str] = []

        # Critical Rules (high score rules first)
        if critical_rules:
            lines.append(SECTION_CRITICAL_RULES)
            sorted_rules = sorted(
                critical_rules,
                key=lambda r: (r.get("score", 0), r.get("validated_count", 0)),
                reverse=True,
            )
            for rule in sorted_rules[:MAX_SECTION_LINES]:
                text = rule.get("text", "")
                score = rule.get("score", 0)
                validated = rule.get("validated_count", 0)
                lines.append(f"- {text} (score: {score}, validated: {validated}x)")
            lines.append("")

        # Frequent Mistakes
        if mistake_corrections:
            lines.append(SECTION_MISTAKE_CORRECTIONS)
            sorted_mistakes = sorted(
                mistake_corrections,
                key=lambda m: m.get("count", 0),
                reverse=True,
            )
            for mistake in sorted_mistakes[:MAX_SECTION_LINES]:
                lines.append(f"- Avoid: {mistake.get('mistake', '')}")
                lines.append(f"  Fix: {mistake.get('correction', '')}")
            lines.append("")

        # Active Agent Calls
        if agent_calls:
            lines.append(SECTION_AGENT_CALLS)
            sorted_agents = sorted(
                agent_calls,
                key=lambda a: a.get("use_count", 0),
                reverse=True,
            )
            for agent in sorted_agents[:MAX_SECTION_LINES]:
                name = agent.get("agent_name", "")
                path = agent.get("path", "")
                count = agent.get("use_count", 0)
                lines.append(f"- `{name}` — {path} ({count}x)")
            lines.append("")

        # Active Skill Calls
        if skill_calls:
            lines.append(SECTION_SKILL_CALLS)
            sorted_skills = sorted(
                skill_calls,
                key=lambda s: s.get("use_count", 0),
                reverse=True,
            )
            for skill in sorted_skills[:MAX_SECTION_LINES]:
                name = skill.get("skill_name", "")
                path = skill.get("path", "")
                count = skill.get("use_count", 0)
                lines.append(f"- `{name}` — {path} ({count}x)")
            lines.append("")

        # Tooling Notes
        if tooling_notes:
            lines.append(SECTION_TOOLING_NOTES)
            for note in tooling_notes[:MAX_SECTION_LINES]:
                lines.append(f"- {note}")
            lines.append("")

        return "\n".join(lines).strip()

    def _insert_markers(self, content: str, published_content: str) -> str:
        """Insert markers with published content into CLAUDE.md."""
        # Find a good insertion point - after the first heading or at end
        lines = content.split("\n")

        # Look for insertion point after initial headings (Project Overview, etc.)
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("## ") and i > 0:
                insert_idx = i + 1

        marker_block = f"\n{PUBLISHED_START}\n{published_content}\n{PUBLISHED_END}\n"

        # Insert at found position
        result_lines = lines[:insert_idx] + [marker_block] + lines[insert_idx:]
        return "\n".join(result_lines)

    def _replace_published_section(
        self,
        content: str,
        critical_rules: list[dict],
        mistake_corrections: list[dict],
        agent_calls: list[dict],
        skill_calls: list[dict],
        tooling_notes: list[str],
    ) -> str:
        """Replace content between markers with new published content."""
        pattern = rf"({re.escape(PUBLISHED_START)}\n)(.*?)(\n{re.escape(PUBLISHED_END)})"

        new_published = self._build_published_content(
            critical_rules,
            mistake_corrections,
            agent_calls,
            skill_calls,
            tooling_notes,
        )

        def replacement(match: re.Match[str]) -> str:
            start = match.group(1)
            end = match.group(3)
            return f"{start}{new_published}{end}"

        return re.sub(pattern, replacement, content, flags=re.DOTALL)

    def get_critical_rules_from_memory(self) -> list[dict[str, Any]]:
        """FALLBACK: Extract rules from .muscle/CLAUDE.md (internal markdown).

        DEPRECATED: This reads from internal markdown which is NOT the source of truth.
        Use update_markers() which queries DB directly instead.

        This method exists for backward compatibility only."""
        from .code_review.memory_manager import MemoryManager

        try:
            manager = MemoryManager(str(self.project_path))
            rules = manager.read_rules()

            # Filter and score rules
            scored_rules = []
            for rule in rules:
                score = self._calculate_rule_score(
                    rule.get("confidence", "low"),
                    rule.get("validated_count", 0),
                )
                if score >= 0.5:  # Only include medium+ confidence
                    scored_rules.append(
                        {
                            "text": rule.get("text", ""),
                            "score": score,
                            "validated_count": rule.get("validated_count", 0),
                        }
                    )

            return scored_rules
        except Exception as e:
            logger.warning(f"Failed to extract critical rules: {e}")
            return []

    def _calculate_rule_score(self, confidence: str, validated_count: int) -> float:
        """Calculate a normalized score for a rule."""
        confidence_weights = {"high": 1.0, "medium": 0.6, "low": 0.3}
        base = confidence_weights.get(confidence.lower(), 0.3)
        # Boost by validated count (capped at 10)
        boost = min(validated_count, 10) * 0.05
        return min(base + boost, 1.0)

    def get_mistake_corrections_from_memory(self) -> list[dict[str, Any]]:
        """FALLBACK: Extract mistake corrections from .muscle/MEMORY.md.

        DEPRECATED: This reads from internal markdown which is NOT the source of truth.
        Use update_markers() which queries DB directly instead.

        This method exists for backward compatibility only."""
        memory_path = self.project_path / ".muscle" / "MEMORY.md"

        if not memory_path.exists():
            return []

        try:
            content = memory_path.read_text()
            mistakes: dict[str, dict[str, Any]] = {}

            # Extract pattern entries from MEMORY.md
            import re

            pattern = re.compile(r"- \[.*?\].*?Avoid.*?`(.*?)`.*?Fix:\s*(.+?)(?:\n|$)")

            for match in pattern.finditer(content):
                mistake = match.group(1).strip()
                correction = match.group(2).strip()
                if mistake in mistakes:
                    mistakes[mistake]["count"] += 1
                else:
                    mistakes[mistake] = {"mistake": mistake, "correction": correction, "count": 1}

            return list(mistakes.values())
        except Exception as e:
            logger.warning(f"Failed to extract mistake corrections: {e}")
            return []

    def get_agent_calls_from_memory(self) -> list[dict[str, Any]]:
        """FALLBACK: Extract agent call usage from .muscle/agents/ directory.

        DEPRECATED: This reads from filesystem which is NOT the source of truth.
        Use update_markers() which queries DB directly instead.

        This method exists for backward compatibility only."""
        agents_dir = self.project_path / ".muscle" / "agents"
        if not agents_dir.exists():
            return []

        agents = []
        for agent_file in agents_dir.glob("*.md"):
            try:
                content = agent_file.read_text()
                # Extract metadata or count usage
                name = agent_file.stem.replace("_", "-")
                use_count = content.count("<!-- used") + content.count("INVOKED")
                if use_count > 0:
                    agents.append(
                        {
                            "agent_name": name,
                            "path": str(agent_file.relative_to(self.project_path)),
                            "use_count": use_count,
                        }
                    )
            except Exception:
                continue

        return agents

    def get_skill_calls_from_memory(self) -> list[dict[str, Any]]:
        """FALLBACK: Extract skill call usage from .muscle/skills/ directory.

        DEPRECATED: This reads from filesystem which is NOT the source of truth.
        Use update_markers() which queries DB directly instead.

        This method exists for backward compatibility only."""
        skills_dir = self.project_path / ".muscle" / "skills"
        if not skills_dir.exists():
            return []

        skills = []
        for skill_file in skills_dir.glob("*.md"):
            try:
                content = skill_file.read_text()
                name = skill_file.stem.replace("_", " ").replace("-", " ")
                use_count = content.count("<!-- used") + content.count("INVOKED")
                if use_count > 0:
                    skills.append(
                        {
                            "skill_name": name,
                            "path": str(skill_file.relative_to(self.project_path)),
                            "use_count": use_count,
                        }
                    )
            except Exception:
                continue

        return skills

    def get_tooling_notes(self) -> list[str]:
        """Generate tooling notes from current project state."""
        notes = []

        # Check for Ruff config
        ruff_path = self.project_path / "ruff.toml"
        if ruff_path.exists():
            notes.append("Ruff configured for linting (see ruff.toml)")

        # Check for pyproject.toml
        pyproject = self.project_path / "pyproject.toml"
        if pyproject.exists():
            notes.append("Python project configured (see pyproject.toml)")

        # Check for type hints
        try:
            py_files = list(self.project_path.glob("**/*.py"))
            typed = sum(
                1 for f in py_files if "type:" in f.read_text() or "TypeGuard" in f.read_text()
            )
            if py_files and typed / len(py_files) > 0.5:
                notes.append("Project uses type hints extensively")
        except Exception:
            pass

        return notes

    def insert_markers_if_missing(self) -> bool:
        """Insert markers into CLAUDE.md if they don't exist."""
        if not self.claude_md_path.exists():
            logger.warning(f"CLAUDE.md not found at {self.claude_md_path}")
            return False

        content = self.claude_md_path.read_text()
        if PUBLISHED_START in content:
            return True  # Already has markers

        try:
            # Create backup first using shared BackupManager
            self._backup_manager.create_backup("claude_md")

            # Insert markers with empty content
            empty_content = (
                f"{SECTION_CRITICAL_RULES}\n\n"
                f"{SECTION_MISTAKE_CORRECTIONS}\n\n"
                f"{SECTION_AGENT_CALLS}\n\n"
                f"{SECTION_SKILL_CALLS}\n\n"
                f"{SECTION_TOOLING_NOTES}\n"
            )
            updated_content = self._insert_markers(content, empty_content)
            self.claude_md_path.write_text(updated_content)
            return True
        except Exception as e:
            logger.error(f"Failed to insert markers: {e}")
            return False

    def update_markers(self) -> bool:
        """Update markers with latest content from DB (DB-first architecture).

        This method queries project_memory.db directly for authoritative data:
        - critical_rules: learned_rules with high recurrence/success_rate
        - agent_calls: agents ordered by use_count from DB
        - skill_calls: skills ordered by use_count from DB
        - tooling_notes: generated from project state

        Internal markdown (.muscle/CLAUDE.md) is NOT consulted.
        """
        # Import here to avoid circular dependency at module level
        from .project_memory import ProjectMemory

        pm = ProjectMemory(str(self.project_path))

        # Get rules from DB - source of truth
        db_rules = pm.list_learned_rules(
            project_path=str(self.project_path),
            status=None,  # Get all, filter below
            limit=100,
        )
        # Include all rules from DB since they're authoritative
        # Calculate score for sorting: success_rate + recurrence boost, capped at 1.0
        critical_rules = []
        for rule in db_rules:
            success_rate = rule.get("success_rate", 0.0) or 0.0
            recurrence = rule.get("recurrence_count", 0) or 0
            # Score formula: success_rate weighted heavily + recurrence boost
            score = min(success_rate * 0.7 + min(recurrence / 10.0, 0.5), 1.0)
            critical_rules.append(
                {
                    "text": rule.get("rule_text", ""),
                    "score": score,
                    "validated_count": recurrence,
                }
            )

        # Get skills from DB
        db_skills = pm.list_skills(
            project_path=str(self.project_path),
            status="active",
            limit=50,
        )
        skill_calls = [
            {
                "skill_name": s.get("name", ""),
                "path": s.get("file_path", ""),
                "use_count": s.get("use_count", 0),
            }
            for s in db_skills
            if s.get("use_count", 0) > 0
        ]

        # Get agents from DB
        db_agents = pm.list_agents(
            project_path=str(self.project_path),
            status="active",
            limit=50,
        )
        agent_calls = [
            {
                "agent_name": a.get("name", ""),
                "path": a.get("file_path", ""),
                "use_count": a.get("use_count", 0),
            }
            for a in db_agents
            if a.get("use_count", 0) > 0
        ]

        # tooling_notes is generated from project state (not from markdown)
        tooling_notes = self.get_tooling_notes()

        # mistake_corrections: read from DB review_findings (high severity patterns)
        # For now, leave as empty list - can be enhanced to query DB
        mistake_corrections: list[dict] = []

        return self.publish(
            critical_rules=critical_rules,
            mistake_corrections=mistake_corrections,
            agent_calls=agent_calls,
            skill_calls=skill_calls,
            tooling_notes=tooling_notes,
        )
