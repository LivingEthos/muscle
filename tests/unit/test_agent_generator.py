"""
Unit tests for code_review/agent_generator.py
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tools.muscle.code_review.agent_generator import (
    MAX_ACTIVE_AGENTS,
    MAX_AGENT_REVISIONS,
    MIN_EVIDENCE_COUNT,
    AgentGenerator,
    _EvidencePattern,
)


@pytest.fixture
def mock_m27():
    return Mock()


@pytest.fixture
def mock_pm():
    pm = Mock()
    pm.insert_agent = Mock(return_value=1)
    pm.get_agent = Mock(return_value=None)
    pm.list_agents = Mock(return_value=[])
    pm.archive_agent = Mock(return_value=True)
    pm.update_agent_revision = Mock(return_value=True)
    pm.get_active_agents_count = Mock(return_value=0)
    pm.get_least_used_active_agent = Mock(return_value=None)
    pm.count_decisions_for_pattern = Mock(return_value=5)
    pm.list_decisions = Mock(return_value=[])
    return pm


@pytest.fixture
def generator(tmp_path, mock_m27, mock_pm):
    return AgentGenerator(
        project_path=str(tmp_path),
        m27_client=mock_m27,
        project_memory=mock_pm,
    )


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


class TestAgentLifecycleConstants:
    def test_max_active_agents_is_10(self):
        assert MAX_ACTIVE_AGENTS == 10

    def test_max_agent_revisions_is_5(self):
        assert MAX_AGENT_REVISIONS == 5

    def test_min_evidence_count_is_3(self):
        assert MIN_EVIDENCE_COUNT == 3


class TestEvidenceThreshold:
    def test_check_evidence_threshold_passes_with_enough_evidence(self, generator, mock_pm):
        mock_pm.count_decisions_for_pattern.return_value = 5
        result = generator._check_evidence_threshold("some_pattern")
        assert result is True

    def test_check_evidence_threshold_fails_with_insufficient_evidence(self, generator, mock_pm):
        mock_pm.count_decisions_for_pattern.return_value = 2
        result = generator._check_evidence_threshold("some_pattern")
        assert result is False

    def test_check_evidence_threshold_uses_min_evidence_count(self, generator, mock_pm):
        mock_pm.count_decisions_for_pattern.return_value = 3
        result = generator._check_evidence_threshold("some_pattern")
        assert result is True

    def test_check_evidence_threshold_without_pm(self, tmp_path, mock_m27):
        gen = AgentGenerator(project_path=str(tmp_path), m27_client=mock_m27, project_memory=None)
        result = gen._check_evidence_threshold("some_pattern")
        assert result is True  # Should pass if no PM available


class TestCanCreateAgent:
    def test_can_create_agent_passes_when_under_cap(self, generator, mock_pm):
        mock_pm.get_active_agents_count.return_value = 5
        can_create, reason = generator.can_create_agent("test_pattern")
        assert can_create is True

    def test_can_create_agent_fails_when_at_cap_no_archive(self, generator, mock_pm):
        mock_pm.get_active_agents_count.return_value = 10
        mock_pm.get_least_used_active_agent.return_value = None
        can_create, reason = generator.can_create_agent("test_pattern")
        assert can_create is False
        assert "max capacity" in reason

    def test_can_create_agent_archives_least_used_when_at_cap(self, generator, mock_pm):
        mock_pm.get_active_agents_count.return_value = 10
        mock_pm.get_least_used_active_agent.return_value = {
            "id": 1,
            "name": "old_agent",
            "file_path": "/path/to/old_agent.md",
        }
        mock_pm.get_agent.return_value = {
            "id": 1,
            "name": "old_agent",
            "file_path": "/path/to/old_agent.md",
        }
        mock_pm.count_decisions_for_pattern.return_value = 5
        can_create, reason = generator.can_create_agent("test_pattern")
        assert can_create is True
        assert "Archived" in reason
        mock_pm.archive_agent.assert_called_once_with(1)

    def test_can_create_agent_fails_below_evidence_threshold(self, generator, mock_pm):
        mock_pm.get_active_agents_count.return_value = 5
        mock_pm.count_decisions_for_pattern.return_value = 2
        can_create, reason = generator.can_create_agent("test_pattern")
        assert can_create is False
        assert "Evidence threshold not met" in reason


class TestArchiveAgent:
    def test_archive_agent_calls_backup_manager(self, generator, mock_pm):
        agent_id = 42
        mock_pm.get_agent.return_value = {
            "id": agent_id,
            "name": "test_agent",
            "file_path": str(generator.agents_dir / "test_agent.md"),
        }
        (generator.agents_dir / "test_agent.md").write_text("---\nname: test\n---")

        with patch.object(generator, "_get_backup_manager") as mock_get_bm:
            mock_bm = Mock()
            mock_bm.create_backup.return_value = Mock()
            mock_get_bm.return_value = mock_bm

            generator.archive_agent(agent_id)

        mock_pm.archive_agent.assert_called_once_with(agent_id)

    def test_archive_agent_fails_when_agent_not_found(self, generator, mock_pm):
        mock_pm.get_agent.return_value = None
        result = generator.archive_agent(999)
        assert result is False


class TestReviseAgent:
    def test_revise_agent_fails_without_pm(self, tmp_path, mock_m27):
        gen = AgentGenerator(project_path=str(tmp_path), m27_client=mock_m27, project_memory=None)
        result = gen.revise_agent(1)
        assert result is None

    def test_revise_agent_fails_for_nonexistent_agent(self, generator, mock_pm):
        mock_pm.get_agent.return_value = None
        result = generator.revise_agent(999)
        assert result is None

    def test_revise_agent_fails_for_archived_agent(self, generator, mock_pm):
        mock_pm.get_agent.return_value = {
            "id": 1,
            "name": "archived_agent",
            "archived_at": "2026-01-01T00:00:00",
        }
        result = generator.revise_agent(1)
        assert result is None

    def test_revise_agent_fails_at_max_revisions(self, generator, mock_pm):
        mock_pm.get_agent.return_value = {
            "id": 1,
            "name": "maxed_agent",
            "revision_count": 5,
            "archived_at": None,
            "file_path": str(generator.agents_dir / "maxed_agent.md"),
        }
        result = generator.revise_agent(1)
        assert result is None

    def test_revise_agent_succeeds_with_valid_agent(self, generator, mock_pm, mock_m27):
        agent_file = generator.agents_dir / "test_agent.md"
        agent_file.write_text("---\nname: test\ndescription: old\ntriggers:\ncapabilities:\n---")

        mock_pm.get_agent.return_value = {
            "id": 1,
            "name": "test_agent",
            "revision_count": 1,
            "archived_at": None,
            "file_path": str(agent_file),
            "trigger_pattern": "test_pattern",
            "description": "",
            "revision_history_json": "[]",
        }
        mock_pm.list_decisions.return_value = []
        mock_m27.chat.return_value = (
            "---\nname: revised\ndescription: improved\ntriggers:\ncapabilities:\n---\n# Revised Agent",
            {},
        )

        with patch.object(generator, "_get_backup_manager") as mock_get_bm:
            mock_bm = Mock()
            mock_get_bm.return_value = mock_bm

            result = generator.revise_agent(1)

        assert result == str(agent_file)
        mock_pm.update_agent_revision.assert_called_once()

    def test_revise_agent_updates_revision_history(self, generator, mock_pm, mock_m27):
        agent_file = generator.agents_dir / "test_agent.md"
        agent_file.write_text("---\nname: test\ndescription: old\ntriggers:\ncapabilities:\n---")

        existing_history = [{"revised_at": "2026-01-01T00:00:00", "revision_number": 1}]
        mock_pm.get_agent.return_value = {
            "id": 1,
            "name": "test_agent",
            "revision_count": 1,
            "archived_at": None,
            "file_path": str(agent_file),
            "trigger_pattern": "test_pattern",
            "description": "",
            "revision_history_json": json.dumps(existing_history),
        }
        mock_pm.list_decisions.return_value = []
        mock_m27.chat.return_value = (
            "---\nname: revised\ndescription: improved\ntriggers:\ncapabilities:\n---\n# Revised Agent",
            {},
        )

        with patch.object(generator, "_get_backup_manager") as mock_get_bm:
            mock_bm = Mock()
            mock_get_bm.return_value = mock_bm

            generator.revise_agent(1)

        # Verify update_agent_revision was called with expanded history
        call_args = mock_pm.update_agent_revision.call_args
        history_json = call_args[0][1]
        history = json.loads(history_json)
        assert len(history) == 2
        assert history[0]["revision_number"] == 1
        assert history[1]["revision_number"] == 2


class TestBuildPatternFromEvidence:
    def test_build_pattern_from_evidence(self, generator, mock_pm):
        mock_pm.list_decisions.return_value = [
            {
                "id": 1,
                "evidence_json": json.dumps(
                    {"trigger": "test_trigger", "issues": [{"severity": "high"}]}
                ),
            },
            {
                "id": 2,
                "evidence_json": json.dumps(
                    {"trigger": "test_trigger", "issues": [{"severity": "medium"}]}
                ),
            },
        ]

        pattern = generator._build_pattern_from_evidence("test_trigger")

        assert pattern.pattern == "test_trigger"
        assert pattern.category == "inferred"
        assert pattern.occurrences == 2


class TestFetchReviewedIssues:
    def test_fetch_reviewed_issues(self, generator, mock_pm):
        mock_pm.list_decisions.return_value = [
            {
                "id": 1,
                "evidence_json": json.dumps(
                    {
                        "trigger": "test_trigger",
                        "issues": [{"severity": "high", "description": "Issue 1"}],
                    }
                ),
            },
        ]

        issues = generator._fetch_reviewed_issues("test_trigger")

        assert len(issues) >= 1


class TestEvidencePattern:
    def test_evidence_pattern_init(self):
        pattern = _EvidencePattern(
            pattern="test",
            category="security",
            occurrences=5,
            files=["a.py", "b.py"],
        )
        assert pattern.pattern == "test"
        assert pattern.category == "security"
        assert pattern.occurrences == 5
        assert pattern.files == ["a.py", "b.py"]
