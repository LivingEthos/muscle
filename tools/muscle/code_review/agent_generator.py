"""
Agent Generator - Creates specialized sub-agents from complex patterns.

Generates Claude Code sub-agent definitions in `.muscle/agents/`.

Architecture Decision Record (ADR):
- Agents are more complex than skills, requiring specialized prompts
- Maximum 10 agents per project to avoid bloat
- Agents reference skills for domain knowledge
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..m27_client import M27Client

logger = logging.getLogger(__name__)

AGENT_TEMPLATE = """---
name: {name}
description: {description}
triggers:
{trigger_list}
capabilities:
{capability_list}
---

# {title}

## Role

{role}

## Capabilities

{capabilities_detail}

## This Project's Conventions

{conventions}

## Workflow

{workflow}

## Output Format

```json
{{
  "status": "success|partial|failed",
  "findings": [],
  "recommendations": []
}}
```

## Notes

{notes}
"""


class AgentGenerator:
    def __init__(self, project_path: str, m27_client: M27Client | None = None):
        self.project_path = Path(project_path)
        self.agents_dir = self.project_path / ".muscle" / "agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.m27 = m27_client or M27Client()
        self._generated_agents: list[str] = []
        self.max_agents = 10

    def generate_agent(
        self,
        pattern_info: Any,
        reviewed_issues: list[dict[str, Any]],
    ) -> str | None:
        """Generate an agent from pattern information."""
        if len(self.list_agents()) >= self.max_agents:
            logger.warning(f"Maximum agents ({self.max_agents}) reached")
            return None

        agent_name = self._pattern_to_agent_name(pattern_info.pattern)
        agent_path = self.agents_dir / f"{agent_name}.md"

        if agent_path.exists():
            logger.info(f"Agent already exists: {agent_path}")
            return None

        prompt = self._build_agent_prompt(pattern_info, reviewed_issues)

        response_text, _ = self.m27.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are an expert at designing Claude Code sub-agents. Generate an agent definition.",
        )

        if response_text:
            content = self._parse_agent_content(response_text, pattern_info)
            if content:
                agent_path.write_text(content)
                self._generated_agents.append(agent_name)
                logger.info(f"Generated agent: {agent_path}")
                return str(agent_path)

        return None

    def _pattern_to_agent_name(self, pattern: str) -> str:
        name = pattern.lower()[:30]
        name = "".join(c if c.isalnum() else "_" for c in name)
        name = "_".join(w for w in name.split("_") if w)
        return name or "specialist"

    def _build_agent_prompt(self, pattern_info: Any, reviewed_issues: list[dict[str, Any]]) -> str:
        issues_text = json.dumps(reviewed_issues[:10], indent=2)

        return f"""Generate a specialized Claude Code sub-agent based on this pattern:

Pattern: {pattern_info.pattern}
Category: {pattern_info.category}
Occurrences: {pattern_info.occurrences}
Files affected: {", ".join(pattern_info.files[:5])}

Sample issues:
{issues_text}

Generate an agent definition with:
1. Frontmatter with name, description, triggers (keywords that invoke this agent)
2. Role description
3. Specific capabilities this agent has
4. This project's conventions (reference .muscle/skills/ if available)
5. Workflow steps
6. Expected output format
7. Notes on usage

The agent should be invoked when the user asks about topics related to {pattern_info.category}.
"""

    def _parse_agent_content(self, content: str, pattern_info: Any) -> str:
        if "---" not in content:
            content = f"---\nname: {pattern_info.pattern}\ndescription: Agent for {pattern_info.category}\n---\n\n{content}"
        return content

    def get_generated_agents(self) -> list[str]:
        """Return list of agents generated this session."""
        return self._generated_agents.copy()

    def list_agents(self) -> list[Path]:
        """List all agent files in the project."""
        if not self.agents_dir.exists():
            return []
        return list(self.agents_dir.glob("*.md"))

    def validate_agent(self, agent_path: Path) -> bool:
        """Validate agent has required frontmatter fields."""
        content = agent_path.read_text()
        required_fields = ["name:", "description:", "triggers:", "capabilities:"]
        return all(field in content for field in required_fields)
