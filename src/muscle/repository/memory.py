"""
In-memory repository implementations.

Architecture Decision Record (ADR):
- Dict/list storage is sufficient for unit tests, CLI demos,
  and early development before a persistent backend is wired in.
- Not thread-safe; use external locking if concurrency is required.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .base import LearningRepository, ProjectRepository, ReviewRepository


class InMemoryProjectRepository(ProjectRepository):
    """In-memory store for project records."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get_by_id(self, project_id: str) -> dict[str, Any] | None:
        """Retrieve a project by its unique identifier."""
        return self._store.get(project_id)

    def save(self, project: dict[str, Any]) -> None:
        """Persist a project record."""
        if "id" not in project:
            raise ValueError("Project dict must contain 'id' key")
        self._store[project["id"]] = project.copy()

    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[dict[str, Any]]:
        """List all projects with pagination."""
        all_projects = list(self._store.values())
        return all_projects[offset : offset + limit]


class InMemoryReviewRepository(ReviewRepository):
    """In-memory store for review records."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get_by_id(self, review_id: str) -> dict[str, Any] | None:
        """Retrieve a review by its unique identifier."""
        return self._store.get(review_id)

    def save(self, review: dict[str, Any]) -> None:
        """Persist a review record."""
        if "id" not in review:
            raise ValueError("Review dict must contain 'id' key")
        self._store[review["id"]] = review.copy()

    def list_for_project(
        self,
        project_id: str,
        limit: int = 100,
    ) -> Sequence[dict[str, Any]]:
        """List reviews associated with a project."""
        matches = [r for r in self._store.values() if r.get("project_id") == project_id]
        return matches[:limit]


class InMemoryLearningRepository(LearningRepository):
    """In-memory store for learning entries."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}

    def record(self, entry: dict[str, Any]) -> None:
        """Store a learning entry."""
        if "id" not in entry:
            raise ValueError("Learning entry dict must contain 'id' key")
        self._entries[entry["id"]] = entry.copy()

    def get_for_project(
        self,
        project_id: str,
        limit: int = 100,
    ) -> Sequence[dict[str, Any]]:
        """Retrieve learning entries for a project."""
        matches = [e for e in self._entries.values() if e.get("project_id") == project_id]
        return matches[:limit]
