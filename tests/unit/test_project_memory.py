"""
Unit tests for ProjectMemory.
"""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from tools.muscle.project_memory import ProjectMemory


@pytest.fixture
def temp_project_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def pm(temp_project_dir):
    """Create a ProjectMemory instance with a temporary directory."""
    return ProjectMemory(str(temp_project_dir))


class TestProjectMemoryInitialization:
    """Test ProjectMemory initialization."""

    def test_init_creates_muscle_directory(self, temp_project_dir):
        """Test that initialization creates .muscle directory."""
        _pm = ProjectMemory(str(temp_project_dir))
        muscle_dir = temp_project_dir / ".muscle"
        assert muscle_dir.exists()

    def test_init_creates_database_file(self, temp_project_dir):
        """Test that initialization creates the database file."""
        _pm = ProjectMemory(str(temp_project_dir))
        db_path = temp_project_dir / ".muscle" / "project_memory.db"
        assert db_path.exists()

    def test_init_with_custom_db_path(self, temp_project_dir):
        """Test initialization with a custom database path."""
        custom_path = temp_project_dir / "custom.db"
        _pm = ProjectMemory(str(temp_project_dir), str(custom_path))
        assert custom_path.exists()

    def test_schema_version_set(self, pm):
        """Test that schema version is set after initialization."""
        version = pm.get_schema_version()
        assert version is not None
        # Schema version should be set by migrations (currently 1.5.0)
        assert version in ("1.0.0", "1.1.0", "1.3.0", "1.3.1", "1.4.0", "1.5.0")


class TestTaskHelpers:
    """Test task-related helper methods."""

    def test_insert_task(self, pm, temp_project_dir):
        """Test inserting a task."""
        task_id = pm.insert_task(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            title="Test Task",
            description="A test task description",
            status="pending",
            token_cost=100,
            duration_ms=500,
        )
        assert task_id > 0

    def test_get_task(self, pm, temp_project_dir):
        """Test retrieving a task by ID."""
        task_id = pm.insert_task(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            title="Test Task",
            description="Description",
            status="pending",
        )
        task = pm.get_task(task_id)
        assert task is not None
        assert task["title"] == "Test Task"
        assert task["status"] == "pending"

    def test_update_task_outcome(self, pm, temp_project_dir):
        """Test updating task outcome."""
        task_id = pm.insert_task(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            title="Test Task",
            description="Description",
            status="running",
        )
        result = pm.update_task_outcome(task_id, "Task completed successfully")
        assert result is True
        task = pm.get_task(task_id)
        assert task["outcome"] == "Task completed successfully"

    def test_list_tasks(self, pm, temp_project_dir):
        """Test listing tasks with filters."""
        # Insert multiple tasks
        for i in range(3):
            pm.insert_task(
                project_path=str(temp_project_dir),
                created_at=datetime.now().isoformat(),
                title=f"Task {i}",
                description="Description",
                status="pending",
            )

        tasks = pm.list_tasks(project_path=str(temp_project_dir))
        assert len(tasks) == 3

    def test_list_tasks_filtered_by_status(self, pm, temp_project_dir):
        """Test listing tasks filtered by status."""
        pm.insert_task(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            title="Pending Task",
            description="Description",
            status="pending",
        )
        pm.insert_task(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            title="Completed Task",
            description="Description",
            status="success",
        )

        pending_tasks = pm.list_tasks(project_path=str(temp_project_dir), status="pending")
        assert len(pending_tasks) == 1
        assert pending_tasks[0]["title"] == "Pending Task"


class TestReviewRunHelpers:
    """Test review run helper methods."""

    def test_insert_review_run(self, pm, temp_project_dir):
        """Test inserting a review run."""
        run_id = pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=5,
            token_cost=1000,
            duration_ms=2000,
            created_at=datetime.now().isoformat(),
        )
        assert run_id > 0

    def test_get_review_run(self, pm, temp_project_dir):
        """Test retrieving a review run by ID."""
        run_id = pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=3,
            token_cost=500,
            duration_ms=1000,
            created_at=datetime.now().isoformat(),
        )
        run = pm.get_review_run(run_id)
        assert run is not None
        assert run["review_mode"] == "review"
        assert run["findings_count"] == 3

    def test_list_review_runs(self, pm, temp_project_dir):
        """Test listing review runs."""
        for i in range(2):
            pm.insert_review_run(
                project_path=str(temp_project_dir),
                review_mode="auto-fix" if i % 2 == 0 else "review",
                target_path=f"src/file{i}.py",
                findings_count=i,
                token_cost=100,
                duration_ms=200,
                created_at=datetime.now().isoformat(),
            )

        runs = pm.list_review_runs(project_path=str(temp_project_dir))
        assert len(runs) == 2

        # Filter by mode
        auto_fix_runs = pm.list_review_runs(
            project_path=str(temp_project_dir), review_mode="auto-fix"
        )
        assert len(auto_fix_runs) == 1


class TestReviewFindingHelpers:
    """Test review finding helper methods."""

    def test_insert_review_finding(self, pm, temp_project_dir):
        """Test inserting a review finding."""
        run_id = pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=0,
            token_cost=0,
            duration_ms=0,
            created_at=datetime.now().isoformat(),
        )
        finding_id = pm.insert_review_finding(
            review_run_id=run_id,
            rule_id="RULE001",
            severity="HIGH",
            file_path="src/main.py",
            line_number=42,
            message="Potential security issue",
            auto_fixable=False,
        )
        assert finding_id > 0

    def test_list_findings_for_run(self, pm, temp_project_dir):
        """Test listing findings for a review run."""
        run_id = pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=0,
            token_cost=0,
            duration_ms=0,
            created_at=datetime.now().isoformat(),
        )
        # Insert multiple findings
        for i in range(3):
            pm.insert_review_finding(
                review_run_id=run_id,
                rule_id=f"RULE00{i}",
                severity="MEDIUM",
                file_path="src/main.py",
                line_number=10 * (i + 1),
                message=f"Finding {i}",
            )

        findings = pm.list_findings_for_run(run_id)
        assert len(findings) == 3


class TestFixAttemptHelpers:
    """Test fix attempt helper methods."""

    def test_insert_fix_attempt(self, pm, temp_project_dir):
        """Test inserting a fix attempt."""
        # Create a review run and finding first
        run_id = pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=0,
            token_cost=0,
            duration_ms=0,
            created_at=datetime.now().isoformat(),
        )
        finding_id = pm.insert_review_finding(
            review_run_id=run_id,
            rule_id="RULE001",
            severity="HIGH",
            file_path="src/main.py",
            line_number=42,
            message="Test finding",
        )

        fix_id = pm.insert_fix_attempt(
            finding_id=finding_id,
            fix_content="print('fixed')",
            verification_passed=True,
            notes="Applied successfully",
        )
        assert fix_id > 0


class TestConversationEventHelpers:
    """Test conversation event helper methods."""

    def test_insert_conversation_event(self, pm, temp_project_dir):
        """Test inserting a conversation event."""
        event_id = pm.insert_conversation_event(
            project_path=str(temp_project_dir),
            event_type="task_start",
            timestamp=datetime.now().isoformat(),
            summary="Task started",
            metadata_json='{"key": "value"}',
        )
        assert event_id > 0

    def test_insert_conversation_event_with_task_id(self, pm, temp_project_dir):
        """Test inserting a conversation event linked to a task."""
        task_id = pm.insert_task(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            title="Test Task",
            description="Description",
            status="running",
        )
        event_id = pm.insert_conversation_event(
            project_path=str(temp_project_dir),
            task_id=task_id,
            event_type="task_end",
            timestamp=datetime.now().isoformat(),
            summary="Task completed",
        )
        events = pm.list_conversation_events(task_id=task_id)
        assert len(events) == 1
        assert events[0]["task_id"] == task_id

    def test_list_conversation_events_filtered(self, pm, temp_project_dir):
        """Test listing conversation events with filters."""
        pm.insert_conversation_event(
            project_path=str(temp_project_dir),
            event_type="task_start",
            timestamp=datetime.now().isoformat(),
            summary="Start",
        )
        pm.insert_conversation_event(
            project_path=str(temp_project_dir),
            event_type="task_end",
            timestamp=datetime.now().isoformat(),
            summary="End",
        )

        task_start_events = pm.list_conversation_events(
            project_path=str(temp_project_dir), event_type="task_start"
        )
        assert len(task_start_events) == 1
        assert task_start_events[0]["event_type"] == "task_start"


class TestLearnedRuleHelpers:
    """Test learned rule helper methods."""

    def test_insert_learned_rule(self, pm, temp_project_dir):
        """Test inserting a learned rule."""
        rule_id = pm.insert_learned_rule(
            project_path=str(temp_project_dir),
            rule_text="Always validate user input",
            trigger_pattern="eval_*",
            status="active",
        )
        assert rule_id > 0

    def test_get_learned_rule(self, pm, temp_project_dir):
        """Test retrieving a learned rule by ID."""
        rule_id = pm.insert_learned_rule(
            project_path=str(temp_project_dir),
            rule_text="Test rule",
            trigger_pattern="test_*",
        )
        rule = pm.get_learned_rule(rule_id)
        assert rule is not None
        assert rule["rule_text"] == "Test rule"
        assert rule["recurrence_count"] == 1

    def test_list_learned_rules(self, pm, temp_project_dir):
        """Test listing learned rules."""
        for i in range(3):
            pm.insert_learned_rule(
                project_path=str(temp_project_dir),
                rule_text=f"Rule {i}",
                trigger_pattern=f"pattern_{i}",
            )

        rules = pm.list_learned_rules(project_path=str(temp_project_dir))
        assert len(rules) == 3

    def test_increment_rule_recurrence(self, pm, temp_project_dir):
        """Test incrementing rule recurrence count."""
        rule_id = pm.insert_learned_rule(
            project_path=str(temp_project_dir),
            rule_text="Test rule",
            trigger_pattern="test",
        )
        pm.increment_rule_recurrence(rule_id)
        rule = pm.get_learned_rule(rule_id)
        assert rule["recurrence_count"] == 2
        assert rule["last_triggered"] is not None

    def test_update_rule_success_rate(self, pm, temp_project_dir):
        """Test updating rule success rate."""
        rule_id = pm.insert_learned_rule(
            project_path=str(temp_project_dir),
            rule_text="Test rule",
            trigger_pattern="test",
        )
        pm.update_rule_success_rate(rule_id, success=True)
        rule = pm.get_learned_rule(rule_id)
        assert rule["success_rate"] == 1.0

    def test_promote_rule(self, pm, temp_project_dir):
        """Test promoting a rule to CLAUDE.md."""
        rule_id = pm.insert_learned_rule(
            project_path=str(temp_project_dir),
            rule_text="Important rule",
            trigger_pattern="important",
        )
        result = pm.promote_rule(rule_id)
        assert result is True
        rule = pm.get_learned_rule(rule_id)
        assert rule["status"] == "promoted"
        assert rule["promoted_to_claude_md"] == 1
        assert rule["promoted_at"] is not None


class TestSkillHelpers:
    """Test skill helper methods."""

    def test_insert_skill(self, pm, temp_project_dir):
        """Test inserting a skill."""
        skill_id = pm.insert_skill(
            project_path=str(temp_project_dir),
            name="auth-checker",
            description="Checks authentication patterns",
            trigger_pattern="auth_*",
            file_path=".claude/skills/auth-checker.md",
        )
        assert skill_id > 0

    def test_get_skill(self, pm, temp_project_dir):
        """Test retrieving a skill by ID."""
        skill_id = pm.insert_skill(
            project_path=str(temp_project_dir),
            name="test-skill",
            description="Test description",
            trigger_pattern="test_*",
        )
        skill = pm.get_skill(skill_id)
        assert skill is not None
        assert skill["name"] == "test-skill"
        assert skill["use_count"] == 0

    def test_list_skills(self, pm, temp_project_dir):
        """Test listing skills."""
        for i in range(2):
            pm.insert_skill(
                project_path=str(temp_project_dir),
                name=f"skill-{i}",
                description="Description",
                trigger_pattern=f"pattern_{i}",
            )

        skills = pm.list_skills(project_path=str(temp_project_dir))
        assert len(skills) == 2

    def test_increment_skill_usage(self, pm, temp_project_dir):
        """Test incrementing skill usage."""
        skill_id = pm.insert_skill(
            project_path=str(temp_project_dir),
            name="popular-skill",
            description="A popular skill",
            trigger_pattern="popular",
        )
        pm.increment_skill_usage(skill_id)
        pm.increment_skill_usage(skill_id)
        skill = pm.get_skill(skill_id)
        assert skill["use_count"] == 2
        assert skill["last_used"] is not None


class TestAgentHelpers:
    """Test agent helper methods."""

    def test_insert_agent(self, pm, temp_project_dir):
        """Test inserting an agent."""
        agent_id = pm.insert_agent(
            project_path=str(temp_project_dir),
            name="debug-agent",
            description="Debugs complex issues",
            trigger_pattern="debug_*",
            file_path=".claude/agents/debug-agent.py",
        )
        assert agent_id > 0

    def test_get_agent(self, pm, temp_project_dir):
        """Test retrieving an agent by ID."""
        agent_id = pm.insert_agent(
            project_path=str(temp_project_dir),
            name="test-agent",
            description="Test description",
            trigger_pattern="test_*",
        )
        agent = pm.get_agent(agent_id)
        assert agent is not None
        assert agent["name"] == "test-agent"
        assert agent["use_count"] == 0

    def test_list_agents(self, pm, temp_project_dir):
        """Test listing agents."""
        for i in range(2):
            pm.insert_agent(
                project_path=str(temp_project_dir),
                name=f"agent-{i}",
                description="Description",
                trigger_pattern=f"pattern_{i}",
            )

        agents = pm.list_agents(project_path=str(temp_project_dir))
        assert len(agents) == 2

    def test_increment_agent_usage(self, pm, temp_project_dir):
        """Test incrementing agent usage."""
        agent_id = pm.insert_agent(
            project_path=str(temp_project_dir),
            name="busy-agent",
            description="A busy agent",
            trigger_pattern="busy",
        )
        pm.increment_agent_usage(agent_id)
        agent = pm.get_agent(agent_id)
        assert agent["use_count"] == 1
        assert agent["last_used"] is not None


class TestProjectNoteHelpers:
    """Test project note helper methods."""

    def test_insert_project_note(self, pm, temp_project_dir):
        """Test inserting a project note."""
        note_id = pm.insert_project_note(
            project_path=str(temp_project_dir),
            category="architecture",
            title="System Design",
            content="Important architectural decisions...",
        )
        assert note_id > 0

    def test_get_project_note(self, pm, temp_project_dir):
        """Test retrieving a project note by ID."""
        note_id = pm.insert_project_note(
            project_path=str(temp_project_dir),
            category="notes",
            title="Test Note",
            content="Test content",
        )
        note = pm.get_project_note(note_id)
        assert note is not None
        assert note["title"] == "Test Note"

    def test_list_project_notes_filtered(self, pm, temp_project_dir):
        """Test listing project notes filtered by category."""
        pm.insert_project_note(
            project_path=str(temp_project_dir),
            category="architecture",
            title="Arch Note",
            content="Content",
        )
        pm.insert_project_note(
            project_path=str(temp_project_dir),
            category="security",
            title="Security Note",
            content="Content",
        )

        arch_notes = pm.list_project_notes(
            project_path=str(temp_project_dir), category="architecture"
        )
        assert len(arch_notes) == 1
        assert arch_notes[0]["title"] == "Arch Note"

    def test_update_project_note(self, pm, temp_project_dir):
        """Test updating a project note."""
        note_id = pm.insert_project_note(
            project_path=str(temp_project_dir),
            category="notes",
            title="Original Title",
            content="Original content",
        )
        result = pm.update_project_note(note_id, "Updated content")
        assert result is True
        note = pm.get_project_note(note_id)
        assert note["content"] == "Updated content"
        assert note["updated_at"] != note["created_at"]


class TestAutomationStateHelpers:
    """Test automation state helper methods."""

    def test_set_automation_state(self, pm, temp_project_dir):
        """Test setting an automation state."""
        state_id = pm.set_automation_state(
            project_path=str(temp_project_dir),
            state_key="nightly_last_run",
            state_value="2026-04-01T00:00:00",
        )
        assert state_id > 0

    def test_get_automation_state(self, pm, temp_project_dir):
        """Test getting an automation state by key."""
        pm.set_automation_state(
            project_path=str(temp_project_dir),
            state_key="test_key",
            state_value="test_value",
        )
        state = pm.get_automation_state("test_key")
        assert state is not None
        assert state["state_key"] == "test_key"
        assert state["state_value"] == "test_value"

    def test_set_automation_state_updates_existing(self, pm, temp_project_dir):
        """Test that setting state updates existing key."""
        pm.set_automation_state(
            project_path=str(temp_project_dir),
            state_key="updatable_key",
            state_value="original",
        )
        pm.set_automation_state(
            project_path=str(temp_project_dir),
            state_key="updatable_key",
            state_value="updated",
        )
        state = pm.get_automation_state("updatable_key")
        assert state["state_value"] == "updated"

    def test_list_automation_states(self, pm, temp_project_dir):
        """Test listing automation states."""
        pm.set_automation_state(
            project_path=str(temp_project_dir), state_key="key1", state_value="value1"
        )
        pm.set_automation_state(
            project_path=str(temp_project_dir), state_key="key2", state_value="value2"
        )

        states = pm.list_automation_states(project_path=str(temp_project_dir))
        assert len(states) == 2


class TestBackupHelpers:
    """Test backup helper methods."""

    def test_insert_backup(self, pm, temp_project_dir):
        """Test inserting a backup record."""
        backup_id = pm.insert_backup(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            backup_type="automatic",
            file_path="/backups/project_2026-04-01.tar.gz",
            checksum="abc123",
            size_bytes=1024,
            retention_days=30,
        )
        assert backup_id > 0

    def test_get_backup(self, pm, temp_project_dir):
        """Test retrieving a backup by ID."""
        backup_id = pm.insert_backup(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            backup_type="manual",
            file_path="/backups/manual.tar.gz",
            checksum="def456",
            size_bytes=2048,
            retention_days=90,
        )
        backup = pm.get_backup(backup_id)
        assert backup is not None
        assert backup["backup_type"] == "manual"

    def test_list_backups_filtered(self, pm, temp_project_dir):
        """Test listing backups filtered by type."""
        pm.insert_backup(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            backup_type="automatic",
            file_path="/backups/auto1.tar.gz",
            checksum="abc",
            size_bytes=100,
            retention_days=30,
        )
        pm.insert_backup(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            backup_type="manual",
            file_path="/backups/manual.tar.gz",
            checksum="def",
            size_bytes=200,
            retention_days=90,
        )

        auto_backups = pm.list_backups(
            project_path=str(temp_project_dir), backup_type="automatic"
        )
        assert len(auto_backups) == 1
        assert auto_backups[0]["backup_type"] == "automatic"

    def test_delete_backup(self, pm, temp_project_dir):
        """Test deleting a backup record."""
        backup_id = pm.insert_backup(
            project_path=str(temp_project_dir),
            created_at=datetime.now().isoformat(),
            backup_type="manual",
            file_path="/backups/to_delete.tar.gz",
            checksum="to_del",
            size_bytes=100,
            retention_days=30,
        )
        result = pm.delete_backup(backup_id)
        assert result is True
        assert pm.get_backup(backup_id) is None


class TestChangeEventHelpers:
    """Test change event helper methods."""

    def test_insert_change_event(self, pm, temp_project_dir):
        """Test inserting a change event."""
        event_id = pm.insert_change_event(
            project_path=str(temp_project_dir),
            changed_files_json='["src/a.py", "src/b.py"]',
            diff_summary="Added feature A and B",
        )
        assert event_id > 0

    def test_insert_change_event_with_review_run(self, pm, temp_project_dir):
        """Test inserting a change event linked to a review run."""
        run_id = pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=0,
            token_cost=0,
            duration_ms=0,
            created_at=datetime.now().isoformat(),
        )
        event_id = pm.insert_change_event(
            project_path=str(temp_project_dir),
            changed_files_json='["src/main.py"]',
            diff_summary="Fixed issue from review",
            review_run_id=run_id,
        )
        assert event_id > 0


class TestMemoryDecisionHelpers:
    """Test memory decision helper methods."""

    def test_insert_decision(self, pm, temp_project_dir):
        """Test inserting a memory decision."""
        decision_id = pm.insert_decision(
            project_path=str(temp_project_dir),
            decision_type="promote_rule",
            source_table="learned_rules",
            source_id=1,
            evidence_json='{"recurrence": 5, "success_rate": 0.9}',
            score_json='{"promotion_score": 0.85}',
            reasoning="High recurrence and success rate indicate this rule should be promoted",
        )
        assert decision_id > 0


class TestStatistics:
    """Test statistics helper methods."""

    def test_get_statistics_empty(self, pm, temp_project_dir):
        """Test getting statistics for a project with no data."""
        stats = pm.get_statistics(str(temp_project_dir))
        assert stats["total_tasks"] == 0
        assert stats["total_reviews"] == 0
        assert stats["total_learned_rules"] == 0
        assert stats["total_skills"] == 0
        assert stats["total_agents"] == 0

    def test_get_statistics_with_data(self, pm, temp_project_dir):
        """Test getting statistics with some data."""
        # Add some tasks
        for i in range(2):
            pm.insert_task(
                project_path=str(temp_project_dir),
                created_at=datetime.now().isoformat(),
                title=f"Task {i}",
                description="Description",
                status="success",
                token_cost=100,
                duration_ms=500,
            )

        # Add a review
        pm.insert_review_run(
            project_path=str(temp_project_dir),
            review_mode="review",
            target_path="src/main.py",
            findings_count=5,
            token_cost=200,
            duration_ms=1000,
            created_at=datetime.now().isoformat(),
        )

        # Add a learned rule
        pm.insert_learned_rule(
            project_path=str(temp_project_dir),
            rule_text="Test rule",
            trigger_pattern="test",
        )

        stats = pm.get_statistics(str(temp_project_dir))
        assert stats["total_tasks"] == 2
        assert stats["total_tokens"] == 200
        assert stats["total_reviews"] == 1
        assert stats["total_findings"] == 5
        assert stats["total_learned_rules"] == 1


class TestActionLogHelpers:
    """Test action_log helper methods."""

    def test_insert_action_log(self, pm, temp_project_dir):
        """Test inserting an action log entry."""
        log_id = pm.insert_action_log(
            project_path=str(temp_project_dir),
            action_type="backup",
            entity_type="backup",
            entity_id=1,
            details_json='{"backup_type": "full", "size_bytes": 1024}',
        )
        assert log_id > 0

    def test_list_action_logs(self, pm, temp_project_dir):
        """Test listing action log entries."""
        for i in range(3):
            pm.insert_action_log(
                project_path=str(temp_project_dir),
                action_type="backup",
                entity_type="backup",
                entity_id=i,
                details_json=f'{{"backup_type": "type_{i}"}}',
            )

        logs = pm.list_action_logs(project_path=str(temp_project_dir))
        assert len(logs) == 3

    def test_list_action_logs_filtered_by_action_type(self, pm, temp_project_dir):
        """Test filtering action logs by action type."""
        pm.insert_action_log(
            project_path=str(temp_project_dir),
            action_type="backup",
            entity_type="backup",
        )
        pm.insert_action_log(
            project_path=str(temp_project_dir),
            action_type="publish",
            entity_type="claude_md",
        )

        backup_logs = pm.list_action_logs(
            project_path=str(temp_project_dir), action_type="backup"
        )
        assert len(backup_logs) == 1
        assert backup_logs[0]["action_type"] == "backup"

    def test_list_action_logs_filtered_by_entity_type(self, pm, temp_project_dir):
        """Test filtering action logs by entity type."""
        pm.insert_action_log(
            project_path=str(temp_project_dir),
            action_type="skill_create",
            entity_type="skill",
            entity_id=1,
        )
        pm.insert_action_log(
            project_path=str(temp_project_dir),
            action_type="backup",
            entity_type="backup",
            entity_id=1,
        )

        skill_logs = pm.list_action_logs(
            project_path=str(temp_project_dir), entity_type="skill"
        )
        assert len(skill_logs) == 1
        assert skill_logs[0]["entity_type"] == "skill"

    def test_list_action_logs_respects_limit(self, pm, temp_project_dir):
        """Test that list_action_logs respects the limit parameter."""
        for i in range(10):
            pm.insert_action_log(
                project_path=str(temp_project_dir),
                action_type="backup",
                entity_type="backup",
                entity_id=i,
            )

        logs = pm.list_action_logs(project_path=str(temp_project_dir), limit=5)
        assert len(logs) == 5
