"""
Model-pack export, install, and draft PR submission helpers.

Architecture Decision Record (ADR):
- Keep normal review/runtime paths offline and local
- Make export deterministic so candidate bundles are reviewable
- Require explicit submission for community sharing
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapters.github import GitHubAdapter
from .model_pack_standard import (
    PACK_LESSONS_SCHEMA_VERSION,
    PACK_MANIFEST_SCHEMA_VERSION,
    PACK_REPO_LAYOUT_VERSION,
    build_lessons_payload,
    canonical_model_repository_path,
    repository_relative_paths,
    repository_scaffold_files,
)
from .model_pack_validation import (
    lesson_from_bundle_item,
    normalize_model_pack_lessons_payload,
    validate_model_pack_lesson,
    validate_model_pack_manifest,
    validate_model_pack_metadata,
)
from .project_fingerprint import build_project_fingerprint
from .project_memory import ProjectMemory
from .project_memory_types import ModelPackLesson, ModelPackMetadata, PackSubmissionRecord
from .system_db import SystemDatabase
from .transferable_lesson_scrubber import (
    SCRUBBER_VERSION,
    build_transfer_scrub_context,
    scrub_transferable_lesson,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PACK_REPO = "LivingEthos/muscle-model-packs"
DEFAULT_MODEL_PACK_REF = "main"
EXPORT_DIR = ".muscle/model-pack-exports"
REMOTE_CACHE_DIR = Path("~/.muscle/model-pack-cache").expanduser()
MODERATION_LABELS = ("model-pack", "needs-human-review", "draft-submission")
MAX_PR_BODY_LESSON_KEYS = 8


@dataclass
class ExportResult:
    export_id: str
    canonical_model_key: str
    bundle_dir: Path
    lesson_count: int
    skipped_rule_ids: list[int]
    rejected_lessons: list[dict[str, Any]]


@dataclass
class RepositoryScaffoldResult:
    root_dir: Path
    files_written: list[Path]


@dataclass
class RemoteBundleResult:
    repo: str
    ref: str
    commit: str | None
    bundle_dir: Path
    manifest: dict[str, Any]
    lessons_payload: dict[str, Any]


class ModelPackManager:
    """Manage model-pack bundles and community submission flow."""

    def __init__(
        self,
        project_path: str,
        project_memory: ProjectMemory | None = None,
        system_db: SystemDatabase | None = None,
        github_adapter_cls: type[GitHubAdapter] = GitHubAdapter,
    ):
        self.project_path = str(Path(project_path).resolve())
        self.project_memory = project_memory or ProjectMemory(self.project_path)
        self.system_db = system_db or SystemDatabase()
        self.github_adapter_cls = github_adapter_cls

    def export_candidate_bundle(
        self,
        canonical_model_key: str,
        output_dir: str | None = None,
        rule_ids: list[int] | None = None,
        supported_aliases: list[str] | None = None,
    ) -> ExportResult:
        """Export selected project lessons into a deterministic model-pack bundle."""
        logger.info(
            "Exporting model pack candidate: canonical_model_key=%s output_dir=%s rule_ids=%s",
            canonical_model_key,
            output_dir or "",
            len(rule_ids or []),
        )
        validate_model_pack_manifest(
            {
                "canonical_model_key": canonical_model_key,
                "version": "0.0.0",
                "supported_aliases": supported_aliases or [],
            }
        )
        export_id = uuid4().hex[:12]
        base_dir = Path(output_dir or (Path(self.project_path) / EXPORT_DIR))
        bundle_dir = base_dir / canonical_model_key.replace("/", "__").replace("@", "_") / export_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        rules = self.project_memory.list_learned_rules(
            project_path=self.project_path,
            limit=500,
        )
        if rule_ids:
            selected = [row for row in rules if int(row.get("id", 0) or 0) in set(rule_ids)]
        else:
            selected = [row for row in rules if row.get("status") in {"promoted", "active"}]

        default_scope_tags = self._default_scope_tags()
        if not default_scope_tags:
            raise ValueError(
                "Model-pack export requires at least one scope tag from project languages or frameworks."
            )

        lessons: list[ModelPackLesson] = []
        skipped: list[int] = []
        rejected_lessons: list[dict[str, Any]] = []
        scrub_context = build_transfer_scrub_context(self.project_path)
        for row in selected:
            scrubbed = scrub_transferable_lesson(str(row.get("rule_text", "")), scrub_context)
            if not scrubbed.accepted:
                rule_id = int(row.get("id", 0) or 0)
                skipped.append(rule_id)
                rejected_lessons.append(
                    {
                        "source_rule_id": rule_id,
                        "content_hash": scrubbed.content_hash,
                        "reason_codes": list(scrubbed.reason_codes),
                    }
                )
                continue
            lesson = validate_model_pack_lesson(
                ModelPackLesson(
                    canonical_model_key=canonical_model_key,
                    lesson_key=f"rule-{int(row.get('id', 0) or 0)}",
                    lesson_text=scrubbed.normalized_text,
                    scope_tags=default_scope_tags,
                    safety_scope="review-only",
                    portability="portable",
                    evidence={
                        "source_project": self.project_path,
                        "learned_rule_id": int(row.get("id", 0) or 0),
                        "recurrence_count": int(row.get("recurrence_count", 0) or 0),
                        "success_rate": float(row.get("success_rate", 0.0) or 0.0),
                        "scrubber": scrubbed.metadata(),
                    },
                    rationale=f"Derived from project-local learned rule {int(row.get('id', 0) or 0)}",
                ),
                expected_canonical_model_key=canonical_model_key,
            )
            lessons.append(lesson)

        lessons.sort(key=lambda lesson: lesson.lesson_key)
        repository_path = canonical_model_repository_path(canonical_model_key)
        manifest = {
            "schema_version": PACK_MANIFEST_SCHEMA_VERSION,
            "repository_layout_version": PACK_REPO_LAYOUT_VERSION,
            "repository_path": repository_path,
            "canonical_model_key": canonical_model_key,
            "lessons_schema_version": PACK_LESSONS_SCHEMA_VERSION,
            "version": f"0.1.{datetime.now().strftime('%Y%m%d')}",
            "generated_at": datetime.now().isoformat(),
            "export_id": export_id,
            "source_project": self.project_path,
            "supported_aliases": sorted(set(supported_aliases or [])),
            "lesson_count": len(lessons),
            "rejected_lesson_count": len(rejected_lessons),
            "scrubber_version": SCRUBBER_VERSION,
        }
        (bundle_dir / "pack.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        lessons_payload = build_lessons_payload(
            canonical_model_key,
            [self._lesson_to_dict(lesson) for lesson in lessons],
        )
        (bundle_dir / "lessons.json").write_text(
            json.dumps(lessons_payload, indent=2, sort_keys=True)
        )
        self.project_memory.insert_action_log(
            project_path=self.project_path,
            action_type="model_pack_export_scrub",
            entity_type="model_pack_export",
            details_json=json.dumps(
                {
                    "export_id": export_id,
                    "canonical_model_key": canonical_model_key,
                    "lesson_count": len(lessons),
                    "rejected": rejected_lessons,
                    "scrubber_version": SCRUBBER_VERSION,
                },
                sort_keys=True,
            ),
        )
        logger.info(
            "Exported model pack candidate: canonical_model_key=%s export_id=%s lesson_count=%s rejected_count=%s bundle_dir=%s",
            canonical_model_key,
            export_id,
            len(lessons),
            len(rejected_lessons),
            bundle_dir,
        )
        return ExportResult(
            export_id=export_id,
            canonical_model_key=canonical_model_key,
            bundle_dir=bundle_dir,
            lesson_count=len(lessons),
            skipped_rule_ids=skipped,
            rejected_lessons=rejected_lessons,
        )

    def install_bundle(
        self,
        bundle_path: str | Path,
        expected_canonical_model_key: str | None = None,
    ) -> ModelPackMetadata:
        """Install or refresh a model pack from a local bundle directory."""
        logger.info(
            "Installing model pack bundle: bundle_path=%s expected_canonical_model_key=%s",
            bundle_path,
            expected_canonical_model_key or "",
        )
        bundle_dir = Path(bundle_path)
        manifest = validate_model_pack_manifest(
            json.loads((bundle_dir / "pack.json").read_text(encoding="utf-8")),
            expected_canonical_model_key=expected_canonical_model_key,
        )
        lessons_json = json.loads((bundle_dir / "lessons.json").read_text(encoding="utf-8"))

        metadata = ModelPackMetadata(
            canonical_model_key=manifest["canonical_model_key"],
            version=manifest["version"],
            install_status="installed",
            source_repo=manifest.get("source_repo"),
            source_repo_commit=manifest.get("source_repo_commit"),
            pack_path=str(bundle_dir),
            metadata={
                "supported_aliases": ",".join(manifest.get("supported_aliases", [])),
                "export_id": manifest.get("export_id", ""),
                "repository_path": manifest.get("repository_path", ""),
                "schema_version": manifest.get("schema_version", ""),
                "lessons_schema_version": manifest.get("lessons_schema_version", ""),
                "repository_layout_version": manifest.get("repository_layout_version", ""),
                "source_ref": manifest.get("source_ref", ""),
            },
        )
        validate_model_pack_metadata(metadata)
        normalized_lessons_payload = normalize_model_pack_lessons_payload(
            lessons_json,
            expected_canonical_model_key=metadata.canonical_model_key,
        )
        if normalized_lessons_payload["schema_version"] != manifest["lessons_schema_version"]:
            raise ValueError(
                "Model-pack lessons payload schema_version does not match the manifest "
                "lessons_schema_version."
            )
        lessons = [
            lesson_from_bundle_item(
                item,
                expected_canonical_model_key=metadata.canonical_model_key,
            )
            for item in normalized_lessons_payload["lessons"]
        ]
        self.system_db.upsert_model_pack(metadata, lessons)
        logger.info(
            "Installed model pack: canonical_model_key=%s version=%s pack_path=%s source_repo=%s source_commit=%s",
            metadata.canonical_model_key,
            metadata.version,
            metadata.pack_path or "",
            metadata.source_repo or "",
            metadata.source_repo_commit or "",
        )
        return metadata

    def install_remote_bundle(
        self,
        canonical_model_key: str,
        *,
        repo: str = DEFAULT_MODEL_PACK_REPO,
        ref: str = DEFAULT_MODEL_PACK_REF,
        expected_canonical_model_key: str | None = None,
    ) -> ModelPackMetadata:
        """Fetch, cache, and install a model pack from the community repository."""
        logger.info(
            "Installing remote model pack: canonical_model_key=%s repo=%s ref=%s expected_canonical_model_key=%s",
            canonical_model_key,
            repo,
            ref,
            expected_canonical_model_key or "",
        )
        remote_bundle = self.fetch_remote_bundle(
            canonical_model_key=canonical_model_key,
            repo=repo,
            ref=ref,
        )
        return self.install_bundle(
            remote_bundle.bundle_dir,
            expected_canonical_model_key=expected_canonical_model_key,
        )

    def update_bundle(
        self,
        canonical_model_key: str,
        bundle_path: str | Path | None = None,
        *,
        repo: str | None = None,
        ref: str | None = None,
    ) -> ModelPackMetadata:
        """Refresh an installed bundle using its source path or an explicit bundle path."""
        logger.info(
            "Updating model pack: canonical_model_key=%s bundle_path=%s repo=%s ref=%s",
            canonical_model_key,
            bundle_path or "",
            repo or "",
            ref or "",
        )
        packs = {pack["canonical_model_key"]: pack for pack in self.system_db.list_model_packs()}
        installed = packs.get(canonical_model_key, {})
        if bundle_path:
            logger.info(
                "Updating model pack from explicit bundle path: canonical_model_key=%s bundle_path=%s",
                canonical_model_key,
                bundle_path,
            )
            return self.install_bundle(
                bundle_path, expected_canonical_model_key=canonical_model_key
            )

        metadata = self._parse_metadata_json(installed.get("metadata_json"))
        remote_repo = repo or str(installed.get("source_repo") or "").strip()
        remote_ref = ref or str(metadata.get("source_ref") or DEFAULT_MODEL_PACK_REF)
        if remote_repo:
            logger.info(
                "Updating model pack from remote source: canonical_model_key=%s repo=%s ref=%s",
                canonical_model_key,
                remote_repo,
                remote_ref,
            )
            return self.install_remote_bundle(
                canonical_model_key=canonical_model_key,
                repo=remote_repo,
                ref=remote_ref,
                expected_canonical_model_key=canonical_model_key,
            )

        target = installed.get("pack_path")
        if not target:
            msg = f"No installed pack or bundle path found for {canonical_model_key}"
            raise ValueError(msg)
        logger.info(
            "Updating model pack from installed local path: canonical_model_key=%s pack_path=%s",
            canonical_model_key,
            target,
        )
        return self.install_bundle(target, expected_canonical_model_key=canonical_model_key)

    def fetch_remote_bundle(
        self,
        canonical_model_key: str,
        *,
        repo: str = DEFAULT_MODEL_PACK_REPO,
        ref: str = DEFAULT_MODEL_PACK_REF,
    ) -> RemoteBundleResult:
        """Fetch one remote model pack and persist it into the local cache."""
        logger.info(
            "Fetching remote model pack: canonical_model_key=%s repo=%s ref=%s",
            canonical_model_key,
            repo,
            ref,
        )
        repo_paths = repository_relative_paths(canonical_model_key)
        adapter = self.github_adapter_cls(repo=repo)
        manifest_text = adapter.get_file_content(repo_paths["manifest"], ref=ref)
        if manifest_text is None:
            raise ValueError(
                f"Could not fetch remote model-pack manifest for {canonical_model_key} from "
                f"{repo}@{ref}"
            )
        lessons_text = adapter.get_file_content(repo_paths["lessons"], ref=ref)
        if lessons_text is None:
            raise ValueError(
                f"Could not fetch remote model-pack lessons for {canonical_model_key} from "
                f"{repo}@{ref}"
            )

        manifest = validate_model_pack_manifest(json.loads(manifest_text))
        lessons_payload = normalize_model_pack_lessons_payload(
            json.loads(lessons_text),
            expected_canonical_model_key=manifest["canonical_model_key"],
        )
        if lessons_payload["schema_version"] != manifest["lessons_schema_version"]:
            raise ValueError(
                "Model-pack lessons payload schema_version does not match the manifest "
                "lessons_schema_version."
            )

        remote_commit = adapter.get_branch_sha(ref)
        bundle_dir = self._remote_cache_dir(
            repo=repo,
            ref=ref,
            canonical_model_key=manifest["canonical_model_key"],
            version=str(manifest["version"]),
            commit=remote_commit,
        )
        bundle_dir.mkdir(parents=True, exist_ok=True)

        cached_manifest = dict(manifest)
        cached_manifest["source_repo"] = repo
        cached_manifest["source_ref"] = ref
        if remote_commit:
            cached_manifest["source_repo_commit"] = remote_commit
        (bundle_dir / "pack.json").write_text(
            json.dumps(cached_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (bundle_dir / "lessons.json").write_text(
            json.dumps(lessons_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.info(
            "Fetched remote model pack into cache: canonical_model_key=%s repo=%s ref=%s commit=%s bundle_dir=%s",
            manifest["canonical_model_key"],
            repo,
            ref,
            remote_commit or "",
            bundle_dir,
        )

        return RemoteBundleResult(
            repo=repo,
            ref=ref,
            commit=remote_commit,
            bundle_dir=bundle_dir,
            manifest=cached_manifest,
            lessons_payload=lessons_payload,
        )

    def submit_draft_pr(
        self,
        bundle_path: str | Path,
        repo: str = DEFAULT_MODEL_PACK_REPO,
        base_branch: str = "main",
    ) -> dict[str, Any]:
        """Create a draft PR in the community model-pack repository."""
        logger.info(
            "Submitting model pack draft PR: bundle_path=%s repo=%s base_branch=%s",
            bundle_path,
            repo,
            base_branch,
        )
        bundle_dir = Path(bundle_path)
        manifest = validate_model_pack_manifest(
            json.loads((bundle_dir / "pack.json").read_text(encoding="utf-8"))
        )
        lessons_payload = normalize_model_pack_lessons_payload(
            json.loads((bundle_dir / "lessons.json").read_text(encoding="utf-8")),
            expected_canonical_model_key=manifest["canonical_model_key"],
        )
        if lessons_payload["schema_version"] != manifest["lessons_schema_version"]:
            raise ValueError(
                "Model-pack lessons payload schema_version does not match the manifest "
                "lessons_schema_version."
            )
        export_id = manifest["export_id"]
        public_manifest = self._public_submission_manifest(manifest)
        submission_fingerprint = self._submission_fingerprint(public_manifest, lessons_payload)
        moderation_labels = self._moderation_labels()
        lesson_keys = self._lesson_keys(lessons_payload)
        submission_metadata = {
            "bundle_path": str(bundle_dir),
            "repository_path": public_manifest["repository_path"],
            "submission_fingerprint": submission_fingerprint,
            "lesson_keys": lesson_keys,
            "lesson_key_count": len(lesson_keys),
            "moderation_labels": moderation_labels,
            "source_ref": str(public_manifest.get("source_ref", "")),
        }

        existing = self.system_db.get_submission(export_id)
        if existing and existing.get("pr_url"):
            logger.info(
                "Reusing existing model pack submission: export_id=%s repo=%s branch=%s pr_url=%s",
                export_id,
                repo,
                existing.get("branch") or "",
                existing.get("pr_url") or "",
            )
            return self._submission_response(
                existing, status_override=str(existing.get("status") or "")
            )

        duplicate = self.system_db.find_submission_by_fingerprint(
            repo=repo,
            canonical_model_key=manifest["canonical_model_key"],
            submission_fingerprint=submission_fingerprint,
        )
        if duplicate and str(duplicate.get("export_id")) != export_id and duplicate.get("pr_url"):
            logger.info(
                "Detected duplicate model pack submission: requested_export_id=%s duplicate_of_export_id=%s repo=%s pr_url=%s",
                export_id,
                duplicate.get("export_id") or "",
                repo,
                duplicate.get("pr_url") or "",
            )
            return self._submission_response(
                duplicate,
                status_override="duplicate_existing",
                extra={
                    "requested_export_id": export_id,
                    "duplicate_of_export_id": str(duplicate.get("export_id") or ""),
                },
            )

        canonical_model_key = manifest["canonical_model_key"]
        active_submission = existing or duplicate
        branch = str(active_submission.get("branch") or "").strip() if active_submission else ""
        if not branch:
            branch = self._submission_branch_name(
                canonical_model_key=canonical_model_key,
                submission_fingerprint=submission_fingerprint,
            )
        adapter = self.github_adapter_cls(repo=repo)
        if not adapter.token:
            raise RuntimeError("GitHub authentication is required for model-pack submission.")

        adapter.create_branch(branch, from_branch=base_branch)

        active_export_id = (
            str(active_submission.get("export_id") or export_id) if active_submission else export_id
        )
        public_manifest["export_id"] = active_export_id
        repo_prefix = public_manifest["repository_path"]
        files_to_commit = {
            f"{repo_prefix}/pack.json": json.dumps(public_manifest, indent=2, sort_keys=True),
            f"{repo_prefix}/lessons.json": json.dumps(
                lessons_payload,
                indent=2,
                sort_keys=True,
            ),
        }
        for path, content in files_to_commit.items():
            adapter.create_commit(
                path=path,
                message=f"feat: add model pack candidate for {canonical_model_key}",
                content=content,
                branch=branch,
            )

        pr = None
        if not active_submission or not active_submission.get("pr_url"):
            pr = adapter.create_pull_request(
                title=f"Add model pack candidate for {canonical_model_key}",
                body=self._build_pr_body(public_manifest, lessons_payload, moderation_labels),
                head=branch,
                base=base_branch,
                draft=True,
            )
            pr_number = pr.get("number") if pr else None
            if isinstance(pr_number, int) and moderation_labels:
                adapter.add_labels(pr_number, moderation_labels)
        else:
            pr_number = self._submission_pr_number(active_submission)
        record = PackSubmissionRecord(
            export_id=active_export_id,
            canonical_model_key=canonical_model_key,
            repo=repo,
            branch=branch,
            status="draft_opened"
            if (pr or (active_submission and active_submission.get("pr_url")))
            else "exported",
            pr_url=(
                pr.get("html_url")
                if pr
                else (str(active_submission.get("pr_url")) if active_submission else None)
            ),
            metadata={
                **submission_metadata,
                "pr_number": pr_number,
                "retryable": True,
                "duplicate_of_export_id": (
                    str(duplicate.get("export_id") or "")
                    if duplicate and str(duplicate.get("export_id") or "") != export_id
                    else ""
                ),
            },
        )
        self.system_db.upsert_submission(record)
        logger.info(
            "Submitted model pack draft PR: export_id=%s repo=%s branch=%s pr_url=%s status=%s",
            active_export_id,
            repo,
            branch,
            record.pr_url or "",
            record.status,
        )
        return {
            "export_id": active_export_id,
            "requested_export_id": export_id,
            "repo": repo,
            "branch": branch,
            "pr_url": record.pr_url,
            "status": (
                "duplicate_existing"
                if duplicate and str(duplicate.get("export_id") or "") != export_id
                else record.status
            ),
            "duplicate_of_export_id": (
                str(duplicate.get("export_id") or "")
                if duplicate and str(duplicate.get("export_id") or "") != export_id
                else None
            ),
        }

    def get_active_pack_id(self, canonical_model_key: str | None = None) -> str | None:
        """Return the content hash of the currently-active model pack.

        Used by M27Client.chat_structured to include the pack content-hash in
        the response-cache key so that pack updates invalidate stale entries.
        Fix: B.5.

        Args:
            canonical_model_key: If provided, look up this specific pack.
                Otherwise, return the hash of the first installed pack found.

        Returns:
            SHA-256 hex digest of the serialised pack content, or ``None``
            if no pack is installed / accessible.
        """
        try:
            packs = self.system_db.list_model_packs()
        except Exception:
            logger.debug("get_active_pack_id: failed to list model packs", exc_info=True)
            return None

        if not packs:
            return None

        if canonical_model_key:
            pack_rows = [p for p in packs if p.get("canonical_model_key") == canonical_model_key]
        else:
            pack_rows = list(packs)

        if not pack_rows:
            return None

        pack_row = pack_rows[0]
        pack_path_str = pack_row.get("pack_path")
        if pack_path_str:
            bundle_dir = Path(str(pack_path_str))
            try:
                manifest_text = (bundle_dir / "pack.json").read_text(encoding="utf-8")
                lessons_text = (bundle_dir / "lessons.json").read_text(encoding="utf-8")
                combined = manifest_text + "||" + lessons_text
                return hashlib.sha256(combined.encode("utf-8")).hexdigest()
            except Exception:
                logger.debug(
                    "get_active_pack_id: failed to hash bundle at %s", pack_path_str, exc_info=True
                )

        # Fallback: hash the DB row itself (version + canonical_model_key + metadata)
        row_repr = json.dumps(pack_row, sort_keys=True, default=str)
        return hashlib.sha256(row_repr.encode("utf-8")).hexdigest()

    def scaffold_repository_standard(self, output_dir: str | Path) -> RepositoryScaffoldResult:
        """Write the public model-pack repository scaffold to a target directory."""
        root_dir = Path(output_dir)
        files_written: list[Path] = []
        for relative_path, content in sorted(repository_scaffold_files().items()):
            target = root_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            files_written.append(target)
        return RepositoryScaffoldResult(root_dir=root_dir, files_written=files_written)

    def _default_scope_tags(self) -> list[str]:
        config_path = Path(self.project_path) / ".muscle" / "config.yaml"
        tags: list[str] = []
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text(encoding="utf-8"))
                project = data.get("project", {})
                tags.extend(
                    str(tag).strip().lower()
                    for tag in (
                        list(project.get("languages", [])) + list(project.get("frameworks", []))
                    )
                    if str(tag).strip()
                )
        except Exception:
            logger.debug(
                "Failed to load scope tags from config for %s", self.project_path, exc_info=True
            )

        if not tags:
            fingerprint = build_project_fingerprint(Path(self.project_path))
            tags.extend(
                str(tag).strip().lower()
                for tag in (fingerprint.languages + fingerprint.frameworks)
                if str(tag).strip()
            )
        normalized = sorted(set(tags))
        return normalized or ["general"]

    @staticmethod
    def _parse_metadata_json(metadata_json: Any) -> dict[str, Any]:
        if not metadata_json:
            return {}
        if isinstance(metadata_json, dict):
            return metadata_json
        try:
            parsed = json.loads(str(metadata_json))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _remote_cache_dir(
        *,
        repo: str,
        ref: str,
        canonical_model_key: str,
        version: str,
        commit: str | None,
    ) -> Path:
        repo_slug = repo.replace("/", "__")
        model_slug = canonical_model_key.replace("/", "__").replace("@", "_")
        version_slug = version.replace("/", "_").replace(" ", "_")
        commit_slug = (commit or "unknown")[:12]
        return REMOTE_CACHE_DIR / repo_slug / ref / model_slug / f"{version_slug}-{commit_slug}"

    @staticmethod
    def _submission_branch_name(
        *,
        canonical_model_key: str,
        submission_fingerprint: str,
    ) -> str:
        model_slug = canonical_model_key.replace("/", "-").replace("@", "-")
        return f"muscle-pack/{model_slug}-{submission_fingerprint[:12]}"

    @staticmethod
    def _lesson_keys(lessons_payload: dict[str, Any]) -> list[str]:
        lessons = lessons_payload.get("lessons", [])
        if not isinstance(lessons, list):
            return []
        return sorted(
            {
                str(item.get("lesson_key") or "").strip()
                for item in lessons
                if isinstance(item, dict) and str(item.get("lesson_key") or "").strip()
            }
        )

    @staticmethod
    def _moderation_labels() -> list[str]:
        return list(MODERATION_LABELS)

    @staticmethod
    def _submission_pr_number(submission: dict[str, Any]) -> int | None:
        metadata = ModelPackManager._parse_metadata_json(submission.get("metadata_json"))
        value = metadata.get("pr_number")
        return value if isinstance(value, int) else None

    @staticmethod
    def _public_submission_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
        public_manifest = dict(manifest)
        if public_manifest.pop("source_project", None):
            public_manifest["source_project_redacted"] = True
        public_manifest["submission_origin"] = "project-local-learned-rules"
        return public_manifest

    @staticmethod
    def _submission_fingerprint(
        manifest: dict[str, Any],
        lessons_payload: dict[str, Any],
    ) -> str:
        fingerprint_source = {
            "canonical_model_key": manifest.get("canonical_model_key"),
            "repository_path": manifest.get("repository_path"),
            "version": manifest.get("version"),
            "supported_aliases": sorted(manifest.get("supported_aliases", [])),
            "scrubber_version": manifest.get("scrubber_version"),
            "lesson_signatures": [
                {
                    "lesson_key": str(item.get("lesson_key") or ""),
                    "scope_tags": sorted(set(item.get("scope_tags", []))),
                    "safety_scope": str(item.get("safety_scope") or ""),
                    "portability": str(item.get("portability") or ""),
                    "lesson_hash": hashlib.sha256(
                        str(item.get("lesson_text") or "").encode("utf-8")
                    ).hexdigest(),
                }
                for item in lessons_payload.get("lessons", [])
                if isinstance(item, dict)
            ],
        }
        normalized = json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _submission_response(
        submission: dict[str, Any],
        *,
        status_override: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = {
            "export_id": str(submission.get("export_id") or ""),
            "repo": str(submission.get("repo") or ""),
            "branch": str(submission.get("branch") or ""),
            "pr_url": submission.get("pr_url"),
            "status": status_override or str(submission.get("status") or ""),
        }
        if extra:
            response.update(extra)
        return response

    @staticmethod
    def _lesson_to_dict(lesson: ModelPackLesson) -> dict[str, Any]:
        return {
            "canonical_model_key": lesson.canonical_model_key,
            "lesson_key": lesson.lesson_key,
            "lesson_text": lesson.lesson_text,
            "scope_tags": sorted(set(lesson.scope_tags)),
            "safety_scope": lesson.safety_scope,
            "portability": lesson.portability,
            "evidence": lesson.evidence,
            "rationale": lesson.rationale,
            "source_repo_commit": lesson.source_repo_commit,
        }

    @staticmethod
    def _build_pr_body(
        manifest: dict[str, Any],
        lessons_payload: dict[str, Any],
        moderation_labels: list[str],
    ) -> str:
        repo_paths = repository_relative_paths(manifest["canonical_model_key"])
        lesson_keys = ModelPackManager._lesson_keys(lessons_payload)
        lesson_key_preview = ", ".join(lesson_keys[:MAX_PR_BODY_LESSON_KEYS]) or "None"
        if len(lesson_keys) > MAX_PR_BODY_LESSON_KEYS:
            lesson_key_preview += f", +{len(lesson_keys) - MAX_PR_BODY_LESSON_KEYS} more"
        return "\n".join(
            [
                "## Summary",
                f"- Canonical model: `{manifest['canonical_model_key']}`",
                f"- Export ID: `{manifest['export_id']}`",
                f"- Lesson count: `{manifest['lesson_count']}`",
                f"- Repository path: `{repo_paths['prefix']}`",
                f"- Pack schema: `{manifest.get('schema_version', PACK_MANIFEST_SCHEMA_VERSION)}`",
                (
                    "- Lessons schema: "
                    f"`{manifest.get('lessons_schema_version', PACK_LESSONS_SCHEMA_VERSION)}`"
                ),
                "",
                "## Evidence",
                "- Exported from MUSCLE project-local learned rules",
                "- Scrubbed to remove project-specific identifiers and unsafe portable content",
                f"- Scrubber version: `{manifest.get('scrubber_version', 'unknown')}`",
                f"- Rejected lessons during export: `{manifest.get('rejected_lesson_count', 0)}`",
                f"- Supported aliases: `{', '.join(manifest.get('supported_aliases', []) or []) or 'None'}`",
                f"- Lesson keys: `{lesson_key_preview}`",
                "",
                "## Moderation Labels",
                f"- {', '.join(f'`{label}`' for label in moderation_labels)}",
                "",
                "## Review Checklist",
                "- [ ] Canonical model key matches the submitted repository path",
                "- [ ] Lessons are portable and free of project-local identifiers",
                "- [ ] Safety scopes are appropriate for the claimed usage stage",
                "- [ ] Evidence and rationale are sufficient for public inclusion",
                "- [ ] No existing pack or open PR already covers the same lessons",
                "",
                "## Review Notes",
                "- This PR is intentionally opened as draft for human review.",
                "- The submitted files follow the canonical `packs/<canonical-model-key>/` layout.",
                "- Local source-project paths are redacted from the committed public manifest.",
            ]
        )
