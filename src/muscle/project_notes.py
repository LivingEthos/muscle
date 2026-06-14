"""
ProjectNotes - Structured note capture and retrieval for MUS-022.

Provides a high-level interface for storing, retrieving, and deduplicating
compact project notes across categories: architecture, workflow, gotcha,
dependency, and integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset(
    [
        "architecture",
        "workflow",
        "gotcha",
        "dependency",
        "integration",
    ]
)


@dataclass
class NoteEntry:
    """A single project note entry."""

    id: int
    project_path: str
    created_at: str
    category: str
    title: str
    content: str
    updated_at: str


class ProjectNotes:
    """
    High-level note management backed by the project_notes table.

    Parameters
    ----------
    memory : ProjectMemory
        An initialized ProjectMemory instance pointing at the project.
    project_path : str
        Absolute path to the project root (used as filter in queries).
    """

    def __init__(self, memory: ProjectMemory, project_path: str) -> None:
        self._memory = memory
        self._project_path = project_path

    # -------------------------------------------------------------------------
    # CRUD operations
    # -------------------------------------------------------------------------

    def add_note(
        self,
        category: str,
        title: str,
        content: str,
        created_at: str | None = None,
    ) -> int:
        """
        Store a new note.

        Parameters
        ----------
        category : str
            One of: architecture, workflow, gotcha, dependency, integration.
        title : str
            Short descriptive title.
        content : str
            Note body.
        created_at : str | None
            ISO timestamp. Defaults to now.

        Returns
        -------
        int
            The row ID of the inserted note.

        Raises
        ------
        ValueError
            If category is not a valid category name.
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category {category!r}. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
            )
        ts = created_at or datetime.now().isoformat()
        return _insert_project_note(
            self._memory,
            project_path=self._project_path,
            category=category,
            title=title,
            content=content,
            created_at=ts,
            updated_at=ts,
        )

    def update_note(
        self,
        note_id: int,
        title: str | None = None,
        content: str | None = None,
        category: str | None = None,
    ) -> bool:
        """
        Update an existing note's fields.

        Parameters
        ----------
        note_id : int
            ID of the note to update.
        title : str | None
            New title (if provided).
        content : str | None
            New content (if provided).
        category : str | None
            New category (if provided).

        Returns
        -------
        bool
            True if a row was updated, False if not found.
        """
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category {category!r}. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
            )

        note = _get_project_note(self._memory, note_id)
        if note is None:
            return False

        new_content = content if content is not None else note.get("content", "")
        return _update_project_note(
            self._memory,
            note_id,
            new_content,
            title=title if title is not None else note.get("title"),
            category=category if category is not None else note.get("category"),
        )

    def get_notes(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[NoteEntry]:
        """
        Retrieve notes, optionally filtered by category.

        Parameters
        ----------
        category : str | None
            If provided, only return notes in this category.
        limit : int
            Maximum number of notes to return.

        Returns
        -------
        list[NoteEntry]
            List of matching notes ordered by updated_at desc.
        """
        notes = _list_project_notes(
            self._memory,
            project_path=self._project_path,
            category=category,
            limit=limit,
        )
        return [NoteEntry(**n) for n in notes]

    def get_notes_by_category(self, category: str) -> list[NoteEntry]:
        """
        Retrieve all notes in a specific category.

        Parameters
        ----------
        category : str
            Category to filter by.

        Returns
        -------
        list[NoteEntry]
            Notes in the category, ordered by updated_at desc.
        """
        return self.get_notes(category=category, limit=1000)

    # -------------------------------------------------------------------------
    # Deduplication
    # -------------------------------------------------------------------------

    def dedupe_notes(self, similarity_threshold: float = 0.85) -> int:
        """
        Detect and merge duplicate notes based on title similarity.

        For each pair of notes with similarity >= similarity_threshold,
        the older note is merged into the newer one (newer is kept,
        older is deleted).  Content is concatenated with a divider.

        Parameters
        ----------
        similarity_threshold : float
            Title similarity score (0.0-1.0) above which notes are
            considered duplicates.  Defaults to 0.85.

        Returns
        -------
        int
            Number of duplicate pairs merged.
        """
        notes = self.get_notes(limit=1000)
        merged = 0

        i = 0
        while i < len(notes):
            note_a = notes[i]
            j = i + 1
            while j < len(notes):
                note_b = notes[j]
                ratio = SequenceMatcher(None, note_a.title.lower(), note_b.title.lower()).ratio()
                if ratio >= similarity_threshold:
                    # Keep the newer note, absorb older's content
                    newer = note_b if note_b.updated_at >= note_a.updated_at else note_a
                    older = note_a if newer is note_b else note_b

                    merged_content = (
                        f"{newer.content}\n\n---\nDuplicate of: {older.title}\n{older.content}"
                    )
                    _update_project_note(self._memory, newer.id, merged_content)
                    _delete_project_note(self._memory, older.id)
                    # Remove older from list and refresh
                    notes = [n for n in notes if n.id != older.id]
                    merged += 1
                    break
                j += 1
            i += 1

        return merged


# -----------------------------------------------------------------------------
# ProjectMemory helpers (added to existing class via monkey-patch pattern)
# These methods delegate to the low-level _get_connection helpers below.
# -----------------------------------------------------------------------------


def _insert_project_note(
    self: ProjectMemory,
    project_path: str,
    category: str,
    title: str,
    content: str,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> int:
    """Insert a project note. Auto-generates timestamps if not provided."""
    conn = None
    try:
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        ts_created = created_at or now
        ts_updated = updated_at or now
        cursor.execute(
            """
            INSERT INTO project_notes
            (project_path, created_at, category, title, content, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_path, ts_created, category, title, content, ts_updated),
        )
        conn.commit()
        return cursor.lastrowid or 0
    finally:
        if conn:
            conn.close()


def _get_project_note(self: ProjectMemory, note_id: int) -> dict | None:
    conn = None
    try:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM project_notes WHERE id = ?", (note_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        if conn:
            conn.close()


def _update_project_note(
    self: ProjectMemory,
    note_id: int,
    content: str | None = None,
    **kwargs: Any,
) -> bool:
    """Update a project note. Supports both legacy (note_id, content) and kwargs forms."""
    allowed = {"title", "content", "category", "updated_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    # Backward compatibility: if content is passed as positional arg, use it
    if content is not None:
        updates["content"] = content
    # Always update updated_at timestamp
    updates["updated_at"] = datetime.now().isoformat()
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [note_id]
    conn = None
    try:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE project_notes SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        if conn:
            conn.close()


def _list_project_notes(
    self: ProjectMemory,
    project_path: str,
    category: str | None = None,
    limit: int = 100,
) -> list[dict]:
    conn = None
    try:
        conn = self._get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM project_notes WHERE project_path = ?"
        params: list[Any] = [project_path]
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()


def _delete_project_note(self: ProjectMemory, note_id: int) -> bool:
    conn = None
    try:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM project_notes WHERE id = ?", (note_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        if conn:
            conn.close()
