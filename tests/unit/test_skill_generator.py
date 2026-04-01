"""
Unit tests for code_review/skill_generator.py
"""

from unittest.mock import Mock

import pytest

from tools.muscle.code_review.skill_generator import SkillGenerator


@pytest.fixture
def mock_m27():
    return Mock()


@pytest.fixture
def generator(tmp_path, mock_m27):
    return SkillGenerator(project_path=str(tmp_path), m27_client=mock_m27)


class TestSkillGenerator:
    def test_init_creates_skills_dir(self, tmp_path, mock_m27):
        SkillGenerator(project_path=str(tmp_path), m27_client=mock_m27)
        assert (tmp_path / ".muscle" / "skills").exists()

    def test_pattern_to_skill_name_basic(self, generator):
        name = generator._pattern_to_skill_name("NullPointerException")
        assert name == "nullpointerexception"
        assert len(name) <= 50

    def test_pattern_to_skill_name_special_chars(self, generator):
        name = generator._pattern_to_skill_name("SQL Injection!")
        assert name == "sql_injection"

    def test_pattern_to_skill_name_long(self, generator):
        name = generator._pattern_to_skill_name("A" * 100)
        assert len(name) == 50

    def test_pattern_to_skill_name_empty(self, generator):
        name = generator._pattern_to_skill_name("")
        assert name == "unnamed_skill"

    def test_list_skills_empty(self, generator):
        assert generator.list_skills() == []

    def test_list_skills_nonexistent(self, generator):
        generator.skills_dir = generator.skills_dir.parent / "nonexistent"
        assert generator.list_skills() == []

    def test_get_generated_skills_initially_empty(self, generator):
        assert generator.get_generated_skills() == []

    def test_validate_skill_missing_frontmatter(self, generator, tmp_path):
        test_file = tmp_path / "bad_skill.md"
        test_file.write_text("# Just a title\nNo frontmatter here")
        assert generator.validate_skill(test_file) is False

    def test_validate_skill_valid(self, generator, tmp_path):
        test_file = tmp_path / "good_skill.md"
        test_file.write_text("---\nname: test\ndescription: A test skill\ntriggers:\n---\n# Test")
        assert generator.validate_skill(test_file) is True

    def test_generate_skill_already_exists(self, generator, tmp_path):
        generator.skills_dir.mkdir(parents=True, exist_ok=True)
        (generator.skills_dir / "existing_skill.md").write_text(
            "---\nname: existing\ndescription:\ntriggers:\n---"
        )
        mock_pattern = Mock()
        mock_pattern.pattern = "existing_skill"
        mock_pattern.category = "general"
        mock_pattern.occurrences = 1
        mock_pattern.files = []
        mock_pattern.severity_counts = {}
        result = generator.generate_skill(mock_pattern, [])
        assert result is None

    def test_build_skill_prompt(self, generator):
        mock_pattern = Mock()
        mock_pattern.pattern = "SQLInjection"
        mock_pattern.category = "security"
        mock_pattern.occurrences = 10
        mock_pattern.files = ["query.py", "db.py"]
        mock_pattern.severity_counts = {"high": 5, "medium": 3}
        issues = [{"severity": "critical", "description": "Raw SQL in query"}]
        prompt = generator._build_skill_prompt(mock_pattern, issues)
        assert "SQLInjection" in prompt
        assert "security" in prompt
        assert "10" in prompt

    def test_parse_skill_content_preserves_frontmatter(self, generator):
        content = "---\nname: test\n---\n# My Skill"
        result = generator._parse_skill_content(content)
        assert result == content

    def test_parse_skill_content_no_frontmatter(self, generator):
        content = "# My Skill\nSome content"
        result = generator._parse_skill_content(content)
        assert result == content.strip()
