"""
Repository adapters for MUSCLE data persistence.

Provides abstract base classes and in-memory implementations
for Project, Review, and Learning storage.
"""

from __future__ import annotations

from .base import LearningRepository, ProjectRepository, ReviewRepository
from .memory import InMemoryLearningRepository, InMemoryProjectRepository, InMemoryReviewRepository

__all__ = [
    "ProjectRepository",
    "ReviewRepository",
    "LearningRepository",
    "InMemoryProjectRepository",
    "InMemoryReviewRepository",
    "InMemoryLearningRepository",
]
