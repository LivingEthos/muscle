"""
CLI tests for related-project memory and model-pack commands.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from tools.muscle.cli import cli
from tools.muscle.project_memory import ProjectMemory
from tools.muscle.project_memory_types import ModelPackMetadata
from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager


@pytest.fixture
def isolate_system_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "home" / ".muscle" / "system.db"
    monkeypatch.setattr("tools.muscle.system_db.DEFAULT_SYSTEM_DB_PATH", db_path)
    return db_path


def test_memory_related_command_surfaces_registered_overlap(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    related = tmp_path / "related"
    current.mkdir()
    related.mkdir()
    (current / "pyproject.toml").write_text(
        "[project]\nname='current'\ndependencies=['fastapi']\n",
        encoding="utf-8",
    )
    (related / "pyproject.toml").write_text(
        "[project]\nname='related'\ndependencies=['fastapi']\n",
        encoding="utf-8",
    )

    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(related).init_project(
        ProjectConfig(name="related", path=related, languages=["Python"])
    )

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        result = runner.invoke(cli, ["memory", "related"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Related Projects" in result.output
    assert "related" in result.output
    assert "Why" in result.output
    assert "fastapi" in result.output


def test_memory_refresh_catalog_prunes_missing_projects(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    stale = tmp_path / "stale"
    current.mkdir()
    stale.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(stale).init_project(
        ProjectConfig(name="stale", path=stale, languages=["Python"])
    )
    ProjectManager(stale).register_project(stale)
    shutil.rmtree(stale)

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        result = runner.invoke(
            cli,
            ["memory", "refresh-catalog", "--prune-stale"],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Refreshed" in result.output
    assert "Pruned" in result.output


def test_model_select_and_status_update_project_config(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(ProjectConfig(name="model-test", path=tmp_path, languages=["Python"]))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        select_result = runner.invoke(
            cli,
            ["model", "select", "--canonical-model", "openai/gpt-5@1", "--pack-mode", "auto"],
            catch_exceptions=False,
        )
        status_result = runner.invoke(cli, ["model", "status"], catch_exceptions=False)

    assert select_result.exit_code == 0
    assert status_result.exit_code == 0

    config = json.loads((tmp_path / ".muscle" / "config.yaml").read_text(encoding="utf-8"))
    assert config["project"]["canonical_model_key"] == "openai/gpt-5@1"
    assert config["project"]["model_manual_override"] == "openai/gpt-5@1"
    assert config["project"]["model_pack_mode"] == "auto"
    assert "openai/gpt-5@1" in status_result.output


def test_settings_model_updates_related_and_pack_policy(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(ProjectConfig(name="model-test", path=tmp_path, languages=["Python"]))

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            [
                "settings",
                "model",
                "--canonical-model",
                "minimax/m2.7@1",
                "--pack-mode",
                "suggest",
                "--related-mode",
                "off",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    config = json.loads((tmp_path / ".muscle" / "config.yaml").read_text(encoding="utf-8"))
    assert config["project"]["canonical_model_key"] == "minimax/m2.7@1"
    assert config["project"]["model_manual_override"] == "minimax/m2.7@1"
    assert config["project"]["model_pack_mode"] == "suggest"
    assert config["project"]["related_project_mode"] == "off"


def test_model_history_command_shows_recent_identity_events(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(ProjectConfig(name="model-test", path=tmp_path, languages=["Python"]))
    pm = ProjectMemory(str(tmp_path))
    resolved_project_path = str(tmp_path.resolve())
    pm.insert_model_identity_history(
        resolved_project_path,
        {
            "requested_label": "claude-sonnet-4",
            "provider_endpoint": "https://gateway.example.com/anthropic",
            "canonical_model_key": None,
            "identity_source": "unresolved",
            "confidence": 0.0,
            "manual_override": False,
        },
    )
    pm.insert_model_identity_history(
        resolved_project_path,
        {
            "requested_label": "gpt-5-mini",
            "provider_endpoint": "https://api.openai.com/v1",
            "canonical_model_key": "openai/gpt-5-mini@1",
            "identity_source": "provider_introspection",
            "confidence": 0.9,
            "manual_override": False,
        },
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(cli, ["model", "history", "--limit", "5"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Model Identity History" in result.output
    assert result.output.index("gpt-5-m") < result.output.index("claude-")
    assert "openai/" in result.output


def test_model_pack_export_install_and_list(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(
        ProjectConfig(
            name="pack-test",
            path=tmp_path,
            languages=["Python"],
            canonical_model_key="minimax/m2.7@1",
            model_manual_override="minimax/m2.7@1",
        )
    )
    pm = ProjectMemory(str(tmp_path))
    pm.insert_learned_rule(str(tmp_path), "Prefer schema-safe retries for JSON output", "json")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        export_result = runner.invoke(
            cli,
            ["model", "packs", "export-candidate", "--canonical-model", "minimax/m2.7@1"],
            catch_exceptions=False,
        )

    assert export_result.exit_code == 0
    export_root = tmp_path / ".muscle" / "model-pack-exports"
    bundle_dir = next(export_root.rglob("pack.json")).parent
    lessons_payload = json.loads((bundle_dir / "lessons.json").read_text(encoding="utf-8"))
    assert isinstance(lessons_payload, dict)
    assert lessons_payload["lesson_count"] == 1

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        install_result = runner.invoke(
            cli,
            ["model", "packs", "install", "--bundle-path", str(bundle_dir)],
            catch_exceptions=False,
        )
        list_result = runner.invoke(cli, ["model", "packs", "list"], catch_exceptions=False)

    assert install_result.exit_code == 0
    assert list_result.exit_code == 0
    assert "minimax/m2.7@1" in list_result.output


def test_model_pack_scaffold_repo_command(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(ProjectConfig(name="pack-test", path=tmp_path, languages=["Python"]))
    output_dir = tmp_path / "model-pack-repo"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            ["model", "packs", "scaffold-repo", "--output-dir", str(output_dir)],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Scaffolded" in result.output
    assert (output_dir / "pack-repository.json").exists()
    assert (output_dir / "schemas" / "pack.schema.json").exists()


def test_model_pack_install_from_repo_command(
    tmp_path: Path,
    isolate_system_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(
        ProjectConfig(
            name="pack-test",
            path=tmp_path,
            languages=["Python"],
            canonical_model_key="minimax/m2.7@1",
            model_manual_override="minimax/m2.7@1",
        )
    )

    calls: list[tuple[str, str, str, str | None]] = []

    class StubManager:
        def __init__(self, project_path: str):
            self.project_path = project_path

        def install_remote_bundle(
            self,
            canonical_model_key: str,
            *,
            repo: str,
            ref: str,
            expected_canonical_model_key: str | None = None,
        ) -> ModelPackMetadata:
            calls.append((canonical_model_key, repo, ref, expected_canonical_model_key))
            return ModelPackMetadata(
                canonical_model_key=canonical_model_key,
                version="1.2.3",
                install_status="installed",
                source_repo=repo,
                source_repo_commit="abcdef123456",
                pack_path=str(tmp_path / ".muscle" / "cache-pack"),
            )

    monkeypatch.setattr("tools.muscle.cli.ModelPackManager", StubManager)

    with pytest.MonkeyPatch.context() as chdir_patch:
        chdir_patch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            [
                "model",
                "packs",
                "install",
                "--canonical-model",
                "minimax/m2.7@1",
                "--repo",
                "LivingEthos/muscle-model-packs",
                "--ref",
                "main",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Installed" in result.output
    assert calls == [
        (
            "minimax/m2.7@1",
            "LivingEthos/muscle-model-packs",
            "main",
            "minimax/m2.7@1",
        )
    ]


def test_model_pack_update_command(
    tmp_path: Path,
    isolate_system_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(ProjectConfig(name="pack-test", path=tmp_path, languages=["Python"]))

    calls: list[tuple[str, str | None, str | None, str | None]] = []

    class StubManager:
        def __init__(self, project_path: str):
            self.project_path = project_path

        def update_bundle(
            self,
            canonical_model: str,
            bundle_path: str | None,
            *,
            repo: str | None = None,
            ref: str | None = None,
        ) -> ModelPackMetadata:
            calls.append((canonical_model, bundle_path, repo, ref))
            return ModelPackMetadata(
                canonical_model_key=canonical_model,
                version="2.0.0",
                install_status="installed",
                source_repo=repo or "LivingEthos/muscle-model-packs",
                source_repo_commit="abcdef123456",
                pack_path=str(tmp_path / ".muscle" / "cache-pack"),
            )

    monkeypatch.setattr("tools.muscle.cli.ModelPackManager", StubManager)

    with pytest.MonkeyPatch.context() as chdir_patch:
        chdir_patch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            [
                "model",
                "packs",
                "update",
                "--canonical-model",
                "minimax/m2.7@1",
                "--repo",
                "LivingEthos/muscle-model-packs",
                "--ref",
                "main",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Updated" in result.output
    assert calls == [
        (
            "minimax/m2.7@1",
            None,
            "LivingEthos/muscle-model-packs",
            "main",
        )
    ]


def test_model_pack_submit_reuses_existing_submission_output(
    tmp_path: Path,
    isolate_system_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(ProjectConfig(name="pack-test", path=tmp_path, languages=["Python"]))
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    calls = {"submit": 0}

    class StubManager:
        def __init__(self, project_path: str):
            self.project_path = project_path

        def submit_draft_pr(
            self,
            bundle_path: str,
            repo: str,
            base_branch: str,
        ) -> dict[str, object]:
            calls["submit"] += 1
            return {
                "export_id": "abc123",
                "requested_export_id": "xyz999",
                "repo": repo,
                "branch": "muscle-pack/minimax-m2.7-abcdef123456",
                "pr_url": "https://example.com/pr/7",
                "status": "duplicate_existing",
                "duplicate_of_export_id": "abc123",
            }

    monkeypatch.setattr("tools.muscle.cli.ModelPackManager", StubManager)

    with pytest.MonkeyPatch.context() as chdir_patch:
        chdir_patch.chdir(tmp_path)
        result = runner.invoke(
            cli,
            ["model", "packs", "submit", "--bundle-path", str(bundle_dir)],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "Reused existing draft submission." in result.output
    assert calls["submit"] == 1


def test_model_pack_install_rejects_bundle_for_different_selected_model(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    runner = CliRunner()
    manager = ProjectManager(tmp_path)
    manager.init_project(
        ProjectConfig(
            name="pack-test",
            path=tmp_path,
            languages=["Python"],
            canonical_model_key="openai/gpt-5@1",
            model_manual_override="openai/gpt-5@1",
        )
    )
    pm = ProjectMemory(str(tmp_path))
    pm.insert_learned_rule(str(tmp_path), "Prefer schema-safe retries for JSON output", "json")

    export_root = tmp_path / ".muscle" / "model-pack-exports"
    bundle_dir = export_root / "minimax__m2.7_1" / "manual-bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "pack.json").write_text(
        json.dumps(
            {
                "canonical_model_key": "minimax/m2.7@1",
                "version": "0.1.0",
                "supported_aliases": [],
                "export_id": "manual-bundle",
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "lessons.json").write_text(
        json.dumps(
            [
                {
                    "canonical_model_key": "minimax/m2.7@1",
                    "lesson_key": "pack-1",
                    "lesson_text": "Use concise structured retries.",
                    "scope_tags": ["python"],
                    "safety_scope": "review-only",
                    "portability": "portable",
                    "evidence": {},
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(tmp_path)
        install_result = runner.invoke(
            cli,
            ["model", "packs", "install", "--bundle-path", str(bundle_dir)],
            catch_exceptions=False,
        )

    assert install_result.exit_code != 0
    assert "incompatible with current model family" in install_result.output


def test_memory_import_project_snapshot_imports_provisional_lessons(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    (current / "pyproject.toml").write_text(
        "[project]\nname='current'\ndependencies=['fastapi']\n",
        encoding="utf-8",
    )
    (source / "pyproject.toml").write_text(
        "[project]\nname='source'\ndependencies=['fastapi']\n",
        encoding="utf-8",
    )
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Prefer schema-first retries", "json")

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        result = runner.invoke(
            cli,
            [
                "memory",
                "import-project",
                "--project",
                str(source),
                "--mode",
                "snapshot",
            ],
            catch_exceptions=False,
        )

    current_pm = ProjectMemory(str(current))
    lessons = current_pm.list_transferred_lessons(project_path=str(current))

    assert result.exit_code == 0
    assert "Imported" in result.output
    assert "Overlap:" in result.output
    assert len(lessons) == 1
    assert lessons[0]["validation_status"] == "provisional"


def test_memory_lesson_feedback_records_manual_confirmation(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        result = runner.invoke(
            cli,
            ["memory", "lesson-feedback", "--lesson-key", str(lesson["lesson_key"]), "--accept"],
            catch_exceptions=False,
        )

    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    usage_events = current_pm.list_lesson_usage_events(project_path=str(current))

    assert result.exit_code == 0
    assert "confirmed" in result.output
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 1
    assert usage_events[0]["outcome"] == "positive_user_confirmation"


def test_memory_promotion_candidates_and_promote_lesson_commands(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.record_transferred_lesson_outcome(str(lesson["lesson_key"]), success=True)
    current_pm.record_manual_transferred_lesson_feedback(
        str(lesson["lesson_key"]),
        success=True,
        note="Confirmed before local promotion.",
    )

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        candidates_result = runner.invoke(
            cli,
            ["memory", "promotion-candidates"],
            catch_exceptions=False,
        )
        promote_result = runner.invoke(
            cli,
            ["memory", "promote-lesson", "--lesson-id", str(int(lesson["id"]))],
            catch_exceptions=False,
        )

    updated_lesson = current_pm.get_transferred_lesson(int(lesson["id"]))

    assert candidates_result.exit_code == 0
    assert "Transferred Lesson Recommendations" in candidates_result.output
    assert "promote" in candidates_result.output
    assert promote_result.exit_code == 0
    assert "Promoted" in promote_result.output
    assert updated_lesson is not None
    assert updated_lesson["validation_status"] == "promoted"
    assert int(updated_lesson["promoted_rule_id"] or 0) > 0


def test_memory_archive_lesson_command(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Retry parser errors with a strict schema", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.record_transferred_lesson_outcome(str(lesson["lesson_key"]), success=False)
    current_pm.record_transferred_lesson_outcome(str(lesson["lesson_key"]), success=False)

    conn = current_pm._get_connection()
    try:
        conn.execute(
            "UPDATE transferred_lessons SET updated_at = ? WHERE id = ?",
            ("2026-03-01T00:00:00", int(lesson["id"])),
        )
        conn.commit()
    finally:
        conn.close()

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        result = runner.invoke(
            cli,
            [
                "memory",
                "archive-lesson",
                "--lesson-id",
                str(int(lesson["id"])),
                "--reason",
                "Aged out after repeated failures.",
            ],
            catch_exceptions=False,
        )

    updated_lesson = current_pm.get_transferred_lesson(int(lesson["id"]))

    assert result.exit_code == 0
    assert "Archived" in result.output
    assert updated_lesson is not None
    assert updated_lesson["validation_status"] == "archived"


def test_memory_status_history_and_audit_show_transferred_lesson_provenance(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    current_pm.record_transferred_lesson_outcome(str(lesson["lesson_key"]), success=True)
    current_pm.record_manual_transferred_lesson_feedback(
        str(lesson["lesson_key"]),
        success=True,
        note="Validated before promotion.",
    )

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        status_result = runner.invoke(cli, ["memory", "status"], catch_exceptions=False)
        history_result = runner.invoke(
            cli,
            ["memory", "history", "--limit", "5"],
            catch_exceptions=False,
        )
        audit_result = runner.invoke(
            cli,
            ["audit", "list", "--action", "transferred_lesson_validated"],
            catch_exceptions=False,
        )

    assert status_result.exit_code == 0
    assert "Transferred Lesson Snapshot" in status_result.output
    assert "source" in status_result.output
    assert history_result.exit_code == 0
    assert "Transferred Lesson Lifecycle" in history_result.output
    assert "Transferred Lesson Audit" in history_result.output
    assert "validated" in history_result.output
    assert audit_result.exit_code == 0
    assert "lesson validated" in audit_result.output
    assert "source" in audit_result.output


def test_memory_history_shows_lesson_usage_events(
    tmp_path: Path,
    isolate_system_db: Path,
) -> None:
    current = tmp_path / "current"
    current.mkdir()
    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    current_pm = ProjectMemory(str(current))
    current_pm.insert_lesson_usage_event(
        project_path=str(current.resolve()),
        session_id="review-session",
        stage="semantic_review",
        lesson_source="model_pack",
        lesson_key="pack-json-retries",
        canonical_model_key="minimax/m2.7@1",
        outcome="positive_fix_verification",
        metadata_json=json.dumps({"reason": "Helped recover valid schema output."}),
    )

    runner = CliRunner()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.chdir(current)
        result = runner.invoke(cli, ["memory", "history", "--limit", "5"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Lesson Usage Events" in result.output
    assert "semantic" in result.output
    assert "positive" in result.output
    assert "pack-jso" in result.output
