"""
Unit tests for tui/views.py
"""

from tools.muscle.tui.views import (
    DashboardView,
    FixesView,
    HistoryView,
    KnowledgeView,
    ProjectsView,
    ReviewsView,
    SettingsView,
    TUI,
    View,
    ViewState,
)


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


class TestDashboardView:
    def test_render(self):
        view = DashboardView()
        state = ViewState(
            current_view=View.DASHBOARD,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None

    def test_render_with_recent_issues(self):
        view = DashboardView()
        state = ViewState(
            current_view=View.DASHBOARD,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[
                {"time": "10:00", "description": "Fixed SQL injection", "pattern": "SQL injection"},
                {"time": "09:00", "description": "Fixed null check", "pattern": "Null check"},
            ],
        )
        panel = view.render(state)
        assert panel is not None


class TestReviewsView:
    def test_render(self):
        view = ReviewsView()
        state = ViewState(
            current_view=View.REVIEWS,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None


class TestHistoryView:
    def test_render(self):
        view = HistoryView()
        state = ViewState(
            current_view=View.HISTORY,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None


class TestSettingsView:
    def test_render(self):
        view = SettingsView()
        state = ViewState(
            current_view=View.SETTINGS,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None


class TestKnowledgeView:
    def test_render(self):
        view = KnowledgeView()
        state = ViewState(
            current_view=View.KNOWLEDGE,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None


class TestFixesView:
    def test_render(self):
        view = FixesView()
        state = ViewState(
            current_view=View.FIXES,
            selected_index=0,
            current_project="/fake",
            review_count=5,
            pattern_count=10,
            last_review="2026-03-31",
            recent_issues=[],
        )
        panel = view.render(state)
        assert panel is not None


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


class TestTUI:
    def test_init(self):
        tui = TUI()
        assert tui.state is not None
        assert tui.views is not None
        assert len(tui.menu_items) == 7

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
        initial = tui.state.current_view
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
