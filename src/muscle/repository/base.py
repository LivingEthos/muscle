"""
Abstract base classes for MUSCLE repository adapters.

Architecture Decision Record (ADR):
- Abstract base classes allow swapping between in-memory, SQLite,
  and external storage backends without changing business logic.
- Methods are intentionally simple (CRUD + list) to keep the surface
  area small while the project matures.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any


class ProjectRepository(ABC):
    """Abstract repository for project records."""

    @abstractmethod
    def get_by_id(self, project_id: str) -> dict[str, Any] | None:
        """Retrieve a project by its unique identifier.

        Args:
            project_id: Unique project identifier.

        Returns:
            Project dictionary or None if not found.
        """

    @abstractmethod
    def save(self, project: dict[str, Any]) -> None:
        """Persist a project record.

        Args:
            project: Project dictionary. Must contain an ``id`` key.
        """

    @abstractmethod
    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[dict[str, Any]]:
        """List all projects with pagination.

        Args:
            limit: Maximum number of records to return.
            offset: Number of records to skip.

        Returns:
            Sequence of project dictionaries.
        """


class ReviewRepository(ABC):
    """Abstract repository for review records."""

    @abstractmethod
    def get_by_id(self, review_id: str) -> dict[str, Any] | None:
        """Retrieve a review by its unique identifier.

        Args:
            review_id: Unique review identifier.

        Returns:
            Review dictionary or None if not found.
        """

    @abstractmethod
    def save(self, review: dict[str, Any]) -> None:
        """Persist a review record.

        Args:
            review: Review dictionary. Must contain an ``id`` key.
        """

    @abstractmethod
    def list_for_project(
        self,
        project_id: str,
        limit: int = 100,
    ) -> Sequence[dict[str, Any]]:
        """List reviews associated with a project.

        Args:
            project_id: Project identifier to filter by.
            limit: Maximum number of records to return.

        Returns:
            Sequence of review dictionaries.
        """


class LearningRepository(ABC):
    """Abstract repository for learning entries."""

    @abstractmethod
    def record(self, entry: dict[str, Any]) -> None:
        """Store a learning entry.

        Args:
            entry: Learning dictionary. Should contain ``project_id``
                and ``id`` keys for later retrieval.
        """

    @abstractmethod
    def get_for_project(
        self,
        project_id: str,
        limit: int = 100,
    ) -> Sequence[dict[str, Any]]:
        """Retrieve learning entries for a project.

        Args:
            project_id: Project identifier to filter by.
            limit: Maximum number of records to return.

        Returns:
            Sequence of learning dictionaries.
        """
