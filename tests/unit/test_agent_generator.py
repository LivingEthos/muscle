"""
Unit tests for code_review/agent_generator.py
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from tools.muscle.code_review.agent_generator import AgentGenerator


@pytest.fixture
def mock_m27():
    return Mock()


@pytest.fixture
def generator(tmp_path, mock_m27):
    return AgentGenerator(project_path=str(tmp_path), m27_client=mock_m27)


class TestAgentGenerator:
    def test_init_creates_agents_dir(self, tmp_path, mock_m27):
        AgentGenerator(project_path=str(tmp_path), m27_client=mock_m27)
        assert (tmp_path / ".muscle" / "agents").exists()

    def test_pattern_to_agent_name_basic(self, generator):
        name = generator._pattern_to_agent_name("NullPointerException")
        assert name == "nullpointerexception"
        assert len(name) <= 30

    def test_pattern_to_agent_name_special_chars(self, generator):
        name = generator._pattern_to_agent_name("SQL Injection!")
        assert name == "sql_injection"

    def test_pattern_to_agent_name_long(self, generator):
        name = generator._pattern_to_agent_name("A" * 100)
        assert len(name) == 30

    def test_pattern_to_agent_name_empty(self, generator):
        name = generator._pattern_to_agent_name("")
        assert name == "specialist"

    def test_pattern_to_agent_name_underscores(self, generator):
        name = generator._pattern_to_agent_name("path/to/file")
        assert name == "path_to_file"

    def test_list_agents_empty(self, generator):
        assert generator.list_agents() == []

    def test_list_agents_nonexistent_dir(self, generator):
        generator.agents_dir = generator.agents_dir.parent / "nonexistent_agents"
        assert generator.list_agents() == []

    def test_get_generated_agents_initially_empty(self, generator):
        assert generator.get_generated_agents() == []

    def test_validate_agent_missing_frontmatter(self, generator, tmp_path):
        test_file = tmp_path / "bad_agent.md"
        test_file.write_text("# Just a title\nNo frontmatter here")
        assert generator.validate_agent(test_file) is False

    def test_validate_agent_valid(self, generator, tmp_path):
        test_file = tmp_path / "good_agent.md"
        test_file.write_text(
            "---\nname: test\ndescription: A test agent\ntriggers:\ncapabilities:\n---\n# Test"
        )
        assert generator.validate_agent(test_file) is True

    def test_max_agents_enforced(self, generator, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".muscle" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        for i in range(10):
            (agents_dir / f"agent_{i}.md").write_text(
                "---\nname: a\ndescription: b\ntriggers:\ncapabilities:\n---"
            )
        monkeypatch.setattr(
            AgentGenerator, "list_agents", lambda self: [f"a{i}.md" for i in range(10)]
        )
        result = generator.generate_agent(Mock(), [])
        assert result is None

    def test_generate_agent_already_exists(self, generator, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".muscle" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "existing.md").write_text(
            "---\nname: existing\ndescription: exists\ntriggers:\ncapabilities:\n---"
        )
        monkeypatch.setattr(
            AgentGenerator, "list_agents", lambda self: [Path(str(agents_dir / "existing.md"))]
        )
        mock_pattern = Mock()
        mock_pattern.pattern = "existing"
        result = generator.generate_agent(mock_pattern, [])
        assert result is None

    def test_build_agent_prompt(self, generator):
        mock_pattern = Mock()
        mock_pattern.pattern = "TestPattern"
        mock_pattern.category = "security"
        mock_pattern.occurrences = 5
        mock_pattern.files = ["a.py", "b.py", "c.py"]
        issues = [{"severity": "high", "description": "SQL injection"}]
        prompt = generator._build_agent_prompt(mock_pattern, issues)
        assert "TestPattern" in prompt
        assert "security" in prompt
        assert "5" in prompt

    def test_parse_agent_content_adds_frontmatter(self, generator):
        mock_pattern = Mock()
        mock_pattern.pattern = "test"
        mock_pattern.category = "general"
        content = "# My Agent\nNo frontmatter"
        result = generator._parse_agent_content(content, mock_pattern)
        assert result.startswith("---")

    def test_parse_agent_content_preserves_frontmatter(self, generator):
        mock_pattern = Mock()
        mock_pattern.pattern = "test"
        mock_pattern.category = "general"
        content = "---\nname: test\n---\n# My Agent"
        result = generator._parse_agent_content(content, mock_pattern)
        assert "---" in result
