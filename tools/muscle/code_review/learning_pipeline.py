"""
Learning Pipeline - Orchestrates the self-learning cycle after reviews.

Wires together MemoryManager, PatternDetector, and SkillGenerator to:
1. Categorize findings by severity
2. Update CLAUDE.md with rules + anti-patterns (high/critical immediately)
3. Update MEMORY.md with pattern history and review sessions
4. Detect recurring patterns and generate skills
5. Validate existing rules and archive stale ones
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .memory_manager import MemoryManager
from .pattern_detector import PatternDetector
from .skill_generator import SkillGenerator
from .types import ReviewResult, Severity

logger = logging.getLogger(__name__)

ARCHIVE_VALIDATED_THRESHOLD = 10


class LearningPipeline:
    """Orchestrates the full self-learning cycle after a review."""

    def __init__(
        self,
        project_path: str,
        m27_client: Any | None = None,
        kb_path: str | None = None,
    ):
        self.project_path = Path(project_path)
        self.memory_manager = MemoryManager(project_path, m27_client)
        self.m27 = m27_client
        self._kb_path = kb_path
        self._last_validated_count: int = 0
        self._last_archived_count: int = 0

    def learn_from_review(self, review_result: ReviewResult) -> dict:
        """Main entry point -- called after every review completes."""
        actions: dict[str, Any] = {
            "rules_added": 0,
            "rules_validated": 0,
            "rules_archived": 0,
            "skills_generated": 0,
            "session_logged": False,
        }

        if not review_result.issues:
            self._validate_existing_rules(review_result)
            actions["rules_validated"] = self._last_validated_count
            actions["rules_archived"] = self._last_archived_count
            self._log_review_session(review_result, actions)
            actions["session_logged"] = True
            return actions

        immediate, tracked = self._categorize_findings(review_result)

        for issue in immediate:
            rule_type = "dont"
            if issue.suggested_fix:
                rule_text = f"{issue.title} — {issue.suggested_fix}"
            else:
                rule_text = f"{issue.title} in `{issue.file_path}`"

            added = self.memory_manager.write_rule(
                rule_text=rule_text,
                rule_type=rule_type,
                severity=issue.severity.name.lower(),
                confidence="low",
                validated_count=0,
            )
            if added:
                actions["rules_added"] += 1

        for issue in tracked:
            self.memory_manager.update_memory_md(
                f"{issue.severity.name}: {issue.title} in `{issue.file_path}`",
                category="pattern",
            )

        self._validate_existing_rules(review_result)
        actions["rules_validated"] = self._last_validated_count
        actions["rules_archived"] = self._last_archived_count

        skills = self._detect_and_generate_skills()
        actions["skills_generated"] = skills

        self._log_review_session(review_result, actions)
        actions["session_logged"] = True

        return actions

    def _categorize_findings(self, review_result: ReviewResult) -> tuple[list, list]:
        """Split: high/critical -> immediate rules, medium/low/info -> tracked in MEMORY.md."""
        immediate = []
        tracked = []
        for issue in review_result.issues:
            if issue.severity in (Severity.CRITICAL, Severity.HIGH):
                immediate.append(issue)
            else:
                tracked.append(issue)
        return immediate, tracked

    def _validate_existing_rules(self, review_result: ReviewResult) -> None:
        """Check each existing rule against current review findings."""
        self._last_validated_count = 0
        self._last_archived_count = 0

        rules = self.memory_manager.read_rules()
        issue_titles_lower = {i.title.lower() for i in review_result.issues}

        for rule in rules:
            rule_text_lower = rule["text"].lower()
            pattern_found = any(
                title in rule_text_lower or rule_text_lower in title
                for title in issue_titles_lower
            )

            if not pattern_found:
                new_count = rule["validated_count"] + 1
                new_confidence = self._compute_confidence(new_count)

                if new_count >= ARCHIVE_VALIDATED_THRESHOLD and new_confidence == "high":
                    self.memory_manager.archive_rule(
                        rule["text"],
                        reason=f"not seen in {new_count}+ clean reviews",
                    )
                    self._last_archived_count += 1
                else:
                    self.memory_manager.update_rule_validation(
                        rule["text"],
                        validated_count=new_count,
                        confidence=new_confidence,
                    )
                    self._last_validated_count += 1

    def _compute_confidence(self, validated_count: int) -> str:
        if validated_count >= 4:
            return "high"
        if validated_count >= 2:
            return "medium"
        return "low"

    def _detect_and_generate_skills(self) -> int:
        """Run pattern detection and generate skills for recurring patterns."""
        try:
            detector = PatternDetector(kb_path=self._kb_path, m27_client=self.m27)
            detector.detect_patterns()
            candidates = detector.get_skill_candidates()

            if not candidates:
                return 0

            generator = SkillGenerator(str(self.project_path), self.m27)
            count = 0

            for pattern in candidates:
                if detector.should_create_skill(pattern):
                    skill_path = generator.generate_skill(
                        pattern,
                        pattern.semantically_related_issues,
                    )
                    if skill_path:
                        self.memory_manager.write_skill_ref(
                            pattern.pattern[:40],
                            skill_path,
                        )
                        count += 1

            return count
        except Exception as e:
            logger.warning(f"Skill generation failed: {e}")
            return 0

    def _log_review_session(self, review_result: ReviewResult, actions: dict) -> None:
        """Log review session summary to MEMORY.md."""
        action_parts: list[str] = []
        if actions.get("rules_added"):
            action_parts.append(f"added {actions['rules_added']} rules")
        if actions.get("rules_validated"):
            action_parts.append(f"validated {actions['rules_validated']} rules")
        if actions.get("rules_archived"):
            action_parts.append(f"archived {actions['rules_archived']} rules")
        if actions.get("skills_generated"):
            action_parts.append(f"generated {actions['skills_generated']} skills")

        if not action_parts:
            action_parts = ["no actions"]

        self.memory_manager.log_review_session(
            critical=review_result.critical_count,
            high=review_result.high_count,
            medium=review_result.medium_count,
            low=review_result.low_count,
            actions=action_parts,
        )
