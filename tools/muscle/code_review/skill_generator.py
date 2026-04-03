"""
Skill Generator - Creates project-specific skills from detected patterns.

DB-FIRST ARCHITECTURE:
- project_memory.db is the SOURCE OF TRUTH for skill metadata and lifecycle state
- Skill files in .muscle/skills/ remain as the readable skill content
- DB tracks: created_at, archived_at, status, evidence_count, revision, reasoning

Skill creation is explainable from stored evidence:
- When a skill is created, the reasoning field records why (evidence from memory_decisions)
- decision record links the skill to the pattern that triggered it

Duplicate suppression:
- skill_similar_exists() checks DB for existing active skills with same trigger_pattern
- Skills are revisioned, not just appended to (revision number increments on update)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..m27_client import M27Client

logger = logging.getLogger(__name__)

SKILL_TEMPLATE = """---
name: {name}
description: {description}
triggers:
{trigger_list}
revision: {revision}
---

# {title}

## What This Skill Does

{intro}

## Patterns to Avoid

{dangerous_patterns}

## Recommended Patterns

{safe_patterns}

## Implementation Guide

{implementation}

## Related Files

{related_files}

## Common Mistakes

{common_mistakes}
"""


class SkillGenerator:
    def __init__(
        self,
        project_path: str,
        m27_client: M27Client | None = None,
        project_memory: Any | None = None,
    ):
        self.project_path = Path(project_path)
        self.skills_dir = self.project_path / ".muscle" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._m27_client = m27_client  # Lazy: only create M27Client when needed
        self._pm = project_memory
        self._generated_skills: list[str] = []

    @property
    def m27(self) -> M27Client:
        """Lazy M27 client initialization to avoid requiring API key for archive-only use."""
        if self._m27_client is None:
            self._m27_client = M27Client()
        return self._m27_client

    def generate_skill(
        self,
        pattern_info: Any,
        reviewed_issues: list[dict[str, Any]],
    ) -> str | None:
        """Generate a skill file from pattern information (DB-first, explainable creation).

        DB-first flow:
        1. Check for existing active skill with same trigger_pattern (suppress duplicate)
        2. Write skill content to file
        3. Write skill metadata to DB (status='active', evidence_count=occurrences)
        4. Record CREATE_SKILL decision in memory_decisions with reasoning/evidence
        5. Return skill path on success, None if suppressed or failed
        """
        # Can only proceed with M27 client for content generation
        if self._m27_client is None:
            from ..m27_client import M27Client

            try:
                self._m27_client = M27Client()
            except ValueError:
                logger.debug("M27 client not available, skipping skill generation")
                return None

        skill_name = self._pattern_to_skill_name(pattern_info.pattern)
        skill_path = self.skills_dir / f"{skill_name}.md"

        # Step 1: DB-first duplicate suppression
        if self._pm:
            existing = self._pm.skill_similar_exists(
                str(self.project_path),
                trigger_pattern=pattern_info.pattern,
                status="active",
            )
            if existing:
                logger.info(
                    f"Skill for pattern '{pattern_info.pattern[:40]}...' already exists "
                    f"(id={existing['id']}), suppressing duplicate"
                )
                # Update evidence_count instead of creating new skill
                if hasattr(pattern_info, "occurrences") and pattern_info.occurrences:
                    self._pm.update_skill_evidence_count(
                        existing["id"],
                        pattern_info.occurrences,
                    )
                return None

        prompt = self._build_skill_prompt(pattern_info, reviewed_issues)

        try:
            response_text, _ = self.m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a skilled technical writer. Generate a skill file in markdown format.",
            )
        except (ValueError, TypeError) as e:
            # M27 client not properly configured (e.g., no API key in tests)
            logger.debug(f"M27 chat failed: {e}, skipping skill generation")
            return None

        if not response_text:
            return None

        content = self._parse_skill_content(response_text)
        if not content:
            return None

        # Step 2: Write skill file (still writes file for readable content)
        revision = 1
        content = self._add_revision_to_frontmatter(content, revision)
        skill_path.write_text(content)
        logger.info(f"Generated skill: {skill_path}")

        # Step 3: Write skill metadata to DB (source of truth for lifecycle)
        if self._pm:
            evidence_count = getattr(pattern_info, "occurrences", 0)
            reasoning = self._build_reasoning(pattern_info, reviewed_issues)
            evidence_json = json.dumps(
                {
                    "occurrences": evidence_count,
                    "confidence": getattr(pattern_info, "confidence", 0.0),
                    "files": list(getattr(pattern_info, "files", []))[:5],
                    "severity_counts": getattr(pattern_info, "severity_counts", {}),
                }
            )

            skill_id = self._pm.insert_skill(
                project_path=str(self.project_path),
                name=skill_name,
                description=self._build_description(pattern_info),
                trigger_pattern=pattern_info.pattern,
                file_path=str(skill_path),
                status="active",
            )

            self._pm.insert_action_log(
                project_path=str(self.project_path),
                action_type="skill_create",
                entity_type="skill",
                entity_id=skill_id,
                details_json=json.dumps(
                    {
                        "skill_name": skill_name,
                        "trigger_pattern": pattern_info.pattern,
                        "evidence_count": evidence_count,
                    }
                ),
            )

            # Update evidence_count
            if skill_id and evidence_count:
                self._pm.update_skill_evidence_count(skill_id, evidence_count)

            # Step 4: Record decision for explainability
            if skill_id:
                self._pm.record_skill_decision(
                    project_path=str(self.project_path),
                    skill_id=skill_id,
                    reasoning=reasoning,
                    evidence_json=evidence_json,
                )

        self._generated_skills.append(skill_name)
        return str(skill_path)

    def _build_reasoning(self, pattern_info: Any, reviewed_issues: list[dict[str, Any]]) -> str:
        """Build explainable reasoning string for why the skill was created."""
        pattern = getattr(pattern_info, "pattern", "unknown")
        category = getattr(pattern_info, "category", "unknown")
        occurrences = getattr(pattern_info, "occurrences", 0)
        confidence = getattr(pattern_info, "confidence", 0.0)

        reasoning = (
            f"Skill created from pattern '{pattern}' (category={category}). "
            f"Detected {occurrences} occurrences with confidence={confidence:.2f}. "
            f"Evidence sourced from memory_decisions table. "
            f"Triggered by {len(reviewed_issues)} reviewed issues."
        )
        return reasoning

    def _build_description(self, pattern_info: Any) -> str:
        """Build skill description from pattern info."""
        category = getattr(pattern_info, "category", "")
        summary = getattr(pattern_info, "summary", "")
        return f"{category}: {summary}" if summary else f"Skill for {category} patterns"

    def _add_revision_to_frontmatter(self, content: str, revision: int) -> str:
        """Add or update revision in frontmatter (revisioning, not append-only)."""
        if "revision:" in content:
            # Update existing revision line
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("revision:"):
                    new_lines.append(f"revision: {revision}")
                else:
                    new_lines.append(line)
            return "\n".join(new_lines)
        else:
            # Insert revision after description in frontmatter
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                new_lines.append(line)
                if line.startswith("description:"):
                    new_lines.append(f"revision: {revision}")
            return "\n".join(new_lines)

    def _pattern_to_skill_name(self, pattern: str) -> str:
        name = pattern.lower()
        name = "".join(c if c.isalnum() else "_" for c in name)
        name = "_".join(w for w in name.split("_") if w)[:50]
        return name or "unnamed_skill"

    def _build_skill_prompt(self, pattern_info: Any, reviewed_issues: list[dict[str, Any]]) -> str:
        issues_text = json.dumps(reviewed_issues[:10], indent=2)

        return f"""Generate a project-specific skill based on this pattern:

Pattern: {pattern_info.pattern}
Category: {pattern_info.category}
Occurrences: {pattern_info.occurrences}
Files affected: {", ".join(pattern_info.files[:5])}
Severity distribution: {json.dumps(pattern_info.severity_counts)}

Sample issues found:
{issues_text}

Generate a skill file with:
1. Frontmatter with name, description, and triggers (file extensions, keywords)
2. What the skill does
3. Patterns to avoid (based on the issues)
4. Recommended patterns
5. Implementation guide
6. Related files (from the issues)
7. Common mistakes to avoid

Keep it concise and actionable. This skill should help a coding agent avoid the same mistakes.
"""

    def _parse_skill_content(self, content: str) -> str | None:
        if "---" in content:
            start = content.find("---")
            second_dash = content.find("---", start + 3)
            if second_dash != -1:
                return content
        return content.strip()

    def get_generated_skills(self) -> list[str]:
        """Return list of skills generated this session."""
        return self._generated_skills.copy()

    def list_skills(self) -> list[Path]:
        """List all skill files in the project."""
        if not self.skills_dir.exists():
            return []
        return list(self.skills_dir.glob("*.md"))

    def update_skill(self, skill_path: Path, new_context: str) -> bool:
        """Revise a skill file with new context (increments revision in DB, not append-only).

        DB-first: looks up skill by file_path in DB, increments revision number.
        """
        if not skill_path.exists():
            return False

        # Get current revision from DB (not from file append)
        revision = 1
        if self._pm:
            skills = self._pm.list_skills(
                project_path=str(self.project_path),
                status="active",
                limit=100,
            )
            for s in skills:
                if s.get("file_path") == str(skill_path):
                    revision = s.get("revision", 1) + 1
                    break

        content = skill_path.read_text()
        timestamp = datetime.now().strftime("%Y-%m-%d")

        # Check if there's already an Update section for today (avoid duplicates)
        if f"## Update ({timestamp})" in content:
            # Replace existing update section instead of adding another
            lines = content.split("\n")
            new_lines = []
            skip_until_next_header = False
            for line in lines:
                if f"## Update ({timestamp})" in line:
                    skip_until_next_header = True
                    new_lines.append(f"## Update ({timestamp})")
                    new_lines.append(new_context)
                    continue
                if skip_until_next_header and line.startswith("## "):
                    skip_until_next_header = False
                if not skip_until_next_header:
                    new_lines.append(line)
            content = "\n".join(new_lines)
        else:
            content += f"\n\n## Update ({timestamp})\n\n{new_context}\n"

        # Update revision in frontmatter (revisioning, not append-only)
        content = self._add_revision_to_frontmatter(content, revision)

        skill_path.write_text(content)
        logger.info(f"Updated skill (rev {revision}): {skill_path}")

        # Update revision in DB
        if self._pm:
            skills = self._pm.list_skills(
                project_path=str(self.project_path),
                status="active",
                limit=100,
            )
            for s in skills:
                if s.get("file_path") == str(skill_path):
                    self._pm.update_skill_revision(s["id"], revision)
                    self._pm.insert_action_log(
                        project_path=str(self.project_path),
                        action_type="skill_revise",
                        entity_type="skill",
                        entity_id=s["id"],
                        details_json=json.dumps(
                            {"revision": revision, "skill_path": str(skill_path)}
                        ),
                    )
                    break

        return True

    def archive_skill(self, skill_path: Path, reason: str = "") -> Path:
        """Archive a skill: set DB status='archived', move file to archived/ subdir.

        DB-first: updates DB record first, then moves file. Reason recorded in DB.
        """
        archived_path = skill_path

        # Update DB first (source of truth for lifecycle)
        if self._pm:
            skills = self._pm.list_skills(
                project_path=str(self.project_path),
                status="active",
                limit=100,
            )
            for s in skills:
                if s.get("file_path") == str(skill_path):
                    self._pm.archive_skill(s["id"], reason)
                    self._pm.insert_action_log(
                        project_path=str(self.project_path),
                        action_type="skill_archive",
                        entity_type="skill",
                        entity_id=s["id"],
                        details_json=json.dumps({"reason": reason, "skill_path": str(skill_path)}),
                    )
                    break

        # Move file to archived/ subdir
        archive_dir = self.skills_dir / "archived"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archived_path = archive_dir / skill_path.name
        if skill_path.exists():
            skill_path.rename(archived_path)
            logger.info(f"Archived skill: {skill_path} -> {archived_path}")

        return archived_path

    def validate_skill(self, skill_path: Path) -> bool:
        """Validate skill has required frontmatter fields."""
        content = skill_path.read_text()
        required_fields = ["name:", "description:", "triggers:"]
        return all(field in content for field in required_fields)
