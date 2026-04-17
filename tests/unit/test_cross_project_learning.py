"""
Unit tests for cross-project learning, model identity, and model packs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tools.muscle.audit_presenter import format_action_log_entry
from tools.muscle.lesson_resolver import LessonRenderBudget, LessonResolver
from tools.muscle.model_identity import ModelIdentityResolver
from tools.muscle.model_pack_standard import (
    PACK_LESSONS_SCHEMA_VERSION,
    PACK_MANIFEST_SCHEMA_VERSION,
    PACK_REPO_LAYOUT_VERSION,
)
from tools.muscle.model_packs import ModelPackManager
from tools.muscle.project_fingerprint import (
    build_project_fingerprint,
    explain_relatedness,
    score_relatedness,
)
from tools.muscle.project_memory import ProjectMemory
from tools.muscle.project_memory_types import ModelPackLesson, ModelPackMetadata
from tools.muscle.system_db import SystemDatabase
from tools.muscle.transferable_lesson_scrubber import (
    TransferScrubContext,
    scrub_transferable_lesson,
)
from tools.muscle.tui.project_manager import ProjectConfig, ProjectManager


@pytest.fixture
def isolated_system_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "home" / ".muscle" / "system.db"
    monkeypatch.setattr("tools.muscle.system_db.DEFAULT_SYSTEM_DB_PATH", db_path)
    return db_path


def test_model_identity_manual_override_wins(isolated_system_db: Path) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())
    identity = resolver.resolve(
        requested_label="claude-sonnet-4",
        provider_endpoint="https://gateway.example.com/anthropic",
        manual_override="openai/gpt-5@1",
    )
    assert identity.canonical_model_key == "openai/gpt-5@1"
    assert identity.identity_source == "manual_override"
    assert identity.manual_override is True


def test_model_identity_custom_anthropic_endpoint_stays_unresolved(
    isolated_system_db: Path,
) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())
    identity = resolver.resolve(
        requested_label="claude-sonnet-4",
        provider_endpoint="https://gateway.example.com/anthropic",
    )
    assert identity.canonical_model_key is None
    assert identity.identity_source == "unresolved"


def test_model_identity_introspects_trusted_openai_response(isolated_system_db: Path) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())
    identity = resolver.introspect_response(
        requested_label="custom-openai-alias",
        provider_endpoint="https://api.openai.com/v1",
        response_payload={"model": "gpt-5-mini-2026-04-14"},
    )
    assert identity is not None
    assert identity.canonical_model_key == "openai/gpt-5-mini@1"
    assert identity.identity_source == "provider_introspection"
    assert identity.metadata["provider_owner"] == "openai"


def test_model_identity_ignores_untrusted_provider_response_spoof(isolated_system_db: Path) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())
    identity = resolver.introspect_response(
        requested_label="custom-openai-alias",
        provider_endpoint="https://gateway.example.com/v1",
        response_payload={"model": "gpt-5-mini-2026-04-14"},
    )
    assert identity is None


def test_model_identity_introspection_respects_manual_override(isolated_system_db: Path) -> None:
    resolver = ModelIdentityResolver(SystemDatabase())
    identity = resolver.introspect_response(
        requested_label="gpt-5",
        provider_endpoint="https://api.openai.com/v1",
        response_payload={"model": "gpt-5-mini-2026-04-14"},
        manual_override=True,
    )
    assert identity is None


def test_project_fingerprint_relatedness_prefers_overlap(tmp_path: Path) -> None:
    current = tmp_path / "current"
    related = tmp_path / "related"
    unrelated = tmp_path / "unrelated"
    current.mkdir()
    related.mkdir()
    unrelated.mkdir()

    (current / "pyproject.toml").write_text(
        "[project]\nname='current'\ndependencies=['fastapi', 'pydantic']\n",
        encoding="utf-8",
    )
    (current / "tests").mkdir()

    (related / "pyproject.toml").write_text(
        "[project]\nname='related'\ndependencies=['fastapi', 'sqlalchemy']\n",
        encoding="utf-8",
    )
    (related / "tests").mkdir()

    (unrelated / "package.json").write_text(
        json.dumps({"name": "frontend", "dependencies": {"react": "^19.0.0"}}),
        encoding="utf-8",
    )
    (unrelated / "src").mkdir()

    current_fp = build_project_fingerprint(current, languages=["Python"])
    related_fp = build_project_fingerprint(related, languages=["Python"])
    unrelated_fp = build_project_fingerprint(unrelated, languages=["JavaScript"])

    assert score_relatedness(current_fp, related_fp) > score_relatedness(current_fp, unrelated_fp)


def test_project_fingerprint_detects_common_framework_configs(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "dependencies": {"react": "^19.0.0", "next": "^16.0.0"},
                "devDependencies": {"tailwindcss": "^4.0.0"},
                "peerDependencies": {"vitest": "^2.0.0"},
            }
        ),
        encoding="utf-8",
    )
    (web / "next.config.mjs").write_text("export default {}", encoding="utf-8")
    (web / "tsconfig.json").write_text("{}", encoding="utf-8")
    (web / "packages").mkdir()

    fingerprint = build_project_fingerprint(web)

    assert "TypeScript" in fingerprint.languages
    assert {"Next.js", "Tailwind", "Vitest"} <= set(fingerprint.frameworks)
    assert "monorepo" in fingerprint.archetypes


def test_relatedness_explanation_surfaces_overlap_reasons(tmp_path: Path) -> None:
    current = tmp_path / "current"
    related = tmp_path / "related"
    current.mkdir()
    related.mkdir()
    (current / "pyproject.toml").write_text(
        "[project]\nname='current'\ndependencies=['fastapi', 'pydantic']\n",
        encoding="utf-8",
    )
    (current / "tests").mkdir()
    (related / "pyproject.toml").write_text(
        "[project]\nname='related'\ndependencies=['fastapi', 'sqlalchemy']\n",
        encoding="utf-8",
    )
    (related / "tests").mkdir()

    explanation = explain_relatedness(
        build_project_fingerprint(current, languages=["Python"]),
        build_project_fingerprint(related, languages=["Python"]),
    )

    assert explanation["score"] > 0.0
    assert "languages: Python" in explanation["summary"]
    assert "deps: fastapi" in explanation["summary"]
    assert explanation["overlap"]["dependencies"] == ["fastapi"]


def test_transfer_scrubber_is_deterministic_and_preserves_portable_lessons() -> None:
    context = TransferScrubContext(
        project_path="/tmp/project",
        project_name="example-project",
        repo_name="example-project",
    )
    text = "Prefer schema-first retries when parsing model JSON."
    first = scrub_transferable_lesson(text, context)
    second = scrub_transferable_lesson(text, context)

    assert first == second
    assert first.accepted is True
    assert first.normalized_text == text
    assert first.reason_codes == ()


def test_lesson_resolver_keeps_local_precedence_and_records_usage(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()

    manager = ProjectManager(current)
    source_manager = ProjectManager(source)
    manager.init_project(ProjectConfig(name="current", path=current, languages=["Python"]))
    source_manager.init_project(ProjectConfig(name="source", path=source, languages=["Python"]))

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    current_pm.insert_learned_rule(
        str(current), "Prefer explicit validation before writes", "validate"
    )
    source_pm.insert_learned_rule(str(source), "Related project lesson", "auth")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.9
    )

    system_db = SystemDatabase()
    system_db.upsert_model_pack(
        metadata=ModelPackMetadata(
            canonical_model_key="minimax/m2.7@1",
            version="0.1.0",
            install_status="installed",
        ),
        lessons=[
            ModelPackLesson(
                canonical_model_key="minimax/m2.7@1",
                lesson_key="pack-1",
                lesson_text="MiniMax prefers concise, schema-faithful outputs.",
                scope_tags=["python"],
                safety_scope="review-only",
                portability="portable",
            )
        ],
    )

    config = ProjectConfig(
        name="current",
        path=current,
        languages=["Python"],
        model_pack_mode="auto",
        model_manual_override="minimax/m2.7@1",
    )
    resolver = LessonResolver(
        project_path=str(current),
        project_memory=current_pm,
        system_db=system_db,
        project_config=config,
        requested_model_label="MiniMax-M2.7",
        provider_endpoint="https://api.minimax.io/anthropic",
    )

    result = resolver.resolve_for_prompt(
        query_text="validate auth bug",
        stage="semantic_review",
        session_id="sess-1",
        language="Python",
    )

    assert result.lessons
    assert result.lessons[0].source == "local"
    assert any(lesson.source == "related" for lesson in result.lessons)
    assert any(lesson.source == "model-pack" for lesson in result.lessons)
    usage_events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="sess-1"
    )
    assert len(usage_events) >= 3


def test_lesson_resolver_applies_explicit_render_budget_to_prompt_and_usage(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source"
    current.mkdir()
    source.mkdir()

    manager = ProjectManager(current)
    source_manager = ProjectManager(source)
    manager.init_project(ProjectConfig(name="current", path=current, languages=["Python"]))
    source_manager.init_project(ProjectConfig(name="source", path=source, languages=["Python"]))

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    current_pm.insert_learned_rule(str(current), "Validate inputs first", "validate")
    source_pm.insert_learned_rule(str(source), "Reuse schema-first parsing", "validate")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.9
    )

    system_db = SystemDatabase()
    system_db.upsert_model_pack(
        metadata=ModelPackMetadata(
            canonical_model_key="minimax/m2.7@1",
            version="0.1.0",
            install_status="installed",
        ),
        lessons=[
            ModelPackLesson(
                canonical_model_key="minimax/m2.7@1",
                lesson_key="pack-1",
                lesson_text="Keep JSON outputs schema-faithful.",
                scope_tags=["python"],
                safety_scope="review-only",
                portability="portable",
            )
        ],
    )

    resolver = LessonResolver(
        project_path=str(current),
        project_memory=current_pm,
        system_db=system_db,
        project_config=ProjectConfig(
            name="current",
            path=current,
            languages=["Python"],
            model_pack_mode="auto",
            model_manual_override="minimax/m2.7@1",
        ),
        requested_model_label="MiniMax-M2.7",
        provider_endpoint="https://api.minimax.io/anthropic",
    )

    result = resolver.resolve_for_prompt(
        query_text="validate JSON writes",
        stage="semantic_review",
        session_id="sess-budget",
        language="Python",
        render_budget=LessonRenderBudget(
            name="tiny-review-budget",
            max_total_tokens=40,
            source_token_limits={"local": 30, "related": 1, "model-pack": 1, "global": 1},
        ),
    )

    assert result.lessons
    assert all(lesson.source == "local" for lesson in result.lessons)
    assert result.render_budget_name == "tiny-review-budget"
    usage_events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="sess-budget"
    )
    assert len(usage_events) == len(result.lessons)


def test_related_project_import_rejects_nonportable_lessons_and_logs_reasons(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    current = tmp_path / "current"
    source = tmp_path / "source-project"
    current.mkdir()
    source.mkdir()

    ProjectManager(current).init_project(
        ProjectConfig(name="current", path=current, languages=["Python"])
    )
    ProjectManager(source).init_project(
        ProjectConfig(name="source-project", path=source, languages=["Python"])
    )

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Use schema-first retries for JSON parsing", "json")
    source_pm.insert_learned_rule(
        str(source),
        f"Never read from /Users/test/{source.name}/secret.txt in {source.name}",
        "secret",
    )
    source_pm.insert_learned_rule(
        str(source),
        "Keep api_key values out of prompts",
        "secret",
    )

    result = current_pm.import_project_lessons(
        str(current),
        str(source),
        link_mode="snapshot",
        relatedness_score=0.8,
    )

    transferred = current_pm.list_transferred_lessons(project_path=str(current))
    assert result["imported"] == 1
    assert result["rejected"] == 2
    assert len(transferred) == 1

    metadata = json.loads(transferred[0]["metadata_json"])
    assert metadata["scrubber"]["accepted"] is True
    assert metadata["scrubber"]["reason_codes"] == []

    action_logs = current_pm.list_action_logs(
        project_path=str(current),
        action_type="related_import_scrub",
    )
    assert action_logs
    details = json.loads(action_logs[0]["details_json"])
    assert details["rejected"]
    reason_sets = [set(item["reason_codes"]) for item in details["rejected"]]
    assert any({"absolute_path", "project_identifier"} <= reason_set for reason_set in reason_sets)
    assert any("secret_like_content" in reason_set for reason_set in reason_sets)


def test_system_db_prunes_stale_and_missing_registered_projects(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    keep = tmp_path / "keep"
    stale = tmp_path / "stale"
    missing = tmp_path / "missing"
    keep.mkdir()
    stale.mkdir()
    missing.mkdir()

    system_db = SystemDatabase()
    system_db.register_project(build_project_fingerprint(keep, languages=["Python"]))
    system_db.register_project(build_project_fingerprint(stale, languages=["Python"]))
    system_db.register_project(build_project_fingerprint(missing, languages=["Python"]))

    conn = system_db._get_connection()
    try:
        conn.execute(
            "UPDATE registered_projects SET last_seen = ? WHERE project_path = ?",
            ((datetime.now() - timedelta(days=120)).isoformat(), str(stale.resolve())),
        )
        conn.commit()
    finally:
        conn.close()
    missing.rmdir()

    pruned = system_db.prune_registered_projects(stale_after_days=90, keep_paths=[str(keep)])
    remaining = system_db.list_registered_projects()

    assert pruned["removed"] == 2
    assert pruned["missing_removed"] == 1
    assert pruned["stale_removed"] == 1
    assert len(remaining) == 1
    assert remaining[0]["project_path"] == str(keep.resolve())


def test_model_pack_export_and_install_scrubs_project_specific_content(
    tmp_path: Path,
    isolated_system_db: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ProjectManager(project).init_project(
        ProjectConfig(name="project", path=project, languages=["Python"])
    )
    pm = ProjectMemory(str(project))
    keep_rule = pm.insert_learned_rule(
        str(project), "Use structured JSON retries for parser recovery", "json"
    )
    skip_rule = pm.insert_learned_rule(
        str(project),
        f"Never hardcode paths like {project}/secret.txt",
        "path",
    )

    manager = ModelPackManager(str(project))
    with caplog.at_level("INFO", logger="tools.muscle.model_packs"):
        result = manager.export_candidate_bundle(
            canonical_model_key="minimax/m2.7@1",
            output_dir=str(tmp_path / "exports"),
            rule_ids=[keep_rule, skip_rule],
        )
        metadata = manager.install_bundle(result.bundle_dir)

    assert result.lesson_count == 1
    assert skip_rule in result.skipped_rule_ids
    assert result.rejected_lessons
    assert {"absolute_path", "project_identifier"} <= set(
        result.rejected_lessons[0]["reason_codes"]
    )
    manifest = json.loads((result.bundle_dir / "pack.json").read_text(encoding="utf-8"))
    lessons_payload = json.loads((result.bundle_dir / "lessons.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == PACK_MANIFEST_SCHEMA_VERSION
    assert manifest["repository_layout_version"] == PACK_REPO_LAYOUT_VERSION
    assert manifest["lessons_schema_version"] == PACK_LESSONS_SCHEMA_VERSION
    assert manifest["repository_path"] == "packs/minimax/m2.7@1"
    assert lessons_payload["schema_version"] == PACK_LESSONS_SCHEMA_VERSION
    assert lessons_payload["canonical_model_key"] == "minimax/m2.7@1"
    assert lessons_payload["lesson_count"] == 1
    assert len(lessons_payload["lessons"]) == 1

    assert metadata.canonical_model_key == "minimax/m2.7@1"
    packs = SystemDatabase().list_model_packs()
    assert any(pack["canonical_model_key"] == "minimax/m2.7@1" for pack in packs)
    action_logs = pm.list_action_logs(
        project_path=str(project),
        action_type="model_pack_export_scrub",
    )
    assert action_logs
    formatted = format_action_log_entry(action_logs[0])
    assert formatted["action"] == "model pack exported"
    assert "minimax/m2.7@1" in formatted["details"]
    assert "exported 1 lessons" in formatted["details"]
    assert "Exported model pack candidate" in caplog.text
    assert "Installed model pack" in caplog.text


def test_model_pack_install_rejects_incompatible_canonical_model(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ProjectManager(project).init_project(
        ProjectConfig(name="project", path=project, languages=["Python"])
    )
    pm = ProjectMemory(str(project))
    pm.insert_learned_rule(str(project), "Use structured JSON retries for parser recovery", "json")

    manager = ModelPackManager(str(project))
    result = manager.export_candidate_bundle(
        canonical_model_key="minimax/m2.7@1",
        output_dir=str(tmp_path / "exports"),
    )

    with pytest.raises(ValueError, match="incompatible with current model family"):
        manager.install_bundle(
            result.bundle_dir,
            expected_canonical_model_key="openai/gpt-5@1",
        )


def test_model_pack_install_rejects_lessons_without_scope_tags(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "pack.json").write_text(
        json.dumps(
            {
                "canonical_model_key": "minimax/m2.7@1",
                "version": "0.1.0",
                "supported_aliases": [],
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "lessons.json").write_text(
        json.dumps(
            [
                {
                    "canonical_model_key": "minimax/m2.7@1",
                    "lesson_key": "bad-lesson",
                    "lesson_text": "Do the safe thing.",
                    "scope_tags": [],
                    "safety_scope": "review-only",
                    "portability": "portable",
                    "evidence": {},
                }
            ]
        ),
        encoding="utf-8",
    )

    manager = ModelPackManager(str(tmp_path))

    with pytest.raises(ValueError, match="scope tag"):
        manager.install_bundle(bundle_dir)


def test_model_pack_install_rejects_manifest_with_wrong_repository_path(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "pack.json").write_text(
        json.dumps(
            {
                "schema_version": PACK_MANIFEST_SCHEMA_VERSION,
                "repository_layout_version": PACK_REPO_LAYOUT_VERSION,
                "repository_path": "packs/openai/gpt-5@1",
                "canonical_model_key": "minimax/m2.7@1",
                "lessons_schema_version": PACK_LESSONS_SCHEMA_VERSION,
                "version": "0.1.0",
                "supported_aliases": [],
            }
        ),
        encoding="utf-8",
    )
    (bundle_dir / "lessons.json").write_text(
        json.dumps(
            {
                "schema_version": PACK_LESSONS_SCHEMA_VERSION,
                "canonical_model_key": "minimax/m2.7@1",
                "lesson_count": 1,
                "lessons": [
                    {
                        "canonical_model_key": "minimax/m2.7@1",
                        "lesson_key": "portable-lesson",
                        "lesson_text": "Do the safe thing.",
                        "scope_tags": ["python"],
                        "safety_scope": "review-only",
                        "portability": "portable",
                        "evidence": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = ModelPackManager(str(tmp_path))

    with pytest.raises(ValueError, match="repository_path"):
        manager.install_bundle(bundle_dir)


def test_system_db_rejects_model_pack_lessons_with_invalid_portability(
    isolated_system_db: Path,
) -> None:
    system_db = SystemDatabase()

    with pytest.raises(ValueError, match="Unsupported model-pack portability"):
        system_db.upsert_model_pack(
            metadata=ModelPackMetadata(
                canonical_model_key="minimax/m2.7@1",
                version="0.1.0",
                install_status="installed",
            ),
            lessons=[
                ModelPackLesson(
                    canonical_model_key="minimax/m2.7@1",
                    lesson_key="bad-portability",
                    lesson_text="Unsafe portability metadata.",
                    scope_tags=["python"],
                    safety_scope="review-only",
                    portability="project-local",
                    evidence={},
                )
            ],
        )


def test_review_only_model_pack_lessons_do_not_apply_during_generate(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ProjectManager(project).init_project(
        ProjectConfig(
            name="project",
            path=project,
            languages=["Python"],
            model_pack_mode="auto",
            model_manual_override="minimax/m2.7@1",
        )
    )
    pm = ProjectMemory(str(project))
    system_db = SystemDatabase()
    system_db.upsert_model_pack(
        metadata=ModelPackMetadata(
            canonical_model_key="minimax/m2.7@1",
            version="0.1.0",
            install_status="installed",
        ),
        lessons=[
            ModelPackLesson(
                canonical_model_key="minimax/m2.7@1",
                lesson_key="review-only-pack",
                lesson_text="Only use this during semantic review.",
                scope_tags=["python"],
                safety_scope="review-only",
                portability="portable",
                evidence={},
            )
        ],
    )
    resolver = LessonResolver(
        project_path=str(project),
        project_memory=pm,
        system_db=system_db,
        project_config=ProjectConfig(
            name="project",
            path=project,
            languages=["Python"],
            model_pack_mode="auto",
            model_manual_override="minimax/m2.7@1",
        ),
        requested_model_label="MiniMax-M2.7",
        provider_endpoint="https://api.minimax.io/anthropic",
    )

    result = resolver.resolve_for_prompt(
        query_text="generate a parser",
        stage="generate",
        session_id="sess-generate",
        language="Python",
    )

    assert not any(lesson.source == "model-pack" for lesson in result.lessons)


def test_positive_transferred_lesson_outcome_updates_validation_history(
    tmp_path: Path,
    isolated_system_db: Path,
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
    (current / "CLAUDE.md").write_text("# Current Project\n", encoding="utf-8")

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    current_pm.insert_lesson_usage_event(
        project_path=str(current),
        session_id="sess-outcome",
        stage="generate",
        lesson_source="related",
        lesson_key=str(lesson["lesson_key"]),
        source_project_path=str(source),
    )
    result = current_pm.apply_transferred_lesson_outcomes(
        project_path=str(current),
        session_id="sess-outcome",
        stages=["generate"],
        outcome="positive_generation_iteration",
        success=True,
    )

    updated_events = current_pm.list_lesson_usage_events(
        project_path=str(current),
        session_id="sess-outcome",
    )
    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    assert result == {"events_updated": 1, "lessons_updated": 1}
    assert updated_events[0]["outcome"] == "positive_generation_iteration"
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 1
    assert updated_lesson["validation_status"] == "provisional"


def test_negative_transferred_lesson_outcome_does_not_validate_lesson(
    tmp_path: Path,
    isolated_system_db: Path,
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
    (current / "CLAUDE.md").write_text("# Current Project\n", encoding="utf-8")

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    source_pm.insert_learned_rule(str(source), "Reuse schema-first retries", "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    current_pm.insert_lesson_usage_event(
        project_path=str(current),
        session_id="sess-fail",
        stage="fix_generation",
        lesson_source="related",
        lesson_key=str(lesson["lesson_key"]),
        source_project_path=str(source),
    )
    current_pm.apply_transferred_lesson_outcomes(
        project_path=str(current),
        session_id="sess-fail",
        stages=["fix_generation"],
        outcome="negative_fix_verification",
        success=False,
    )

    updated_lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]
    updated_events = current_pm.list_lesson_usage_events(
        project_path=str(current), session_id="sess-fail"
    )

    assert updated_events[0]["outcome"] == "negative_fix_verification"
    assert int(updated_lesson["validation_count"] or 0) == 1
    assert int(updated_lesson["success_count"] or 0) == 0
    assert updated_lesson["validation_status"] == "provisional"


def test_transferred_lesson_manual_confirmation_can_create_promotion_candidate(
    tmp_path: Path,
    isolated_system_db: Path,
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
    before = current_pm.get_transferred_lesson_recommendation(int(lesson["id"]))
    assert before is not None
    assert before["recommendation"] == "observe"

    current_pm.record_manual_transferred_lesson_feedback(
        str(lesson["lesson_key"]),
        success=True,
        note="Confirmed on a similar bug in this project.",
    )

    after = current_pm.get_transferred_lesson_recommendation(int(lesson["id"]))
    assert after is not None
    assert after["validation_status"] == "validated"
    assert after["promotion_candidate"] is True
    assert after["recommendation"] == "promote"
    assert after["manual_accepts"] == 1
    assert "Validated in this project" in after["status_explanation"]

    action_logs = current_pm.list_action_logs(
        project_path=str(current),
        action_type="transferred_lesson_validated",
        limit=10,
    )
    assert action_logs
    decisions = current_pm.list_decisions(
        project_path=str(current),
        decision_type="validate_transferred_lesson",
        limit=10,
    )
    assert decisions


def test_transferred_lessons_only_publish_after_promotion_into_local_rules(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    from tools.muscle.claude_publisher import ClaudePublisher

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
    (current / "CLAUDE.md").write_text("# Current Project\n", encoding="utf-8")

    current_pm = ProjectMemory(str(current))
    source_pm = ProjectMemory(str(source))
    lesson_text = "Prefer schema-first retries when parsing JSON output"
    source_pm.insert_learned_rule(str(source), lesson_text, "json")
    current_pm.import_project_lessons(
        str(current), str(source), link_mode="snapshot", relatedness_score=0.8
    )
    lesson = current_pm.list_transferred_lessons(project_path=str(current))[0]

    current_pm.record_transferred_lesson_outcome(str(lesson["lesson_key"]), success=True)
    current_pm.record_manual_transferred_lesson_feedback(
        str(lesson["lesson_key"]),
        success=True,
        note="Validated locally before promotion.",
    )

    publisher = ClaudePublisher(str(current))
    assert publisher.update_markers() is True
    content_before = (current / "CLAUDE.md").read_text(encoding="utf-8")
    assert lesson_text not in content_before

    local_rule_id = current_pm.promote_transferred_lesson(int(lesson["id"]))
    assert local_rule_id > 0

    assert publisher.update_markers() is True
    content_after = (current / "CLAUDE.md").read_text(encoding="utf-8")
    assert lesson_text in content_after

    promoted_lesson = current_pm.get_transferred_lesson(int(lesson["id"]))
    assert promoted_lesson is not None
    assert promoted_lesson["validation_status"] == "promoted"
    assert int(promoted_lesson["promoted_rule_id"] or 0) == local_rule_id

    decisions = current_pm.list_decisions(
        project_path=str(current),
        decision_type="promote_transferred_lesson",
        limit=10,
    )
    assert decisions
    action_logs = current_pm.list_action_logs(
        project_path=str(current),
        action_type="transferred_lesson_promoted",
        limit=10,
    )
    assert action_logs


def test_archived_transferred_lessons_are_removed_from_related_prompt_context(
    tmp_path: Path,
    isolated_system_db: Path,
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
            ((datetime.now() - timedelta(days=30)).isoformat(), int(lesson["id"])),
        )
        conn.commit()
    finally:
        conn.close()

    recommendation = current_pm.get_transferred_lesson_recommendation(int(lesson["id"]))
    assert recommendation is not None
    assert recommendation["archive_candidate"] is True
    assert recommendation["recommendation"] == "archive"

    assert current_pm.archive_transferred_lesson(
        int(lesson["id"]),
        reason="Aged out after repeated failures in this project.",
    )

    resolver = LessonResolver(
        project_path=str(current),
        project_memory=current_pm,
        system_db=SystemDatabase(),
        project_config=ProjectConfig(name="current", path=current, languages=["Python"]),
    )
    resolved = resolver.resolve_for_prompt(
        query_text="json parser regression",
        stage="generate",
        session_id="sess-archived",
        language="Python",
    )

    assert not any(lesson.source == "related" for lesson in resolved.lessons)
    action_logs = current_pm.list_action_logs(
        project_path=str(current),
        action_type="transferred_lesson_archived",
        limit=10,
    )
    assert action_logs


def test_unlink_related_project_records_audit_entry(
    tmp_path: Path,
    isolated_system_db: Path,
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

    assert current_pm.unlink_related_project(str(current), str(source))

    action_logs = current_pm.list_action_logs(
        project_path=str(current),
        action_type="related_project_unlinked",
        limit=10,
    )
    assert action_logs
    details = json.loads(action_logs[0]["details_json"])
    assert details["source_project_path"] == str(source)


def test_model_pack_submit_records_draft_pr(
    tmp_path: Path,
    isolated_system_db: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "submit-project"
    project.mkdir()
    ProjectManager(project).init_project(ProjectConfig(name="submit-project", path=project))
    pm = ProjectMemory(str(project))
    pm.insert_learned_rule(str(project), "Keep JSON outputs minimal and schema-first", "json")
    manager = ModelPackManager(str(project))
    export_result = manager.export_candidate_bundle(
        canonical_model_key="minimax/m2.7@1",
        output_dir=str(tmp_path / "exports"),
    )
    committed_paths: list[str] = []
    committed_payloads: dict[str, str] = {}
    pr_bodies: list[str] = []
    label_calls: list[tuple[int, list[str]]] = []

    class StubGitHubAdapter:
        def __init__(self, token: str | None = None, repo: str | None = None):
            self.token = "token"
            self.repo = repo

        def create_branch(self, branch: str, from_branch: str = "main") -> dict[str, object]:
            return {"ref": f"refs/heads/{branch}"}

        def create_commit(
            self,
            path: str,
            message: str,
            content: str,
            branch: str = "main",
        ) -> dict[str, object]:
            committed_paths.append(path)
            committed_payloads[path] = content
            return {"content": {"path": path}, "commit": {"message": message}, "branch": branch}

        def create_pull_request(
            self,
            title: str,
            body: str,
            head: str,
            base: str = "main",
            draft: bool = False,
        ) -> dict[str, object]:
            pr_bodies.append(body)
            return {
                "number": 41,
                "html_url": "https://example.com/pr/1",
                "draft": draft,
                "head": head,
            }

        def add_labels(self, issue_number: int, labels: list[str]) -> dict[str, object]:
            label_calls.append((issue_number, list(labels)))
            return {"issue_number": issue_number, "labels": labels}

    submit_manager = ModelPackManager(
        str(project),
        github_adapter_cls=StubGitHubAdapter,  # type: ignore[arg-type]
    )
    with caplog.at_level("INFO", logger="tools.muscle.model_packs"):
        result = submit_manager.submit_draft_pr(export_result.bundle_dir)
    assert result["status"] == "draft_opened"
    assert sorted(committed_paths) == [
        "packs/minimax/m2.7@1/lessons.json",
        "packs/minimax/m2.7@1/pack.json",
    ]
    submitted_manifest = json.loads(committed_payloads["packs/minimax/m2.7@1/pack.json"])
    submitted_lessons = json.loads(committed_payloads["packs/minimax/m2.7@1/lessons.json"])
    assert submitted_manifest["repository_path"] == "packs/minimax/m2.7@1"
    assert submitted_manifest["schema_version"] == PACK_MANIFEST_SCHEMA_VERSION
    assert submitted_manifest["source_project_redacted"] is True
    assert "source_project" not in submitted_manifest
    assert submitted_lessons["schema_version"] == PACK_LESSONS_SCHEMA_VERSION
    assert "packs/minimax/m2.7@1" in pr_bodies[0]
    assert "Review Checklist" in pr_bodies[0]
    assert "needs-human-review" in pr_bodies[0]
    assert label_calls == [(41, ["model-pack", "needs-human-review", "draft-submission"])]
    submission = SystemDatabase().get_submission(export_result.export_id)
    assert submission is not None
    assert submission["pr_url"] == "https://example.com/pr/1"
    submission_metadata = json.loads(str(submission["metadata_json"]))
    assert submission_metadata["submission_fingerprint"]
    assert submission_metadata["pr_number"] == 41
    assert "Submitting model pack draft PR" in caplog.text
    assert "Submitted model pack draft PR" in caplog.text


def test_model_pack_submit_is_idempotent_for_same_export(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    project = tmp_path / "submit-project"
    project.mkdir()
    ProjectManager(project).init_project(ProjectConfig(name="submit-project", path=project))
    pm = ProjectMemory(str(project))
    pm.insert_learned_rule(str(project), "Keep JSON outputs minimal and schema-first", "json")
    manager = ModelPackManager(str(project))
    export_result = manager.export_candidate_bundle(
        canonical_model_key="minimax/m2.7@1",
        output_dir=str(tmp_path / "exports"),
    )

    call_counts = {"branch": 0, "commit": 0, "pr": 0, "labels": 0}

    class StubGitHubAdapter:
        def __init__(self, token: str | None = None, repo: str | None = None):
            self.token = "token"
            self.repo = repo

        def create_branch(self, branch: str, from_branch: str = "main") -> dict[str, object]:
            call_counts["branch"] += 1
            return {"ref": f"refs/heads/{branch}"}

        def create_commit(
            self,
            path: str,
            message: str,
            content: str,
            branch: str = "main",
        ) -> dict[str, object]:
            call_counts["commit"] += 1
            return {"content": {"path": path}, "commit": {"message": message}, "branch": branch}

        def create_pull_request(
            self,
            title: str,
            body: str,
            head: str,
            base: str = "main",
            draft: bool = False,
        ) -> dict[str, object]:
            call_counts["pr"] += 1
            return {
                "number": 42,
                "html_url": "https://example.com/pr/42",
                "draft": draft,
                "head": head,
            }

        def add_labels(self, issue_number: int, labels: list[str]) -> dict[str, object]:
            call_counts["labels"] += 1
            return {"issue_number": issue_number, "labels": labels}

    submit_manager = ModelPackManager(
        str(project),
        github_adapter_cls=StubGitHubAdapter,  # type: ignore[arg-type]
    )
    first = submit_manager.submit_draft_pr(export_result.bundle_dir)
    second = submit_manager.submit_draft_pr(export_result.bundle_dir)

    assert first["status"] == "draft_opened"
    assert second["status"] == "draft_opened"
    assert second["pr_url"] == "https://example.com/pr/42"
    assert call_counts == {"branch": 1, "commit": 2, "pr": 1, "labels": 1}


def test_model_pack_submit_reuses_existing_submission_for_duplicate_content(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    project = tmp_path / "submit-project"
    project.mkdir()
    ProjectManager(project).init_project(ProjectConfig(name="submit-project", path=project))
    pm = ProjectMemory(str(project))
    pm.insert_learned_rule(str(project), "Keep JSON outputs minimal and schema-first", "json")
    manager = ModelPackManager(str(project))
    first_export = manager.export_candidate_bundle(
        canonical_model_key="minimax/m2.7@1",
        output_dir=str(tmp_path / "exports"),
    )
    second_export = manager.export_candidate_bundle(
        canonical_model_key="minimax/m2.7@1",
        output_dir=str(tmp_path / "exports"),
    )

    call_counts = {"branch": 0, "commit": 0, "pr": 0, "labels": 0}

    class StubGitHubAdapter:
        def __init__(self, token: str | None = None, repo: str | None = None):
            self.token = "token"
            self.repo = repo

        def create_branch(self, branch: str, from_branch: str = "main") -> dict[str, object]:
            call_counts["branch"] += 1
            return {"ref": f"refs/heads/{branch}"}

        def create_commit(
            self,
            path: str,
            message: str,
            content: str,
            branch: str = "main",
        ) -> dict[str, object]:
            call_counts["commit"] += 1
            return {"content": {"path": path}, "commit": {"message": message}, "branch": branch}

        def create_pull_request(
            self,
            title: str,
            body: str,
            head: str,
            base: str = "main",
            draft: bool = False,
        ) -> dict[str, object]:
            call_counts["pr"] += 1
            return {
                "number": 43,
                "html_url": "https://example.com/pr/43",
                "draft": draft,
                "head": head,
            }

        def add_labels(self, issue_number: int, labels: list[str]) -> dict[str, object]:
            call_counts["labels"] += 1
            return {"issue_number": issue_number, "labels": labels}

    submit_manager = ModelPackManager(
        str(project),
        github_adapter_cls=StubGitHubAdapter,  # type: ignore[arg-type]
    )
    first = submit_manager.submit_draft_pr(first_export.bundle_dir)
    duplicate = submit_manager.submit_draft_pr(second_export.bundle_dir)

    assert first["status"] == "draft_opened"
    assert duplicate["status"] == "duplicate_existing"
    assert duplicate["pr_url"] == "https://example.com/pr/43"
    assert duplicate["duplicate_of_export_id"] == first_export.export_id
    assert call_counts == {"branch": 1, "commit": 2, "pr": 1, "labels": 1}
    assert SystemDatabase().get_submission(second_export.export_id) is None


def test_model_pack_repository_scaffold_writes_standard_files(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    project = tmp_path / "repo-project"
    project.mkdir()
    ProjectManager(project).init_project(ProjectConfig(name="repo-project", path=project))

    manager = ModelPackManager(str(project))
    scaffold_root = tmp_path / "model-pack-repo"
    result = manager.scaffold_repository_standard(scaffold_root)

    assert result.root_dir == scaffold_root
    expected_files = {
        scaffold_root / "README.md",
        scaffold_root / "CONTRIBUTING.md",
        scaffold_root / "docs" / "moderation.md",
        scaffold_root / "pack-repository.json",
        scaffold_root / "packs" / "README.md",
        scaffold_root / "schemas" / "pack.schema.json",
        scaffold_root / "schemas" / "lessons.schema.json",
    }
    assert expected_files.issubset(set(result.files_written))
    descriptor = json.loads((scaffold_root / "pack-repository.json").read_text(encoding="utf-8"))
    assert descriptor["repository_layout_version"] == PACK_REPO_LAYOUT_VERSION
    assert descriptor["pack_manifest_schema_version"] == PACK_MANIFEST_SCHEMA_VERSION
    assert descriptor["lessons_schema_version"] == PACK_LESSONS_SCHEMA_VERSION


def test_remote_model_pack_install_populates_local_cache_and_storage(
    tmp_path: Path,
    isolated_system_db: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "remote-project"
    project.mkdir()
    ProjectManager(project).init_project(
        ProjectConfig(
            name="remote-project",
            path=project,
            languages=["Python"],
            canonical_model_key="minimax/m2.7@1",
            model_manual_override="minimax/m2.7@1",
            model_pack_mode="auto",
        )
    )
    cache_root = tmp_path / "cache-root"

    class StubGitHubAdapter:
        def __init__(self, token: str | None = None, repo: str | None = None):
            self.token = token
            self.repo = repo

        def get_file_content(self, path: str, ref: str = "main") -> str | None:
            payloads = {
                "packs/minimax/m2.7@1/pack.json": json.dumps(
                    {
                        "schema_version": PACK_MANIFEST_SCHEMA_VERSION,
                        "repository_layout_version": PACK_REPO_LAYOUT_VERSION,
                        "repository_path": "packs/minimax/m2.7@1",
                        "canonical_model_key": "minimax/m2.7@1",
                        "lessons_schema_version": PACK_LESSONS_SCHEMA_VERSION,
                        "version": "1.2.3",
                        "supported_aliases": ["MiniMax-M2.7"],
                    }
                ),
                "packs/minimax/m2.7@1/lessons.json": json.dumps(
                    {
                        "schema_version": PACK_LESSONS_SCHEMA_VERSION,
                        "canonical_model_key": "minimax/m2.7@1",
                        "lesson_count": 1,
                        "lessons": [
                            {
                                "canonical_model_key": "minimax/m2.7@1",
                                "lesson_key": "remote-lesson",
                                "lesson_text": "Prefer schema-safe retries for parser output.",
                                "scope_tags": ["python"],
                                "safety_scope": "review-only",
                                "portability": "portable",
                                "evidence": {"origin": "remote-pack"},
                            }
                        ],
                    }
                ),
            }
            return payloads.get(path)

        def get_branch_sha(self, branch: str) -> str | None:
            return "abcdef1234567890"

    manager = ModelPackManager(
        str(project),
        github_adapter_cls=StubGitHubAdapter,  # type: ignore[arg-type]
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("tools.muscle.model_packs.REMOTE_CACHE_DIR", cache_root)
        with caplog.at_level("INFO", logger="tools.muscle.model_packs"):
            metadata = manager.install_remote_bundle(
                "minimax/m2.7@1",
                repo="LivingEthos/muscle-model-packs",
                ref="main",
                expected_canonical_model_key="minimax/m2.7@1",
            )

    assert metadata.canonical_model_key == "minimax/m2.7@1"
    assert metadata.version == "1.2.3"
    assert metadata.source_repo == "LivingEthos/muscle-model-packs"
    assert metadata.source_repo_commit == "abcdef1234567890"
    assert metadata.pack_path is not None
    cached_dir = Path(metadata.pack_path)
    assert cached_dir.exists()
    assert cached_dir.is_dir()
    assert cached_dir.parent.parent.parent == cache_root / "LivingEthos__muscle-model-packs"
    installed = SystemDatabase().list_model_packs()
    assert installed[0]["canonical_model_key"] == "minimax/m2.7@1"
    stored_manifest = json.loads((cached_dir / "pack.json").read_text(encoding="utf-8"))
    assert stored_manifest["source_repo"] == "LivingEthos/muscle-model-packs"
    assert stored_manifest["source_ref"] == "main"
    assert "Fetching remote model pack" in caplog.text
    assert "Fetched remote model pack into cache" in caplog.text
    assert "Installing remote model pack" in caplog.text


def test_remote_model_pack_update_is_idempotent_when_version_matches(
    tmp_path: Path,
    isolated_system_db: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project = tmp_path / "remote-project"
    project.mkdir()
    ProjectManager(project).init_project(
        ProjectConfig(
            name="remote-project",
            path=project,
            languages=["Python"],
            canonical_model_key="minimax/m2.7@1",
            model_manual_override="minimax/m2.7@1",
            model_pack_mode="auto",
        )
    )
    cache_root = tmp_path / "cache-root"
    fetch_count = {"pack": 0, "lessons": 0}

    class StubGitHubAdapter:
        def __init__(self, token: str | None = None, repo: str | None = None):
            self.token = token
            self.repo = repo

        def get_file_content(self, path: str, ref: str = "main") -> str | None:
            if path.endswith("pack.json"):
                fetch_count["pack"] += 1
                return json.dumps(
                    {
                        "schema_version": PACK_MANIFEST_SCHEMA_VERSION,
                        "repository_layout_version": PACK_REPO_LAYOUT_VERSION,
                        "repository_path": "packs/minimax/m2.7@1",
                        "canonical_model_key": "minimax/m2.7@1",
                        "lessons_schema_version": PACK_LESSONS_SCHEMA_VERSION,
                        "version": "1.2.3",
                        "supported_aliases": [],
                    }
                )
            if path.endswith("lessons.json"):
                fetch_count["lessons"] += 1
                return json.dumps(
                    {
                        "schema_version": PACK_LESSONS_SCHEMA_VERSION,
                        "canonical_model_key": "minimax/m2.7@1",
                        "lesson_count": 1,
                        "lessons": [
                            {
                                "canonical_model_key": "minimax/m2.7@1",
                                "lesson_key": "remote-lesson",
                                "lesson_text": "Prefer schema-safe retries for parser output.",
                                "scope_tags": ["python"],
                                "safety_scope": "review-only",
                                "portability": "portable",
                                "evidence": {"origin": "remote-pack"},
                            }
                        ],
                    }
                )
            return None

        def get_branch_sha(self, branch: str) -> str | None:
            return "abcdef1234567890"

    manager = ModelPackManager(
        str(project),
        github_adapter_cls=StubGitHubAdapter,  # type: ignore[arg-type]
    )
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("tools.muscle.model_packs.REMOTE_CACHE_DIR", cache_root)
        first = manager.install_remote_bundle(
            "minimax/m2.7@1",
            repo="LivingEthos/muscle-model-packs",
            ref="main",
            expected_canonical_model_key="minimax/m2.7@1",
        )
        with caplog.at_level("INFO", logger="tools.muscle.model_packs"):
            second = manager.update_bundle("minimax/m2.7@1")

    assert first.version == second.version == "1.2.3"
    assert first.pack_path == second.pack_path
    assert fetch_count["pack"] == 2
    assert fetch_count["lessons"] == 2
    installed = SystemDatabase().list_model_packs()
    assert installed[0]["pack_path"] == first.pack_path
    assert "Updating model pack" in caplog.text
    assert "Updating model pack from remote source" in caplog.text


def test_lesson_resolver_uses_remote_installed_pack_without_fetch(
    tmp_path: Path,
    isolated_system_db: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ProjectManager(project).init_project(
        ProjectConfig(
            name="project",
            path=project,
            languages=["Python"],
            model_pack_mode="auto",
            model_manual_override="minimax/m2.7@1",
        )
    )
    pm = ProjectMemory(str(project))
    system_db = SystemDatabase()
    system_db.upsert_model_pack(
        metadata=ModelPackMetadata(
            canonical_model_key="minimax/m2.7@1",
            version="1.2.3",
            install_status="installed",
            source_repo="LivingEthos/muscle-model-packs",
            source_repo_commit="abcdef1234567890",
            pack_path=str(tmp_path / "cache-pack"),
            metadata={"source_ref": "main"},
        ),
        lessons=[
            ModelPackLesson(
                canonical_model_key="minimax/m2.7@1",
                lesson_key="remote-lesson",
                lesson_text="Only use this during semantic review.",
                scope_tags=["python"],
                safety_scope="review-only",
                portability="portable",
                evidence={"origin": "remote-pack"},
            )
        ],
    )

    class FailingGitHubAdapter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("Remote fetch should not be reachable from prompt resolution")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("tools.muscle.model_packs.GitHubAdapter", FailingGitHubAdapter)
        resolver = LessonResolver(
            project_path=str(project),
            project_memory=pm,
            system_db=system_db,
            project_config=ProjectConfig(
                name="project",
                path=project,
                languages=["Python"],
                model_pack_mode="auto",
                model_manual_override="minimax/m2.7@1",
            ),
            requested_model_label="MiniMax-M2.7",
            provider_endpoint="https://api.minimax.io/anthropic",
        )
        result = resolver.resolve_for_prompt(
            query_text="review parser code",
            stage="semantic_review",
            session_id="sess-remote-offline",
            language="Python",
        )

    assert any(
        lesson.source == "model-pack" and lesson.lesson_key == "remote-lesson"
        for lesson in result.lessons
    )
