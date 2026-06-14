"""Unit tests for in-memory repository adapters."""

from __future__ import annotations

from typing import Any

import pytest

from muscle.repository.memory import (
    InMemoryLearningRepository,
    InMemoryProjectRepository,
    InMemoryReviewRepository,
)

# ---------------------------------------------------------------------------
# ProjectRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_save_and_get() -> None:
    repo = InMemoryProjectRepository()
    project: dict[str, Any] = {"id": "p1", "name": "Alpha"}
    repo.save(project)
    assert repo.get_by_id("p1") == project


@pytest.mark.asyncio
async def test_project_get_missing() -> None:
    repo = InMemoryProjectRepository()
    assert repo.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_project_save_overwrites() -> None:
    repo = InMemoryProjectRepository()
    repo.save({"id": "p1", "name": "Alpha"})
    repo.save({"id": "p1", "name": "Beta"})
    assert repo.get_by_id("p1") == {"id": "p1", "name": "Beta"}


@pytest.mark.asyncio
async def test_project_save_without_id_raises() -> None:
    repo = InMemoryProjectRepository()
    with pytest.raises(ValueError, match="'id' key"):
        repo.save({"name": "No ID"})


@pytest.mark.asyncio
async def test_project_list_all_pagination() -> None:
    repo = InMemoryProjectRepository()
    for i in range(5):
        repo.save({"id": f"p{i}", "name": f"Project {i}"})

    assert len(repo.list_all(limit=2, offset=0)) == 2
    assert len(repo.list_all(limit=2, offset=2)) == 2
    assert len(repo.list_all(limit=2, offset=4)) == 1
    assert repo.list_all(limit=2, offset=10) == []


# ---------------------------------------------------------------------------
# ReviewRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_save_and_get() -> None:
    repo = InMemoryReviewRepository()
    review: dict[str, Any] = {"id": "r1", "project_id": "p1", "score": 8}
    repo.save(review)
    assert repo.get_by_id("r1") == review


@pytest.mark.asyncio
async def test_review_get_missing() -> None:
    repo = InMemoryReviewRepository()
    assert repo.get_by_id("missing") is None


@pytest.mark.asyncio
async def test_review_save_without_id_raises() -> None:
    repo = InMemoryReviewRepository()
    with pytest.raises(ValueError, match="'id' key"):
        repo.save({"project_id": "p1"})


@pytest.mark.asyncio
async def test_review_list_for_project() -> None:
    repo = InMemoryReviewRepository()
    repo.save({"id": "r1", "project_id": "p1", "score": 5})
    repo.save({"id": "r2", "project_id": "p1", "score": 7})
    repo.save({"id": "r3", "project_id": "p2", "score": 9})

    p1_reviews = repo.list_for_project("p1")
    assert len(p1_reviews) == 2
    assert {r["id"] for r in p1_reviews} == {"r1", "r2"}

    p2_reviews = repo.list_for_project("p2")
    assert len(p2_reviews) == 1
    assert p2_reviews[0]["id"] == "r3"


@pytest.mark.asyncio
async def test_review_list_for_project_limit() -> None:
    repo = InMemoryReviewRepository()
    for i in range(5):
        repo.save({"id": f"r{i}", "project_id": "p1", "score": i})
    assert len(repo.list_for_project("p1", limit=2)) == 2


@pytest.mark.asyncio
async def test_review_list_for_project_empty() -> None:
    repo = InMemoryReviewRepository()
    assert repo.list_for_project("nonexistent") == []


# ---------------------------------------------------------------------------
# LearningRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_learning_record_and_get() -> None:
    repo = InMemoryLearningRepository()
    entry: dict[str, Any] = {"id": "l1", "project_id": "p1", "lesson": "Use typing"}
    repo.record(entry)
    results = repo.get_for_project("p1")
    assert len(results) == 1
    assert results[0] == entry


@pytest.mark.asyncio
async def test_learning_record_without_id_raises() -> None:
    repo = InMemoryLearningRepository()
    with pytest.raises(ValueError, match="'id' key"):
        repo.record({"project_id": "p1", "lesson": "Oops"})


@pytest.mark.asyncio
async def test_learning_get_for_project_limit() -> None:
    repo = InMemoryLearningRepository()
    for i in range(5):
        repo.record({"id": f"l{i}", "project_id": "p1", "lesson": f"Lesson {i}"})
    assert len(repo.get_for_project("p1", limit=2)) == 2


@pytest.mark.asyncio
async def test_learning_get_for_project_empty() -> None:
    repo = InMemoryLearningRepository()
    assert repo.get_for_project("nonexistent") == []


@pytest.mark.asyncio
async def test_learning_multiple_projects() -> None:
    repo = InMemoryLearningRepository()
    repo.record({"id": "l1", "project_id": "p1", "lesson": "A"})
    repo.record({"id": "l2", "project_id": "p2", "lesson": "B"})
    repo.record({"id": "l3", "project_id": "p1", "lesson": "C"})

    p1 = repo.get_for_project("p1")
    assert len(p1) == 2
    assert [e["lesson"] for e in p1] == ["A", "C"]

    p2 = repo.get_for_project("p2")
    assert len(p2) == 1
    assert p2[0]["lesson"] == "B"
