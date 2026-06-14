"""
Cache-aware prompt prefix planning.

Architecture Decision Record (ADR):
- Make stable prompt prefixes measurable so host cache behavior can be tested
  instead of left as a prose convention.
- Keep linting deterministic and conservative; warnings annotate cache risk
  without rewriting prompts.
- Label cost numbers as estimates until provider cache telemetry is available.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

FABLE_FRESH_INPUT_PER_CHAR = 10.00 / 1_000_000 / 4
FABLE_CACHE_READ_PER_CHAR = 1.00 / 1_000_000 / 4


@dataclass(frozen=True)
class PromptPrefixSection:
    """One ordered prompt section."""

    name: str
    content: str
    stable: bool = True


@dataclass(frozen=True)
class PromptPrefixLintWarning:
    """A cache-prefix lint warning."""

    code: str
    section_name: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "section_name": self.section_name,
            "message": self.message,
        }


@dataclass(frozen=True)
class PromptPrefixCostEstimate:
    """Estimated Fable cache cost for the stable prefix."""

    prefix_chars: int
    estimated_cache_fresh_cost: float
    estimated_cache_read_cost: float
    confidence: str = "estimated"

    def to_dict(self) -> dict[str, object]:
        return {
            "prefix_chars": self.prefix_chars,
            "estimated_cache_fresh_cost": round(self.estimated_cache_fresh_cost, 8),
            "estimated_cache_read_cost": round(self.estimated_cache_read_cost, 8),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class PromptPrefixPlan:
    """Stable/dynamic prompt layout with lint and cost metadata."""

    sections: list[PromptPrefixSection]
    lint_warnings: list[PromptPrefixLintWarning] = field(default_factory=list)
    cost_estimate: PromptPrefixCostEstimate | None = None

    @property
    def stable_prefix(self) -> str:
        return "\n\n".join(section.content for section in self.sections if section.stable)

    @property
    def dynamic_payload(self) -> str:
        return "\n\n".join(section.content for section in self.sections if not section.stable)

    @property
    def cache_prefix_digest(self) -> str:
        return hashlib.sha256(self.stable_prefix.encode("utf-8")).hexdigest()

    def to_metadata(self) -> dict[str, object]:
        estimate = self.cost_estimate or estimate_prefix_cost(len(self.stable_prefix))
        return {
            "cache_prefix_chars": len(self.stable_prefix),
            "cache_prefix_digest": self.cache_prefix_digest,
            "cache_prefix_lint_warning_count": len(self.lint_warnings),
            "cache_prefix_lint_warnings": [warning.to_dict() for warning in self.lint_warnings],
            **estimate.to_dict(),
        }


class PromptPrefixPlanner:
    """Build and lint stable prompt-prefix plans."""

    def plan(
        self,
        *,
        system_instructions: str = "",
        methodology: str = "",
        stable_project_summary: str = "",
        model_pack_lessons: str = "",
        tool_schemas: str = "",
        dynamic_task_payload: str = "",
    ) -> PromptPrefixPlan:
        """Return a plan in the canonical stable-prefix order."""
        sections = [
            PromptPrefixSection("system_instructions", system_instructions),
            PromptPrefixSection("methodology", methodology),
            PromptPrefixSection("stable_project_summary", stable_project_summary),
            PromptPrefixSection("model_pack_lessons", model_pack_lessons),
            PromptPrefixSection("tool_schemas", tool_schemas),
            PromptPrefixSection("dynamic_task_payload", dynamic_task_payload, stable=False),
        ]
        sections = [section for section in sections if section.content]
        lint_warnings = lint_prompt_prefix(sections)
        stable_prefix = "\n\n".join(section.content for section in sections if section.stable)
        return PromptPrefixPlan(
            sections=sections,
            lint_warnings=lint_warnings,
            cost_estimate=estimate_prefix_cost(len(stable_prefix)),
        )

    def plan_rendered_prompt(self, prompt: str) -> PromptPrefixPlan:
        """Infer stable prefix from an already-rendered prompt.

        For current MUSCLE prompts, the first untrusted-content envelope marks
        the beginning of the dynamic task payload. Prompts without that marker
        are treated as entirely stable.
        """
        marker = "===== BEGIN MUSCLE UNTRUSTED CONTENT ====="
        index = prompt.find(marker)
        if index == -1:
            return self.plan(system_instructions=prompt)
        stable_prefix = prompt[:index].rstrip()
        dynamic_payload = prompt[index:].lstrip()
        return self.plan(system_instructions=stable_prefix, dynamic_task_payload=dynamic_payload)


_TIMESTAMP_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?)?\b")
_RANDOM_ID_RE = re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)
_ABS_PATH_RE = re.compile(r"(?:^|\s)/(?:Users|tmp|private|var|home)/\S+")
_TOKEN_COUNTER_RE = re.compile(r"\b\d{3,}\s+tokens?\b", re.IGNORECASE)
_TRANSIENT_STATUS_RE = re.compile(
    r"\b(in progress|running|retrying|queued|elapsed)\b", re.IGNORECASE
)
_COMMAND_OUTPUT_RE = re.compile(r"\b(traceback|collected \d+ items|failed|error:)\b", re.IGNORECASE)


def lint_prompt_prefix(sections: list[PromptPrefixSection]) -> list[PromptPrefixLintWarning]:
    """Flag volatile content in stable sections."""
    warnings: list[PromptPrefixLintWarning] = []
    for section in sections:
        if not section.stable:
            continue
        content = section.content
        for code, pattern, message in [
            ("timestamp", _TIMESTAMP_RE, "timestamp in stable prefix"),
            ("random_id", _RANDOM_ID_RE, "random-looking id in stable prefix"),
            ("transient_status", _TRANSIENT_STATUS_RE, "transient status in stable prefix"),
            ("path_list", _ABS_PATH_RE, "absolute path list in stable prefix"),
            ("token_counter", _TOKEN_COUNTER_RE, "token counter in stable prefix"),
            ("command_output", _COMMAND_OUTPUT_RE, "command output in stable prefix"),
        ]:
            if pattern.search(content):
                warnings.append(
                    PromptPrefixLintWarning(
                        code=code,
                        section_name=section.name,
                        message=message,
                    )
                )
    return warnings


def estimate_prefix_cost(prefix_chars: int) -> PromptPrefixCostEstimate:
    """Estimate fresh/read cache cost for a Fable-style host prefix."""
    return PromptPrefixCostEstimate(
        prefix_chars=prefix_chars,
        estimated_cache_fresh_cost=prefix_chars * FABLE_FRESH_INPUT_PER_CHAR,
        estimated_cache_read_cost=prefix_chars * FABLE_CACHE_READ_PER_CHAR,
    )
