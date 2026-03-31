"""
Skill Generator - Creates project-specific skills from detected patterns.

Generates `.md` skill files in `.muscle/skills/` that coding agents can use.

Architecture Decision Record (ADR):
- M2.7 generates skill content based on pattern analysis
- Skills follow standard format with triggers, patterns, and conventions
- Skills are validated before being marked as active
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..m27_client import M27Client

logger = logging.getLogger(__name__)

SKILL_TEMPLATE = """---
name: {name}
description: {description}
triggers:
{trigger_list}
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
    def __init__(self, project_path: str, m27_client: M27Client | None = None):
        self.project_path = Path(project_path)
        self.skills_dir = self.project_path / ".muscle" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.m27 = m27_client or M27Client()
        self._generated_skills: list[str] = []

    def generate_skill(
        self,
        pattern_info: Any,
        reviewed_issues: list[dict[str, Any]],
    ) -> str | None:
        """Generate a skill file from pattern information."""
        skill_name = self._pattern_to_skill_name(pattern_info.pattern)
        skill_path = self.skills_dir / f"{skill_name}.md"

        if skill_path.exists():
            logger.info(f"Skill already exists: {skill_path}")
            return None

        prompt = self._build_skill_prompt(pattern_info, reviewed_issues)

        response_text, _ = self.m27.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a skilled technical writer. Generate a skill file in markdown format.",
        )

        if response_text:
            content = self._parse_skill_content(response_text)
            if content:
                skill_path.write_text(content)
                self._generated_skills.append(skill_name)
                logger.info(f"Generated skill: {skill_path}")
                return str(skill_path)

        return None

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

    def validate_skill(self, skill_path: Path) -> bool:
        """Validate skill has required frontmatter fields."""
        content = skill_path.read_text()
        required_fields = ["name:", "description:", "triggers:"]
        return all(field in content for field in required_fields)
