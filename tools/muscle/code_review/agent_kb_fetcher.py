"""
Agent Knowledge Base Fetcher - Fetches best practices from awesome-claude-* repos.

Downloads and parses well-designed agent and skill patterns from community repos.

Architecture Decision Record (ADR):
- Fetches from VoltAgent/awesome-claude-code-subagents
- Fetches from travisvn/awesome-claude-skills
- Caches locally to avoid repeated network calls
- Provides templates MUSCLE can refine for project needs
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

AGENT_KB_CACHE_DIR = ".muscle/agent_kb"
AGENT_REPOS = [
    "https://github.com/VoltAgent/awesome-claude-code-subagents",
    "https://github.com/travisvn/awesome-claude-skills",
]


class AgentKBFetcher:
    def __init__(self, project_path: str | None = None, cache_ttl_hours: int = 24):
        self.project_path = Path(project_path) if project_path else Path.cwd()
        self.cache_dir = self.project_path / AGENT_KB_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._agents: list[dict[str, Any]] = []
        self._skills: list[dict[str, Any]] = []

    def fetch_all(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch and parse all agent KB sources."""
        self._agents = []
        self._skills = []

        for repo_url in AGENT_REPOS:
            if "subagents" in repo_url:
                self._fetch_subagents(repo_url)
            elif "skills" in repo_url:
                self._fetch_skills(repo_url)

        self._save_cache()
        return self._agents, self._skills

    def _fetch_subagents(self, repo_url: str) -> None:
        """Fetch subagent patterns from VoltAgent repo."""
        try:
            readme_url = (
                repo_url.replace("github.com", "raw.githubusercontent.com") + "/main/README.md"
            )
            content = self._fetch_url(readme_url)

            if content:
                agents = self._parse_subagents_from_readme(content)
                self._agents.extend(agents)
                logger.info(f"Fetched {len(agents)} subagent patterns")
        except Exception as e:
            logger.warning(f"Failed to fetch subagents from {repo_url}: {e}")
            self._load_from_cache()

    def _fetch_skills(self, repo_url: str) -> None:
        """Fetch skill patterns from travisvn repo."""
        try:
            readme_url = (
                repo_url.replace("github.com", "raw.githubusercontent.com") + "/main/README.md"
            )
            content = self._fetch_url(readme_url)

            if content:
                skills = self._parse_skills_from_readme(content)
                self._skills.extend(skills)
                logger.info(f"Fetched {len(skills)} skill patterns")
        except Exception as e:
            logger.warning(f"Failed to fetch skills from {repo_url}: {e}")
            self._load_from_cache()

    def _fetch_url(self, url: str) -> str | None:
        """Fetch URL content using urllib."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MUSCLE/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data: bytes = response.read()
                return data.decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _parse_subagents_from_readme(self, content: str) -> list[dict[str, Any]]:
        """Parse subagent entries from README markdown."""
        agents = []

        pattern = r"- \[([^\]]+)\]\(([^\)]+)\)\s*-?\s*([^\n]*)"
        matches = re.findall(pattern, content)

        for name, url, description in matches:
            if url.endswith(".md") or "agent" in name.lower():
                agents.append(
                    {
                        "name": name.strip(),
                        "url": url.strip(),
                        "description": description.strip(),
                        "source": "awesome-claude-code-subagents",
                        "fetched_at": datetime.now().isoformat(),
                    }
                )

        return agents

    def _parse_skills_from_readme(self, content: str) -> list[dict]:
        """Parse skill entries from README markdown."""
        skills = []

        pattern = r"- \[([^\]]+)\]\(([^\)]+)\)\s*-?\s*([^\n]*)"
        matches = re.findall(pattern, content)

        for name, url, description in matches:
            if url.endswith(".md") or "skill" in name.lower():
                skills.append(
                    {
                        "name": name.strip(),
                        "url": url.strip(),
                        "description": description.strip(),
                        "source": "awesome-claude-skills",
                        "fetched_at": datetime.now().isoformat(),
                    }
                )

        return skills

    def _save_cache(self) -> None:
        """Save fetched data to local cache."""
        cache_file = self.cache_dir / "agent_kb_cache.json"
        cache_data = {
            "agents": self._agents,
            "skills": self._skills,
            "cached_at": datetime.now().isoformat(),
        }
        cache_file.write_text(json.dumps(cache_data, indent=2))
        logger.debug(f"Saved agent KB cache to {cache_file}")

    def _load_from_cache(self) -> None:
        """Load data from local cache if available and fresh."""
        cache_file = self.cache_dir / "agent_kb_cache.json"

        if not cache_file.exists():
            return

        try:
            cache_data = json.loads(cache_file.read_text())
            cached_at = datetime.fromisoformat(cache_data["cached_at"])

            if datetime.now() - cached_at < self.cache_ttl:
                self._agents = cache_data.get("agents", [])
                self._skills = cache_data.get("skills", [])
                logger.debug("Loaded agent KB from cache")
            else:
                logger.debug("Agent KB cache expired")
        except Exception as e:
            logger.warning(f"Failed to load agent KB cache: {e}")

    def get_agents(self, force_refresh: bool = False) -> list[dict]:
        """Get cached or freshly-fetched agents."""
        if force_refresh or not self._agents:
            self.fetch_all()
        return self._agents

    def get_skills(self, force_refresh: bool = False) -> list[dict]:
        """Get cached or freshly-fetched skills."""
        if force_refresh or not self._skills:
            self.fetch_all()
        return self._skills

    def search_agents(self, query: str) -> list[dict]:
        """Search agents by name or description."""
        query_lower = query.lower()
        return [
            a
            for a in self.get_agents()
            if query_lower in a.get("name", "").lower()
            or query_lower in a.get("description", "").lower()
        ]

    def search_skills(self, query: str) -> list[dict]:
        """Search skills by name or description."""
        query_lower = query.lower()
        return [
            s
            for s in self.get_skills()
            if query_lower in s.get("name", "").lower()
            or query_lower in s.get("description", "").lower()
        ]

    def get_agent_template(self, category: str) -> str | None:
        """Get agent template for a specific category."""
        agents = self.search_agents(category)
        if agents:
            return f"""# Template for {category} Agent

Based on patterns from community agents.

## Common Patterns
{agents[0].get("description", "N/A")}

## Recommended Structure
- Name: {category.lower()}-specialist
- Triggers: {category.lower()}, related keywords
- Capabilities: Domain-specific checks and validations
"""
        return None

    def get_skill_template(self, category: str) -> str | None:
        """Get skill template for a specific category."""
        skills = self.search_skills(category)
        if skills:
            return f"""# Template for {category} Skill

Based on patterns from community skills.

## Common Patterns
{skills[0].get("description", "N/A")}

## Recommended Structure
- Triggers: {category.lower()}, related keywords
- Patterns to avoid
- Recommended patterns
- Implementation guide
"""
        return None
