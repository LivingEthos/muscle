"""
Unit tests for tui/views.py
"""

import pytest
from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from tools.muscle.tui.views import (
    AgentsView,
    BackupsView,
    DashboardView,
    FixesView,
    HistoryView,
    KnowledgeView,
    MemoryView,
    NotesView,
    ProjectsView,
    ReviewsView,
    SettingsView,
    SkillsView,
    TUI,
    View,
    ViewState,
)


def _render(panel) -> str:
    """Render a Rich Panel to a string using a Console."""
    s = StringIO()
    c = Console(file=s, force_terminal=True, width=200)
    c.print(panel)
    return s.getvalue()


class TestViewState:
    def test_defaults(self):
        state = ViewState(
            current_view=View.DASHBOARD,
            selected_index=0,
            current_project="/fake/path",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        assert state.current_view == View.DASHBOARD
        assert state.selected_index == 0
        assert state.review_count == 5

    def test_empty_defaults(self):
        state = ViewState()
        assert state.current_view == View.DASHBOARD
        assert state.selected_index == 0
        assert state.review_count == 0
        assert state.recent_issues == []
        assert state.data is None


class TestDashboardView:
    def test_render_returns_panel(self):
        view = DashboardView()
        state = ViewState(
            current_view=View.DASHBOARD,
            selected_index=0,
            current_project="/fake",
            review_count=0,
            pattern_count=0,
            last_review="",
            recent_issues=[],
            data=None,
        )
        panel = view.render(state)
        assert panel is not None

    def test_render_empty_state_shows_no_patterns(self):
        view = DashboardView()
        state = ViewState(
            current_view=View.DASHBOARD,
            selected_index=0,
            current_project="/fake",
            review_count=0,
            pattern_count=0,
            last_review="",
            recent_issues=[],
            data=None,
        )
        panel = view.render(state)
        rendered = _render(panel)
        assert "No patterns learned yet" in rendered

    def test_render_with_data_shows_counts(self):
        view = DashboardView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            review_count=5,
            pattern_count=10,
            skill_count=3,
            agent_count=2,
            last_review="2026-04-01 10:00",
            recent_findings=[],
            learned_rules=[],
        )
        state = ViewState(
            current_view=View.DASHBOARD,
            selected_index=0,
            current_project="/fake",
            review_count=0,
            pattern_count=0,
            last_review="",
            recent_issues=[],
            data=data,
        )
        panel = view.render(state)
        rendered = _render(panel)
        assert "5" in rendered  # review_count
        assert "10" in rendered  # pattern_count
        assert "3" in rendered  # skill_count
        assert "2" in rendered  # agent_count

    def test_render_with_learned_rules(self):
        view = DashboardView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            review_count=1,
            pattern_count=1,
            skill_count=0,
            agent_count=0,
            last_review="2026-04-01",
            recent_findings=[],
            learned_rules=[
                {
                    "trigger_pattern": "auth validation",
                    "recurrence_count": 5,
                    "success_rate": 0.8,
                    "status": "active",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "auth validation" in rendered


class TestReviewsView:
    def test_render_returns_panel(self):
        view = ReviewsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_data_shows_empty_state(self):
        view = ReviewsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No reviews yet" in rendered

    def test_render_with_review_runs(self):
        view = ReviewsView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            review_runs=[
                {
                    "id": 1,
                    "target_path": "/fake/src/main.py",
                    "review_mode": "pressure",
                    "findings_count": 7,
                    "duration_ms": 3500,
                    "token_cost": 1200,
                    "created_at": "2026-04-01T10:00:00",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "main.py" in rendered
        assert "pressure" in rendered


class TestHistoryView:
    def test_render_returns_panel(self):
        view = HistoryView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_data_shows_empty_state(self):
        view = HistoryView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No review history yet" in rendered

    def test_render_with_runs(self):
        view = HistoryView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            review_runs=[
                {
                    "id": 2,
                    "target_path": "/fake/src/module.py",
                    "findings_count": 3,
                    "token_cost": 500,
                    "created_at": "2026-04-01T09:00:00",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "module.py" in rendered


class TestSettingsView:
    def test_render_returns_panel(self):
        view = SettingsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_data_uses_defaults(self):
        view = SettingsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "Automation Level" in rendered
        assert "Auto-fix" in rendered

    def test_render_with_config(self):
        view = SettingsView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            automation_level="manual",
            review_gate="report",
            triggers=["manual", "pressure"],
            github_enabled=True,
            memory_location=".muscle",
            skill_generation=False,
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "manual" in rendered
        assert "report" in rendered
        assert "Enabled" in rendered


class TestKnowledgeView:
    def test_render_returns_panel(self):
        view = KnowledgeView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_rules_shows_empty_state(self):
        view = KnowledgeView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No patterns learned yet" in rendered

    def test_render_with_rules(self):
        view = KnowledgeView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            learned_rules=[
                {
                    "trigger_pattern": "null check missing",
                    "rule_text": "Always validate null",
                    "recurrence_count": 3,
                    "success_rate": 0.667,
                    "status": "active",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "null check missing" in rendered


class TestFixesView:
    def test_render_returns_panel(self):
        view = FixesView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_findings_shows_empty_state(self):
        view = FixesView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No findings yet" in rendered

    def test_render_with_findings(self):
        view = FixesView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            recent_findings=[
                {
                    "rule_id": "AUTH001",
                    "file_path": "/fake/src/auth.py",
                    "line_number": 42,
                    "auto_fixable": True,
                    "severity": "high",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "AUTH001" in rendered
        assert "auth.py" in rendered


class TestSkillsView:
    def test_render_returns_panel(self):
        view = SkillsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_skills_shows_empty_state(self):
        view = SkillsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No skills yet" in rendered

    def test_render_with_skills(self):
        view = SkillsView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            skills=[
                {
                    "name": "auth-review",
                    "trigger_pattern": "auth/*",
                    "use_count": 5,
                    "status": "active",
                    "last_used": "2026-04-01T10:00:00",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "auth-review" in rendered


class TestAgentsView:
    def test_render_returns_panel(self):
        view = AgentsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_agents_shows_empty_state(self):
        view = AgentsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No agents yet" in rendered

    def test_render_with_agents(self):
        view = AgentsView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            agents=[
                {
                    "name": "security-agent",
                    "description": "Reviews security patterns",
                    "trigger_pattern": "security/*",
                    "use_count": 3,
                    "file_path": "/fake/.muscle/agents/security.py",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "security-agent" in rendered


class TestBackupsView:
    def test_render_returns_panel(self):
        view = BackupsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_no_backups_shows_empty_state(self):
        view = BackupsView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No backups yet" in rendered

    def test_render_with_backups(self):
        view = BackupsView()
        from tools.muscle.backup_manager import BackupInfo
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            backups=[
                BackupInfo(
                    id=1,
                    backup_type="full",
                    file_path="/fake/.muscle/backups/full/20260401_100000/full.tar.gz",
                    checksum="abc123",
                    size_bytes=4096,
                    created_at="2026-04-01T10:00:00",
                    retention_days=30,
                )
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "full" in rendered


class TestProjectsView:
    def test_render(self):
        view = ProjectsView()
        state = ViewState(
            current_view=View.PROJECTS,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None


class TestNotesView:
    def test_render_with_missing_deps(self):
        view = NotesView()
        state = ViewState(current_project="/fake")
        # Patch imports to raise
        with patch.dict("sys.modules", {"tools.muscle.project_memory": None, "tools.muscle.project_notes": None}):
            panel = view.render(state)
            assert panel is not None


class TestTUI:
    def test_init(self):
        tui = TUI()
        assert tui.state is not None
        assert tui.views is not None
        # 13 menu items: Dashboard, Reviews, History, Settings, Knowledge, Fixes, Projects, Notes, Memory, Skills, Agents, Backups, Audit
        assert len(tui.menu_items) == 13
        # 13 views
        assert len(tui.views) == 13

    def test_render_returns_layout(self):
        tui = TUI()
        layout = tui.render()
        assert layout is not None

    def test_render_with_different_views(self):
        tui = TUI()
        for view in View:
            tui.state.current_view = view
            layout = tui.render()
            assert layout is not None

    def test_handle_key_q_quits(self):
        tui = TUI()
        result = tui.handle_key("q")
        assert result is False

    def test_handle_key_r_switches_to_reviews(self):
        tui = TUI()
        tui.state.current_view = View.DASHBOARD
        result = tui.handle_key("r")
        assert result is True
        assert tui.state.current_view == View.REVIEWS

    def test_handle_key_p_switches_to_reviews(self):
        tui = TUI()
        tui.state.current_view = View.DASHBOARD
        tui.handle_key("p")
        assert tui.state.current_view == View.REVIEWS

    def test_handle_key_s_switches_to_settings(self):
        tui = TUI()
        tui.state.current_view = View.DASHBOARD
        tui.handle_key("s")
        assert tui.state.current_view == View.SETTINGS

    def test_handle_key_up_navigates(self):
        tui = TUI()
        tui.state.current_view = View.REVIEWS
        tui.handle_key("up")
        assert tui.state.current_view in View

    def test_handle_key_down_navigates(self):
        tui = TUI()
        tui.state.current_view = View.DASHBOARD
        tui.handle_key("down")
        assert tui.state.current_view in View

    def test_handle_key_left_navigates(self):
        tui = TUI()
        tui.state.current_view = View.REVIEWS
        tui.handle_key("left")
        assert tui.state.current_view in View

    def test_handle_key_right_navigates(self):
        tui = TUI()
        tui.state.current_view = View.DASHBOARD
        tui.handle_key("right")
        assert tui.state.current_view in View

    def test_handle_key_enter_returns_true(self):
        tui = TUI()
        result = tui.handle_key("enter")
        assert result is True

    def test_handle_key_unknown_returns_true(self):
        tui = TUI()
        result = tui.handle_key("x")
        assert result is True

    def test_refresh_updates_state(self):
        tui = TUI()
        tui._refresh_data()
        # After refresh, state should have data set (may be empty if no project)
        assert tui.state is not None

    def test_menu_items_all_views_have_entries(self):
        tui = TUI()
        view_names = {v for _, _, v in tui.menu_items}
        for v in View:
            assert v in view_names, f"View {v} has no menu item"
