"""
Unit tests for code_review/agent_kb_fetcher.py
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from tools.muscle.code_review.agent_kb_fetcher import AgentKBFetcher


class TestAgentKBFetcher:
    @pytest.fixture
    def fetcher(self, tmp_path):
        return AgentKBFetcher(project_path=str(tmp_path), cache_ttl_hours=24)

    def test_init_creates_cache_dir(self, tmp_path):
        AgentKBFetcher(project_path=str(tmp_path))
        assert (tmp_path / ".muscle" / "agent_kb").exists()

    def test_parse_subagents_from_readme(self, fetcher):
        content = """
## Subagents

- [Auth Specialist](agents/auth.md) - Handles authentication flows
- [SQL Expert](agents/sql.md) - Database query optimization
- [API Designer](agents/api.md)
"""
        agents = fetcher._parse_subagents_from_readme(content)
        assert len(agents) >= 2
        assert agents[0]["source"] == "awesome-claude-code-subagents"

    def test_parse_skills_from_readme(self, fetcher):
        content = """
## Skills

- [Python Skill](skills/python.md) - Python best practices
- [Rust Skill](skills/rust.md) - Memory safety patterns
"""
        skills = fetcher._parse_skills_from_readme(content)
        assert len(skills) >= 2
        assert skills[0]["source"] == "awesome-claude-skills"

    def test_parse_empty_readme(self, fetcher):
        agents = fetcher._parse_subagents_from_readme("")
        assert agents == []
        skills = fetcher._parse_skills_from_readme("")
        assert skills == []

    def test_fetch_url_network_error(self, fetcher):
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            result = fetcher._fetch_url("https://example.com")
        assert result is None

    def test_save_and_load_cache(self, fetcher, tmp_path):
        fetcher._agents = [
            {
                "name": "TestAgent",
                "url": "http://example.com",
                "description": "Test",
                "source": "test",
                "fetched_at": datetime.now().isoformat(),
            }
        ]
        fetcher._skills = []
        fetcher._save_cache()
        cache_file = tmp_path / ".muscle" / "agent_kb" / "agent_kb_cache.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert len(data["agents"]) == 1

    def test_load_from_cache_expired(self, fetcher, tmp_path):
        cache_dir = tmp_path / ".muscle" / "agent_kb"
        cache_dir.mkdir(parents=True, exist_ok=True)
        old_time = (datetime.now() - timedelta(hours=48)).isoformat()
        cache_file = cache_dir / "agent_kb_cache.json"
        cache_file.write_text(
            json.dumps(
                {
                    "agents": [
                        {
                            "name": "Old",
                            "url": "",
                            "description": "",
                            "source": "",
                            "fetched_at": old_time,
                        }
                    ],
                    "skills": [],
                    "cached_at": old_time,
                }
            )
        )
        fetcher._load_from_cache()
        assert fetcher._agents == []

    def test_search_agents(self, fetcher):
        fetcher._agents = [
            {
                "name": "Auth Specialist",
                "url": "",
                "description": "Handles auth",
                "source": "",
                "fetched_at": "",
            },
            {
                "name": "SQL Expert",
                "url": "",
                "description": "Database queries",
                "source": "",
                "fetched_at": "",
            },
        ]
        results = fetcher.search_agents("auth")
        assert len(results) == 1
        assert results[0]["name"] == "Auth Specialist"

    def test_search_agents_by_description(self, fetcher):
        fetcher._agents = [
            {
                "name": "DB Agent",
                "url": "",
                "description": "Handles database operations",
                "source": "",
                "fetched_at": "",
            },
        ]
        results = fetcher.search_agents("database")
        assert len(results) == 1

    def test_search_skills(self, fetcher):
        fetcher._skills = [
            {
                "name": "Python Skill",
                "url": "",
                "description": "Python patterns",
                "source": "",
                "fetched_at": "",
            },
        ]
        results = fetcher.search_skills("python")
        assert len(results) == 1

    def test_get_agent_template(self, fetcher):
        fetcher._agents = [
            {
                "name": "Auth Specialist",
                "url": "",
                "description": "Handles authentication",
                "source": "",
                "fetched_at": "",
            },
        ]
        template = fetcher.get_agent_template("Auth Specialist")
        assert template is not None
        assert "Auth Specialist" in template

    def test_get_agent_template_no_match(self, fetcher):
        fetcher._agents = []
        template = fetcher.get_agent_template("nonexistent")
        assert template is None

    def test_get_skill_template(self, fetcher):
        fetcher._skills = [
            {
                "name": "Python Skill",
                "url": "",
                "description": "Python best practices",
                "source": "",
                "fetched_at": "",
            },
        ]
        template = fetcher.get_skill_template("Python Skill")
        assert template is not None
        assert "Python Skill" in template

    def test_get_agents_triggers_fetch(self, fetcher):
        with patch.object(fetcher, "_fetch_url", return_value=""):
            with patch.object(fetcher, "_parse_subagents_from_readme", return_value=[]):
                agents = fetcher.get_agents()
        assert isinstance(agents, list)

    def test_get_skills_triggers_fetch(self, fetcher):
        with patch.object(fetcher, "_fetch_url", return_value=""):
            with patch.object(fetcher, "_parse_skills_from_readme", return_value=[]):
                skills = fetcher.get_skills()
        assert isinstance(skills, list)
