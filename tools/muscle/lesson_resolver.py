"""
Prompt-time lesson resolution across local, related-project, model-pack, and global tiers.

Architecture Decision Record (ADR):
- Keep project-local lessons authoritative
- Treat transferred and model-pack lessons as provisional overlays
- Cap every tier independently so prompts stay bounded
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model_identity import ModelIdentityResolver
from .model_pack_validation import stage_allows_model_pack_scope
from .project_fingerprint import build_project_fingerprint
from .project_memory import ProjectMemory
from .project_memory_types import ModelIdentity
from .strategy_kb import GlobalKnowledgeBase
from .system_db import SystemDatabase

logger = logging.getLogger(__name__)

MAX_LOCAL_LESSONS = 6
MAX_RELATED_LESSONS = 4
MAX_MODEL_PACK_LESSONS = 4
MAX_GLOBAL_LESSONS = 3
MAX_RENDER_CHARS = 2800


def _stable_key(*parts: str) -> str:
    return hashlib.sha1("::".join(parts).encode("utf-8")).hexdigest()[:16]


def _normalize_text(text: str | None) -> str:
    return (text or "").strip().replace("\x00", "")


def _estimate_tokens(text: str) -> int:
    normalized = _normalize_text(text)
    if not normalized:
        return 0
    return max(1, math.ceil(len(normalized) / 4))


@dataclass(frozen=True)
class LessonRenderBudget:
    """Approximate token budget for rendered lesson context."""

    name: str = "default"
    max_total_tokens: int = 240
    source_token_limits: dict[str, int] = field(
        default_factory=lambda: {
            "local": 120,
            "related": 50,
            "model-pack": 40,
            "global": 30,
        }
    )


@dataclass
class ResolvedLesson:
    """A single lesson selected for prompt context."""

    lesson_key: str
    lesson_text: str
    source: str
    trigger_pattern: str | None = None
    source_project_path: str | None = None
    canonical_model_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedLessonSet:
    """Structured prompt context and metadata from lesson resolution."""

    lessons: list[ResolvedLesson] = field(default_factory=list)
    rendered_context: str = ""
    canonical_model_key: str | None = None
    model_identity_source: str | None = None
    model_identity_confidence: float = 0.0
    truncated: bool = False
    render_budget_name: str | None = None
    source_render_counts: dict[str, int] = field(default_factory=dict)

    def metadata(self) -> dict[str, Any]:
        """Return telemetry-friendly metadata."""
        source_counts: dict[str, int] = {}
        for lesson in self.lessons:
            source_counts[lesson.source] = source_counts.get(lesson.source, 0) + 1
        return {
            "lesson_sources": source_counts,
            "lesson_count": len(self.lessons),
            "canonical_model_key": self.canonical_model_key,
            "model_identity_source": self.model_identity_source,
            "model_identity_confidence": self.model_identity_confidence,
            "lesson_keys": [lesson.lesson_key for lesson in self.lessons],
            "lesson_render_budget": self.render_budget_name,
            "lesson_render_source_counts": self.source_render_counts,
            "lesson_truncated": self.truncated,
        }


class LessonResolver:
    """Resolve prompt context lessons across the four MUSCLE knowledge tiers."""

    def __init__(
        self,
        project_path: str,
        project_memory: ProjectMemory | None = None,
        system_db: SystemDatabase | None = None,
        global_kb: GlobalKnowledgeBase | None = None,
        project_config: Any | None = None,
        requested_model_label: str | None = None,
        provider_endpoint: str | None = None,
    ):
        self.project_path = str(Path(project_path).resolve())
        self.project_memory = project_memory or ProjectMemory(self.project_path)
        self.system_db = system_db or SystemDatabase()
        self.global_kb = global_kb or GlobalKnowledgeBase()
        self.project_config = project_config
        self.requested_model_label = requested_model_label
        self.provider_endpoint = provider_endpoint
        self.identity_resolver = ModelIdentityResolver(self.system_db)
        self._fingerprint = build_project_fingerprint(
            Path(self.project_path),
            display_name=getattr(project_config, "name", None),
            languages=getattr(project_config, "languages", None),
        )

    def resolve_for_prompt(
        self,
        query_text: str,
        stage: str,
        session_id: str | None = None,
        call_id: str | None = None,
        language: str | None = None,
        render_budget: LessonRenderBudget | None = None,
    ) -> ResolvedLessonSet:
        """Resolve prompt context for one generation/review/fix call."""
        identity = self.identity_resolver.resolve(
            requested_label=self.requested_model_label,
            provider_endpoint=self.provider_endpoint,
            manual_override=getattr(self.project_config, "model_manual_override", None),
        )

        collected: list[ResolvedLesson] = []
        seen: set[str] = set()

        def add_lessons(candidates: list[ResolvedLesson], limit: int) -> None:
            for lesson in candidates:
                if lesson.lesson_key in seen:
                    continue
                collected.append(lesson)
                seen.add(lesson.lesson_key)
                if len([item for item in collected if item.source == lesson.source]) >= limit:
                    break

        add_lessons(self._local_lessons(query_text), MAX_LOCAL_LESSONS)
        add_lessons(self._related_lessons(query_text), MAX_RELATED_LESSONS)
        add_lessons(self._model_pack_lessons(identity, language, stage), MAX_MODEL_PACK_LESSONS)
        add_lessons(self._global_lessons(query_text, language), MAX_GLOBAL_LESSONS)

        rendered_context, rendered_lessons, truncated, source_render_counts = self._render_context(
            collected,
            render_budget=render_budget,
        )
        if session_id and rendered_lessons:
            self._record_usage(
                rendered_lessons, stage=stage, session_id=session_id, call_id=call_id
            )

        return ResolvedLessonSet(
            lessons=rendered_lessons,
            rendered_context=rendered_context,
            canonical_model_key=identity.canonical_model_key,
            model_identity_source=identity.identity_source,
            model_identity_confidence=identity.confidence,
            truncated=truncated,
            render_budget_name=(render_budget or LessonRenderBudget()).name,
            source_render_counts=source_render_counts,
        )

    def _local_lessons(self, query_text: str) -> list[ResolvedLesson]:
        query = query_text.lower()
        rows = self.project_memory.list_learned_rules(
            project_path=self.project_path,
            limit=MAX_LOCAL_LESSONS * 3,
        )
        ranked = sorted(
            rows,
            key=lambda row: (
                1 if str(row.get("trigger_pattern", "")).lower() in query else 0,
                float(row.get("success_rate", 0.0) or 0.0),
                int(row.get("recurrence_count", 0) or 0),
            ),
            reverse=True,
        )
        return [
            ResolvedLesson(
                lesson_key=_stable_key(
                    "local",
                    str(row.get("id", "")),
                    str(row.get("trigger_pattern", "")),
                    str(row.get("rule_text", "")),
                ),
                lesson_text=str(row.get("rule_text", "")),
                source="local",
                trigger_pattern=str(row.get("trigger_pattern", "")),
                source_project_path=self.project_path,
                metadata={
                    "success_rate": row.get("success_rate", 0.0),
                    "recurrence_count": row.get("recurrence_count", 0),
                },
            )
            for row in ranked[:MAX_LOCAL_LESSONS]
            if row.get("rule_text")
        ]

    def _related_lessons(self, query_text: str) -> list[ResolvedLesson]:
        rows = self.project_memory.list_transferred_lessons(
            project_path=self.project_path,
            validation_statuses=["provisional", "validated"],
            limit=MAX_RELATED_LESSONS * 3,
        )
        related: list[ResolvedLesson] = []
        query = query_text.lower()
        for row in rows:
            lesson_text = _normalize_text(str(row.get("lesson_text", "")))
            if not lesson_text:
                continue
            related.append(
                ResolvedLesson(
                    lesson_key=str(row.get("lesson_key")),
                    lesson_text=lesson_text,
                    source="related",
                    trigger_pattern=str(row.get("trigger_pattern", "")),
                    source_project_path=str(row.get("source_project_path", "")),
                    metadata={
                        "validation_status": row.get("validation_status", "provisional"),
                        "link_mode": row.get("link_mode", "snapshot"),
                        "match": 1 if str(row.get("trigger_pattern", "")).lower() in query else 0,
                    },
                )
            )

        # Attach-mode links are live read-through and never persisted into local
        for link in self.project_memory.list_related_project_links(
            project_path=self.project_path,
            status="active",
            link_mode="attach",
        ):
            source_project_path = str(link.get("source_project_path", ""))
            if not source_project_path:
                continue
            try:
                source_pm = ProjectMemory(source_project_path)
                source_rules = source_pm.list_learned_rules(
                    project_path=source_project_path,
                    limit=2,
                )
            except Exception:
                logger.debug("Failed to read attached project lessons from %s", source_project_path)
                continue

            for row in source_rules:
                lesson_text = _normalize_text(str(row.get("rule_text", "")))
                if not lesson_text:
                    continue
                related.append(
                    ResolvedLesson(
                        lesson_key=_stable_key(
                            "attach",
                            source_project_path,
                            str(row.get("id", "")),
                            lesson_text,
                        ),
                        lesson_text=lesson_text,
                        source="related",
                        trigger_pattern=str(row.get("trigger_pattern", "")),
                        source_project_path=source_project_path,
                        metadata={
                            "validation_status": "provisional",
                            "link_mode": "attach",
                        },
                    )
                )

        related.sort(
            key=lambda lesson: (
                1 if (lesson.trigger_pattern or "").lower() in query else 0,
                1 if lesson.metadata.get("validation_status") == "validated" else 0,
            ),
            reverse=True,
        )
        return related[:MAX_RELATED_LESSONS]

    def _model_pack_lessons(
        self,
        identity: ModelIdentity,
        language: str | None,
        stage: str,
    ) -> list[ResolvedLesson]:
        pack_mode = getattr(self.project_config, "model_pack_mode", "suggest")
        if pack_mode == "off":
            return []
        if not identity.canonical_model_key:
            return []
        if not identity.manual_override and identity.confidence < 0.75:
            return []

        lessons = self.system_db.get_model_pack_lessons(identity.canonical_model_key)
        current_tags = {
            item.lower() for item in (self._fingerprint.frameworks + self._fingerprint.languages)
        }
        if language:
            current_tags.add(language.lower())

        resolved: list[ResolvedLesson] = []
        for row in lessons:
            scope_tags = set(json.loads(row.get("scope_tags_json") or "[]"))
            safety_scope = str(row.get("safety_scope", "review-only") or "review-only").lower()
            portability = str(row.get("portability", "portable") or "portable").lower()
            if portability != "portable":
                continue
            if not stage_allows_model_pack_scope(stage, safety_scope):
                continue
            if (
                scope_tags
                and current_tags
                and not {tag.lower() for tag in scope_tags} & current_tags
            ):
                continue
            resolved.append(
                ResolvedLesson(
                    lesson_key=str(row.get("lesson_key")),
                    lesson_text=str(row.get("lesson_text", "")),
                    source="model-pack",
                    canonical_model_key=identity.canonical_model_key,
                    metadata={
                        "scope_tags": sorted(scope_tags),
                        "safety_scope": safety_scope,
                        "portability": portability,
                    },
                )
            )
        return resolved[:MAX_MODEL_PACK_LESSONS]

    def _global_lessons(self, query_text: str, language: str | None) -> list[ResolvedLesson]:
        if not query_text.strip():
            return []
        strategies = self.global_kb.search(query_text, language, top_k=MAX_GLOBAL_LESSONS)
        lessons: list[ResolvedLesson] = []
        for strategy in strategies:
            lesson_text = _normalize_text(strategy.solution_strategy)
            if not lesson_text:
                continue
            lessons.append(
                ResolvedLesson(
                    lesson_key=_stable_key(
                        "global", str(strategy.id or ""), strategy.error_pattern
                    ),
                    lesson_text=lesson_text,
                    source="global",
                    trigger_pattern=str(strategy.error_pattern),
                    metadata={
                        "root_cause": strategy.root_cause,
                        "success_rate": strategy.success_rate,
                    },
                )
            )
        return lessons

    def _render_context(
        self,
        lessons: list[ResolvedLesson],
        render_budget: LessonRenderBudget | None = None,
    ) -> tuple[str, list[ResolvedLesson], bool, dict[str, int]]:
        if not lessons:
            return "", [], False, {}
        budget = render_budget or LessonRenderBudget()
        sections = {
            "local": "Project-local lessons (authoritative)",
            "related": "Related-project lessons (provisional)",
            "model-pack": "Model-pack lessons (provisional)",
            "global": "Generic global lessons (fallback)",
        }
        lines = [
            "Use these MUSCLE lessons when relevant. Local project lessons outrank all others.",
            "",
        ]
        rendered_lessons: list[ResolvedLesson] = []
        source_render_counts: dict[str, int] = {}
        total_tokens = _estimate_tokens(lines[0])
        for source in ("local", "related", "model-pack", "global"):
            source_lessons = [lesson for lesson in lessons if lesson.source == source]
            if not source_lessons:
                continue
            source_limit = max(
                0, int(budget.source_token_limits.get(source, budget.max_total_tokens))
            )
            source_tokens = 0
            section_header = f"{sections[source]}:"
            section_header_tokens = _estimate_tokens(section_header)
            section_lines: list[str] = []
            prospective_lessons: list[ResolvedLesson] = []
            for lesson in source_lessons:
                trigger = f" [{lesson.trigger_pattern}]" if lesson.trigger_pattern else ""
                lesson_line = f"- {lesson.lesson_text}{trigger}"
                lesson_tokens = _estimate_tokens(lesson_line)
                added_tokens = lesson_tokens + (section_header_tokens if not section_lines else 0)
                if total_tokens + added_tokens > budget.max_total_tokens:
                    break
                if source_tokens + added_tokens > source_limit:
                    continue
                if not section_lines:
                    section_lines.append(section_header)
                    total_tokens += section_header_tokens
                    source_tokens += section_header_tokens
                section_lines.append(lesson_line)
                total_tokens += lesson_tokens
                source_tokens += lesson_tokens
                prospective_lessons.append(lesson)

            if section_lines:
                lines.extend(section_lines)
                lines.append("")
                rendered_lessons.extend(prospective_lessons)
                source_render_counts[source] = len(prospective_lessons)

        rendered = "\n".join(lines).strip()
        truncated = len(rendered_lessons) < len(lessons)
        if len(rendered) > MAX_RENDER_CHARS:
            rendered = rendered[: MAX_RENDER_CHARS - 16].rstrip() + "\n... [truncated]"
            truncated = True
        return rendered, rendered_lessons, truncated, source_render_counts

    def _record_usage(
        self,
        lessons: list[ResolvedLesson],
        stage: str,
        session_id: str,
        call_id: str | None,
    ) -> None:
        for lesson in lessons:
            try:
                self.project_memory.insert_lesson_usage_event(
                    project_path=self.project_path,
                    session_id=session_id,
                    call_id=call_id,
                    stage=stage,
                    lesson_source=lesson.source,
                    lesson_key=lesson.lesson_key,
                    canonical_model_key=lesson.canonical_model_key,
                    source_project_path=lesson.source_project_path,
                    metadata_json=json.dumps(lesson.metadata, sort_keys=True),
                )
            except Exception:
                logger.debug(
                    "Failed to record lesson usage for %s", lesson.lesson_key, exc_info=True
                )
