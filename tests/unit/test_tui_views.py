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
