"""
Tests for project_notes.py (MUS-022).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.project_notes import (
    VALID_CATEGORIES,
    ProjectNotes,
    _delete_project_note,
    _get_project_note,
    _insert_project_note,
    _list_project_notes,
    _update_project_note,
)


@pytest.fixture
def mock_memory() -> MagicMock:
    """Fake ProjectMemory with no filesystem."""
    mem = MagicMock()
    mem._get_connection.return_value = MagicMock()
    return mem


@pytest.fixture
def notes(mock_memory: MagicMock) -> ProjectNotes:
    return ProjectNotes(mock_memory, "/fake/project")


class TestNoteCategories:
    def test_valid_categories(self) -> None:
        assert VALID_CATEGORIES == frozenset(
            [
                "architecture",
                "workflow",
                "gotcha",
                "dependency",
                "integration",
            ]
        )


class TestProjectNotesAdd:
    def test_add_note_calls_insert(self, notes: ProjectNotes, mock_memory: MagicMock) -> None:
        with patch("tools.muscle.project_notes._insert_project_note") as mock_insert:
            mock_insert.return_value = 5

            note_id = notes.add_note(
                category="architecture",
                title="Event-driven design",
                content="Use pub/sub for async",
            )

            assert note_id == 5
            mock_insert.assert_called_once()
            call_kwargs = mock_insert.call_args.kwargs
            assert call_kwargs["category"] == "architecture"
            assert call_kwargs["title"] == "Event-driven design"
            assert call_kwargs["content"] == "Use pub/sub for async"
            assert call_kwargs["project_path"] == "/fake/project"

    def test_add_note_custom_timestamp(self, notes: ProjectNotes, mock_memory: MagicMock) -> None:
        with patch("tools.muscle.project_notes._insert_project_note") as mock_insert:
            mock_insert.return_value = 1
            notes.add_note(
                category="gotcha",
                title="Auth token expiry",
                content="Tokens expire after 1h",
                created_at="2026-01-01T00:00:00",
            )
            call_kwargs = mock_insert.call_args.kwargs
            assert call_kwargs["created_at"] == "2026-01-01T00:00:00"

    def test_add_note_invalid_category(self, notes: ProjectNotes) -> None:
        with pytest.raises(ValueError, match="Invalid category"):
            notes.add_note(category="not_real", title="x", content="")


class TestProjectNotesUpdate:
    def test_update_note_calls_memory(self, notes: ProjectNotes, mock_memory: MagicMock) -> None:
        with (
            patch("tools.muscle.project_notes._get_project_note") as mock_get,
            patch("tools.muscle.project_notes._update_project_note") as mock_update,
        ):
            mock_get.return_value = {"id": 3, "content": "old content", "title": "old title"}
            mock_update.return_value = True

            result = notes.update_note(3, title="New title", content="New content")

            assert result is True
            mock_update.assert_called_once()
            # content is passed positionally, title/category as kwargs
            call_positional = mock_update.call_args[0]
            call_kwargs = mock_update.call_args[1]
            assert call_positional[2] == "New content"  # content is 3rd positional arg
            assert call_kwargs["title"] == "New title"

    def test_update_note_not_found(self, notes: ProjectNotes, mock_memory: MagicMock) -> None:
        with patch("tools.muscle.project_notes._get_project_note") as mock_get:
            mock_get.return_value = None
            result = notes.update_note(999, title="x")
            assert result is False

    def test_update_note_invalid_category(
        self, notes: ProjectNotes, mock_memory: MagicMock
    ) -> None:
        with patch("tools.muscle.project_notes._get_project_note") as mock_get:
            mock_get.return_value = {"id": 1, "content": "c", "title": "t"}
            with pytest.raises(ValueError, match="Invalid category"):
                notes.update_note(1, category="bad_cat")


class TestProjectNotesGet:
    def test_get_notes_returns_note_entries(
        self, notes: ProjectNotes, mock_memory: MagicMock
    ) -> None:
        with patch("tools.muscle.project_notes._list_project_notes") as mock_list:
            mock_list.return_value = [
                {
                    "id": 1,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-01T10:00:00",
                    "category": "architecture",
                    "title": "Event sourcing",
                    "content": "Store events not state",
                    "updated_at": "2026-01-02T10:00:00",
                },
                {
                    "id": 2,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-01T11:00:00",
                    "category": "gotcha",
                    "title": "Auth expiry",
                    "content": "Tokens expire",
                    "updated_at": "2026-01-02T11:00:00",
                },
            ]

            result = notes.get_notes()

            assert len(result) == 2
            assert result[0].category == "architecture"
            assert result[1].category == "gotcha"
            mock_list.assert_called_once_with(
                notes._memory, project_path="/fake/project", category=None, limit=100
            )

    def test_get_notes_filtered_by_category(
        self, notes: ProjectNotes, mock_memory: MagicMock
    ) -> None:
        with patch("tools.muscle.project_notes._list_project_notes") as mock_list:
            mock_list.return_value = []
            notes.get_notes(category="dependency")
            mock_list.assert_called_once_with(
                notes._memory, project_path="/fake/project", category="dependency", limit=100
            )

    def test_get_notes_by_category(self, notes: ProjectNotes, mock_memory: MagicMock) -> None:
        with patch("tools.muscle.project_notes._list_project_notes") as mock_list:
            mock_list.return_value = [
                {
                    "id": 1,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-01T10:00:00",
                    "category": "workflow",
                    "title": "PR process",
                    "content": "Require 2 reviewers",
                    "updated_at": "2026-01-02T10:00:00",
                },
            ]
            result = notes.get_notes_by_category("workflow")
            assert len(result) == 1
            assert result[0].category == "workflow"


class TestProjectNotesDedupe:
    def test_dedupe_merges_similar_titles(
        self, notes: ProjectNotes, mock_memory: MagicMock
    ) -> None:
        """Notes with very similar titles (>= 0.85 similarity) should be merged."""
        with (
            patch("tools.muscle.project_notes._list_project_notes") as mock_list,
            patch("tools.muscle.project_notes._update_project_note") as mock_update,
            patch("tools.muscle.project_notes._delete_project_note") as mock_delete,
        ):
            mock_list.return_value = [
                {
                    "id": 1,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-01T10:00:00",
                    "category": "gotcha",
                    "title": "Auth token expiry bug",
                    "content": "Old note content",
                    "updated_at": "2026-01-01T10:00:00",
                },
                {
                    "id": 2,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-02T10:00:00",
                    "category": "gotcha",
                    "title": "Auth token expiry issue",
                    "content": "Newer note content",
                    "updated_at": "2026-01-02T10:00:00",
                },
            ]

            merged = notes.dedupe_notes(similarity_threshold=0.85)

            assert merged == 1
            # delete_project_note called on the older duplicate
            mock_delete.assert_called_once_with(notes._memory, 1)

    def test_dedupe_no_op_when_dissimilar(
        self, notes: ProjectNotes, mock_memory: MagicMock
    ) -> None:
        with (
            patch("tools.muscle.project_notes._list_project_notes") as mock_list,
            patch("tools.muscle.project_notes._delete_project_note") as mock_delete,
        ):
            mock_list.return_value = [
                {
                    "id": 1,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-01T10:00:00",
                    "category": "architecture",
                    "title": "Microservices",
                    "content": "Content A",
                    "updated_at": "2026-01-01T10:00:00",
                },
                {
                    "id": 2,
                    "project_path": "/fake/project",
                    "created_at": "2026-01-02T10:00:00",
                    "category": "gotcha",
                    "title": "Null pointer",
                    "content": "Content B",
                    "updated_at": "2026-01-02T10:00:00",
                },
            ]

            merged = notes.dedupe_notes()
            assert merged == 0
            mock_delete.assert_not_called()


class TestProjectMemoryHelpers:
    """Unit tests for the standalone helper functions attached to ProjectMemory via monkey-patch."""

    def _make_pm(self) -> MagicMock:
        """Build a partially-real ProjectMemory whose _get_connection returns a mock cursor."""
        from tools.muscle.project_memory import ProjectMemory

        # Create a real-feeling PM without triggering __init__ DB init
        pm = ProjectMemory.__new__(ProjectMemory)
        pm._db_path = ":memory:"
        pm._get_connection = MagicMock()  # type: ignore[attr-defined]
        return pm

    def test_insert_project_note_calls_execute(self) -> None:
        pm = self._make_pm()
        mock_conn = pm._get_connection.return_value
        mock_cursor = mock_conn.cursor.return_value
        mock_cursor.lastrowid = 7

        _insert_project_note(
            pm,
            project_path="/test",
            created_at="2026-01-01T00:00:00",
            category="architecture",
            title="Test",
            content="Content",
            updated_at="2026-01-01T00:00:00",
        )

        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()
        assert mock_cursor.lastrowid == 7

    def test_get_project_note_returns_row(self) -> None:
        pm = self._make_pm()
        mock_row = {"id": 3, "title": "Found"}
        pm._get_connection.return_value.cursor.return_value.fetchone.return_value = mock_row

        result = _get_project_note(pm, note_id=3)

        assert result == mock_row

    def test_update_project_note_builds_set_clause(self) -> None:
        pm = self._make_pm()
        pm._get_connection.return_value.cursor.return_value.rowcount = 1

        result = _update_project_note(pm, note_id=5, title="New title", content="New content")

        assert result is True
        call = pm._get_connection.return_value.cursor.return_value.execute.call_args
        sql = call[0][0]
        assert "UPDATE project_notes SET" in sql
        assert "title = ?" in sql
        assert "content = ?" in sql

    def test_list_project_notes_with_category_filter(self) -> None:
        pm = self._make_pm()
        pm._get_connection.return_value.cursor.return_value.fetchall.return_value = []

        _list_project_notes(pm, project_path="/test", category="gotcha", limit=50)

        call = pm._get_connection.return_value.cursor.return_value.execute.call_args
        sql = call[0][0]
        params = call[0][1]
        assert "category = ?" in sql
        assert params == ["/test", "gotcha", 50]

    def test_delete_project_note_calls_delete_sql(self) -> None:
        pm = self._make_pm()
        pm._get_connection.return_value.cursor.return_value.rowcount = 1

        result = _delete_project_note(pm, note_id=7)

        assert result is True
        pm._get_connection.return_value.cursor.return_value.execute.assert_called_with(
            "DELETE FROM project_notes WHERE id = ?", (7,)
        )
