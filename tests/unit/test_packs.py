"""Unit tests for :mod:`muscle.packs` (Phase B.5).

Covers:

- `test_build_pack_produces_content_hash` — pack carries a 64-char hex sha.
- `test_identical_inputs_produce_identical_pack_id` — determinism: the
  canonical body excludes the wall-clock ``Created:`` line, so two builds
  over the same inputs produce the same id even seconds apart.
- `test_pack_round_trip_via_store` — builder writes a file and a DB row;
  ``PackStore.get`` rehydrates an equivalent :class:`Pack`.
- `test_gc_removes_old_packs` — `gc` removes stale packs but preserves
  fresh ones.
- `test_pack_id_propagates_to_response_cache_key` — the pack id changes
  :func:`ResponseCache.build_key` output (key-space split for B.3).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from muscle.migrations import MigrationRunner
from muscle.lesson_resolver import LessonRenderBudget, LessonResolver
from muscle.model_packs import ModelPackManager
from muscle.optimization.context_budgeter import ContextBudgeter
from muscle.packs import Pack, PackBuilder, PackStore
from muscle.project_memory import ProjectMemory
from muscle.response_cache import ResponseCache
from muscle.system_db import SystemDatabase
from muscle.tui.project_manager import ProjectConfig, ProjectManager

logger = logging.getLogger(__name__)

HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FABLE_CANONICAL_KEY = "anthropic/claude-fable-5@2026-06-09"
FABLE_BUNDLE_DIR = (
    Path(__file__).parents[2]
    / "src"
    / "muscle"
    / "model_pack_bundles"
    / "anthropic"
    / "claude-fable-5@2026-06-09"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A fresh project with the full migration chain applied."""
    (tmp_path / ".muscle").mkdir(parents=True, exist_ok=True)
    runner = MigrationRunner(str(tmp_path))
    runner.run()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text(
        "def alpha(x):\n"
        "    # sample\n"
        "    return x + 1\n"
        "\n"
        "class Beta:\n"
        "    def method(self):\n"
        "        return 42\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "beta.py").write_text(
        "import os\n\n"
        "def beta(y):\n"
        "    return y * 2\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def builder(project: Path) -> PackBuilder:
    return PackBuilder(project, ContextBudgeter())


def test_build_pack_produces_content_hash(project: Path, builder: PackBuilder) -> None:
    pack = builder.build(
        task="Review src module for bugs",
        scope=project / "src",
        acceptance="No regressions in existing tests.",
    )
    assert isinstance(pack, Pack)
    assert HEX_SHA256_RE.match(pack.content_sha), (
        f"content_sha should be a 64-char hex sha256; got {pack.content_sha!r}"
    )
    assert len(pack.id) == 16
    assert pack.id == pack.content_sha[:16]
    assert pack.path.exists()
    assert pack.path.read_text(encoding="utf-8").startswith("# Pack")


def test_identical_inputs_produce_identical_pack_id(
    project: Path, builder: PackBuilder
) -> None:
    """Two builds over the same task + scope must produce the same id.

    The on-disk body carries a ``Created:`` ISO timestamp, which would
    differ between calls; ensuring deterministic ids proves the hash is
    computed over the canonical timestamp-free body.
    """
    task = "Review src module for bugs"
    scope = project / "src"
    pack_a = builder.build(task=task, scope=scope, acceptance="crit")
    pack_b = builder.build(task=task, scope=scope, acceptance="crit")
    assert pack_a.id == pack_b.id
    assert pack_a.content_sha == pack_b.content_sha
    # Different tasks must diverge.
    pack_c = builder.build(task="something else entirely", scope=scope)
    assert pack_c.id != pack_a.id


def test_pack_round_trip_via_store(project: Path, builder: PackBuilder) -> None:
    pack = builder.build(
        task="Audit auth paths",
        scope=project / "src" / "alpha.py",
        acceptance="",
    )
    expected_path = project / ".muscle" / "packs" / f"{pack.id}.md"
    assert expected_path.exists()
    assert pack.path == expected_path

    store = PackStore(project)
    rehydrated = store.get(pack.id)
    assert rehydrated is not None
    assert rehydrated.id == pack.id
    assert rehydrated.content_sha == pack.content_sha
    assert rehydrated.task == pack.task
    assert rehydrated.path == pack.path


def test_gc_removes_old_packs(
    project: Path, builder: PackBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = builder.build(task="stale task", scope=project / "src" / "alpha.py")
    fresh = builder.build(task="fresh task", scope=project / "src" / "beta.py")

    # Back-date the stale pack's DB row so it falls behind the gc cutoff.
    past = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    with sqlite3.connect(project / ".muscle" / "project_memory.db") as conn:
        conn.execute(
            "UPDATE packs SET created_at = ? WHERE id = ?", (past, stale.id)
        )
        conn.commit()

    store = PackStore(project)
    removed = store.gc(older_than=timedelta(days=1))
    assert removed == 1
    assert not stale.path.exists()
    assert fresh.path.exists()

    # DB row for the stale pack is also gone.
    with sqlite3.connect(project / ".muscle" / "project_memory.db") as conn:
        rows = conn.execute(
            "SELECT id FROM packs WHERE id = ?", (stale.id,)
        ).fetchall()
    assert rows == []


def test_pack_id_propagates_to_response_cache_key(
    project: Path, builder: PackBuilder, tmp_path: Path
) -> None:
    """Feeding ``pack_id=`` to ``ResponseCache.build_key`` must change the key.

    This proves the B.3 key-space split: two otherwise-identical M2.7 calls
    that differ only by pack participation land in different cache slots.
    """
    pack = builder.build(task="cache key plumbing", scope=project / "src")
    cache_db = tmp_path / "cache.db"
    # Constructor side-effects are fine; we only need the static method.
    ResponseCache(db_path=cache_db)

    base_key = ResponseCache.build_key(
        model_id="MiniMax-M2.7",
        system_prompt="sys",
        user_prompt="user",
        scope_files=[("src/alpha.py", "deadbeef")],
    )
    pack_key = ResponseCache.build_key(
        model_id="MiniMax-M2.7",
        system_prompt="sys",
        user_prompt="user",
        scope_files=[("src/alpha.py", "deadbeef")],
        pack_id=pack.id,
    )
    assert base_key != pack_key
    # Idempotent: same pack id yields the same key.
    pack_key_again = ResponseCache.build_key(
        model_id="MiniMax-M2.7",
        system_prompt="sys",
        user_prompt="user",
        scope_files=[("src/alpha.py", "deadbeef")],
        pack_id=pack.id,
    )
    assert pack_key == pack_key_again


def test_fable_local_model_pack_bundle_validates_and_installs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "home" / ".muscle" / "system.db"
    monkeypatch.setattr("muscle.system_db.DEFAULT_SYSTEM_DB_PATH", db_path)
    manager = ModelPackManager(str(tmp_path))

    metadata = manager.install_bundle(
        FABLE_BUNDLE_DIR,
        expected_canonical_model_key=FABLE_CANONICAL_KEY,
    )

    assert metadata.canonical_model_key == FABLE_CANONICAL_KEY
    assert metadata.version == "0.1.0"
    installed = manager.system_db.list_model_packs()
    assert any(pack["canonical_model_key"] == FABLE_CANONICAL_KEY for pack in installed)
    lessons = manager.system_db.get_model_pack_lessons(FABLE_CANONICAL_KEY)
    assert len(lessons) == 6
    assert {str(row["safety_scope"]) for row in lessons} == {"host-orchestration"}
    manifest = json.loads((FABLE_BUNDLE_DIR / "pack.json").read_text(encoding="utf-8"))
    assert manifest["supported_aliases"] == [
        "anthropic/claude-fable-5@2026-06-09",
        "claude-fable-5",
        "fable 5",
    ]


def test_lesson_resolver_retrieves_fable_host_orchestration_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "home" / ".muscle" / "system.db"
    monkeypatch.setattr("muscle.system_db.DEFAULT_SYSTEM_DB_PATH", db_path)
    project_root = tmp_path / "project"
    project_root.mkdir()
    ProjectManager(project_root).init_project(
        ProjectConfig(name="project", path=project_root, languages=["Python"])
    )
    project_memory = ProjectMemory(str(project_root))
    system_db = SystemDatabase()
    ModelPackManager(
        str(project_root),
        project_memory=project_memory,
        system_db=system_db,
    ).install_bundle(FABLE_BUNDLE_DIR, expected_canonical_model_key=FABLE_CANONICAL_KEY)

    resolver = LessonResolver(
        project_path=str(project_root),
        project_memory=project_memory,
        system_db=system_db,
        project_config=ProjectConfig(
            name="project",
            path=project_root,
            languages=["Python"],
            model_pack_mode="auto",
        ),
        requested_model_label="claude-fable-5",
        provider_endpoint="https://api.anthropic.com/v1/messages",
    )

    result = resolver.resolve_for_prompt(
        query_text="plan a Fable review route with typed verification claims",
        stage="semantic_review",
        session_id="sess-fable",
        language="Python",
        render_budget=LessonRenderBudget(
            name="fable-pack-test",
            max_total_tokens=600,
            source_token_limits={"local": 0, "related": 0, "model-pack": 600, "global": 0},
        ),
    )

    assert result.canonical_model_key == FABLE_CANONICAL_KEY
    fable_lessons = [lesson for lesson in result.lessons if lesson.source == "model-pack"]
    assert fable_lessons
    assert any("host-risk preflight" in lesson.lesson_text for lesson in fable_lessons)
    assert {lesson.metadata["safety_scope"] for lesson in fable_lessons} == {
        "host-orchestration"
    }
