"""
Unit tests for tui/views.py
"""

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from tools.muscle.tui.views import (
    TUI,
    AgentsView,
    AuditView,
    BackupsView,
    DashboardView,
    FixesView,
    HistoryView,
    KnowledgeView,
    NotesView,
    OptimizationView,
    ProjectsView,
    ReviewsView,
    SettingsView,
    SkillsView,
    View,
    ViewState,
)


def _render(panel) -> str:
    """Render a Rich Panel to a string using a Console."""
    s = StringIO()
    c = Console(file=s, force_terminal=True, width=200)
    c.print(panel)
    return s.getvalue()


class TestViewStateDataUnavailable:
    """TU-02: data_unavailable flag and data_error field."""

    def test_defaults_unavailable_false(self):
        state = ViewState()
        assert state.data_unavailable is False
        assert state.data_error == ""

    def test_fields_settable(self):
        state = ViewState(data_unavailable=True, data_error="DB connection failed")
        assert state.data_unavailable is True
        assert state.data_error == "DB connection failed"


class TestDashboardViewDataUnavailable:
    """TU-02: DashboardView renders explicit error panel on data_unavailable."""

    def test_render_shows_data_unavailable_when_flag_set(self):
        view = DashboardView()
        state = ViewState(data_unavailable=True, data_error="ProjectMemory exploded")
        panel = view.render(state)
        rendered = _render(panel)
        assert "Data unavailable" in rendered
        assert "ProjectMemory exploded" in rendered

    def test_render_data_unavailable_does_not_show_hardcoded_defaults(self):
        """When data_unavailable, fake counts like '0 reviews' must NOT appear."""
        view = DashboardView()
        state = ViewState(
            data_unavailable=True,
            data_error="cannot connect",
            review_count=99,  # hardcoded default that should NOT appear
            pattern_count=77,
        )
        panel = view.render(state)
        rendered = _render(panel)
        # Error message IS present
        assert "Data unavailable" in rendered
        # The fallback hardcoded-default rows are NOT rendered
        assert "Total Reviews" not in rendered
        assert "Patterns Learned" not in rendered

    def test_render_normal_shows_no_unavailable_message(self):
        view = DashboardView()
        state = ViewState(data_unavailable=False, data_error="")
        panel = view.render(state)
        rendered = _render(panel)
        assert "Data unavailable" not in rendered


class TestTUIRefreshDataUnavailable:
    """TU-02: TUI._refresh_data sets data_unavailable when provider raises."""

    def test_provider_raise_sets_data_unavailable(self):
        from unittest.mock import patch

        from tools.muscle.tui.views import TUI

        tui = TUI()
        with patch.object(tui.provider, "get_data", side_effect=RuntimeError("DB locked")):
            tui._refresh_data()
        assert tui.state.data_unavailable is True
        assert "DB locked" in tui.state.data_error
        assert tui.state.data is None

    def test_provider_success_clears_unavailable(self):
        from unittest.mock import patch

        from tools.muscle.tui.data_provider import TUIData
        from tools.muscle.tui.views import TUI

        tui = TUI()
        # First simulate a failure
        with patch.object(tui.provider, "get_data", side_effect=RuntimeError("fail")):
            tui._refresh_data()
        assert tui.state.data_unavailable is True

        # Then simulate recovery
        fake_data = TUIData(project_path="/fake")
        with patch.object(tui.provider, "get_data", return_value=fake_data):
            tui._refresh_data()
        assert tui.state.data_unavailable is False
        assert tui.state.data_error == ""
        assert tui.state.data is fake_data


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

    def test_render_with_model_identity_and_lesson_usage_history(self):
        view = HistoryView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            review_runs=[],
            model_identity_history=[
                {
                    "created_at": "2026-04-16T09:00:00",
                    "requested_label": "gpt-5-mini",
                    "canonical_model_key": "openai/gpt-5-mini@1",
                    "identity_source": "provider_introspection",
                    "confidence": 0.92,
                }
            ],
            lesson_usage_events=[
                {
                    "created_at": "2026-04-16T09:05:00",
                    "stage": "semantic_review",
                    "lesson_source": "model_pack",
                    "lesson_key": "pack-json-retries",
                    "canonical_model_key": "minimax/m2.7@1",
                    "outcome": "positive_fix_verification",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "Model Identity History" in rendered
        assert "gpt-5-mini" in rendered
        assert "Lesson Usage Events" in rendered
        assert "positive_fi" in rendered


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
        assert "No learned patterns" in rendered

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

    def test_render_with_external_lessons(self):
        view = KnowledgeView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            learned_rules=[],
            transferred_lessons=[
                {
                    "source_project_path": "/fake/source-app",
                    "validation_status": "validated",
                    "recommendation": "promote",
                    "status_explanation": "Validated in this project and ready for promotion into local memory",
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "External Overlays" in rendered
        assert "source-app" in rendered
        assert "promote" in rendered


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


class TestAuditView:
    def test_render_empty_state(self):
        view = AuditView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(project_path="/fake", action_logs=[])
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "No audit entries yet" in rendered

    def test_render_with_transferred_lesson_actions(self):
        view = AuditView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            action_logs=[
                {
                    "created_at": "2026-04-15T12:00:00",
                    "action_type": "transferred_lesson_validated",
                    "entity_type": "transferred_lesson",
                    "entity_id": 7,
                    "details_json": (
                        '{"lesson_key":"abcdef1234567890","source_project_path":"/tmp/source-app",'
                        '"success_count":2,"validation_count":2}'
                    ),
                }
            ],
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "lesson validated" in rendered
        assert "source-app" in rendered
        assert "lesson:7@source-app" in rendered


class TestOptimizationView:
    def test_render_returns_panel(self):
        view = OptimizationView()
        state = ViewState(current_project="/fake", data=None)
        panel = view.render(state)
        assert panel is not None

    def test_render_with_optimization_data(self):
        view = OptimizationView()
        from tools.muscle.tui.data_provider import TUIData

        data = TUIData(
            project_path="/fake",
            optimization_hotspots=[
                {
                    "stage": "semantic_review",
                    "total_tokens": 1200,
                    "call_count": 4,
                    "avg_context_chars": 800,
                }
            ],
            optimization_recommendations=[
                {
                    "decision_scope": "semantic_review",
                    "current_value": "expanded_file_slice",
                    "recommended_value": "issue_windows",
                    "reason": "Lower token use without hurting parse success",
                }
            ],
            token_savings_summary={"net_tokens_saved": 300, "gross_tokens_saved": 450},
            optimization_settings={"optimize.default_workflow": "review-smart"},
        )
        state = ViewState(current_project="/fake", data=data)
        panel = view.render(state)
        rendered = _render(panel)
        assert "semantic_review" in rendered
        assert "issue_windows" in rendered
        assert "300" in rendered


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
        with patch.dict(
            "sys.modules", {"tools.muscle.project_memory": None, "tools.muscle.project_notes": None}
        ):
            panel = view.render(state)
            assert panel is not None


class TestTUI:
    def test_init(self):
        tui = TUI()
        assert tui.state is not None
        assert tui.views is not None
        # 14 menu items including Optimize
        assert len(tui.menu_items) == 14
        # 14 views
        assert len(tui.views) == 14

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

    def test_handle_key_o_switches_to_optimize(self):
        tui = TUI()
        tui.state.current_view = View.DASHBOARD
        tui.handle_key("o")
        assert tui.state.current_view == View.OPTIMIZE

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
