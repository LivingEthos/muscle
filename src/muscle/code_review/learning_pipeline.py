"""
Learning Pipeline - Orchestrates the self-learning cycle after reviews.

DB-FIRST ARCHITECTURE:
- project_memory.db is the SOURCE OF TRUTH for all review evidence and decisions
- Internal markdown (.muscle/CLAUDE.md, .muscle/AGENT.md, .muscle/MEMORY.md) is
  BOUNDED INTERNAL ARTIFACTS ONLY - not authoritative, readable for backward compat

Wires together MemoryDecisionEngine, LearningIngestor, ClaudePublisher,
PatternDetector, and SkillGenerator to:
1. Write review evidence to DB via LearningIngestor (DB-first)
2. Score findings with MemoryDecisionEngine for audit trail
3. HIGH/CRITICAL issues: write to DB + publish directly to root CLAUDE.md via ClaudePublisher
4. MEDIUM/LOW issues: write to internal markdown for tracking
5. Detect recurring patterns and generate skills
6. Validate existing rules and archive stale ones

Root CLAUDE.md publishing:
- Driven by DB-backed decisions (not by reading internal markdown first)
- LearningPipeline.build_promoted_rules() passes DB-scored rules to _publisher.publish()
- ClaudePublisher.update_markers() queries DB directly for full sync
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..claude_publisher import ClaudePublisher
from ..learning_ingestor import LearningIngestor
from ..memory_decision_engine import DecisionType, MemoryDecisionEngine
from ..project_memory import ProjectMemory
from .agent_generator import AgentGenerator
from .memory_manager import MemoryManager
from .pattern_detector import PatternDetector
from .skill_generator import SkillGenerator
from .types import ReviewIssue, ReviewResult, Severity

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
        self.m27 = m27_client

        # DB-first components
        self._pm = ProjectMemory(str(project_path))
        self._decision_engine = MemoryDecisionEngine(self._pm)
        self._ingestor = LearningIngestor(self._pm)
        self._publisher = ClaudePublisher(str(project_path))

        # Markdown-based components (internal tracking)
        self.memory_manager = MemoryManager(project_path, m27_client)

        self._kb_path = kb_path
        self._last_validated_count: int = 0
        self._last_archived_count: int = 0

    def learn_from_review(
        self,
        review_result: ReviewResult,
        review_mode: str = "review",
        token_cost: int = 0,
        duration_ms: int = 0,
    ) -> dict:
        """Main entry point -- called after every review completes.

        DB-FIRST FLOW:
        1. Write review evidence to project_memory.db via LearningIngestor
        2. Score each finding with MemoryDecisionEngine (for audit trail in DB)
        3. HIGH/CRITICAL: promoted_rules built from DB-scored data -> _publisher.publish()
           (root CLAUDE.md updated directly with DB-backed data)
        4. MEDIUM/LOW: written to internal markdown (.muscle/MEMORY.md) for tracking
        5. Archive patterns that score below threshold
        6. Run pattern detection and skill generation
        7. Log session summary to internal markdown

        NOTE: Root CLAUDE.md publishing uses DB-backed data directly.
        Internal markdown is NOT consulted for publishing decisions.

        Args:
            review_result: The ReviewResult from the review.
            review_mode: The review mode used (e.g. "review", "auto_fix").
            token_cost: Token cost of the review.
            duration_ms: Duration of the review in milliseconds.
        """
        actions: dict[str, Any] = {
            "rules_added": 0,
            "rules_validated": 0,
            "rules_archived": 0,
            "skills_generated": 0,
            "agents_generated": 0,
            "session_logged": False,
            "decisions_recorded": 0,
            "review_run_id": None,
        }

        review_run_id = self._ingestor.write_review_run(
            project_path=str(self.project_path),
            review_mode=review_mode,
            target_path=review_result.target_path,
            findings_count=len(review_result.issues),
            token_cost=token_cost,
            duration_ms=duration_ms,
        )
        actions["review_run_id"] = review_run_id

        if not review_result.issues:
            self._validate_existing_rules(review_result)
            actions["rules_validated"] = self._last_validated_count
            actions["rules_archived"] = self._last_archived_count
            self._log_review_session(review_result, actions)
            actions["session_logged"] = True
            return actions

        # Step 1: Categorize findings (maintains backward compatibility)
        immediate, tracked = self._categorize_findings(review_result)

        # Collect promoted rules for ClaudePublisher
        promoted_rules: list[dict[str, Any]] = []

        # Step 2: Write findings to DB before scoring so decisions can link to real finding IDs.
        finding_ids: list[int | None] = []
        if review_run_id:
            finding_ids = self._ingestor.write_findings_with_ids(
                review_run_id, review_result.issues
            )

        # Step 3: Score all findings for audit trail (even if not promoted)
        for idx, issue in enumerate(review_result.issues):
            recurrence_count = self._get_recurrence_count(issue)
            success_rate = self._estimate_fix_success_rate(issue)
            task_relevance = self._estimate_task_relevance(issue)
            token_savings = self._estimate_token_savings(issue)
            finding_id = finding_ids[idx] if idx < len(finding_ids) else None

            # Score and record decision for audit
            decision, score = self._decision_engine.evaluate_and_record(
                project_path=str(self.project_path),
                severity=issue.severity.name,
                recurrence_count=recurrence_count,
                success_rate=success_rate,
                task_relevance=task_relevance,
                token_savings_estimate=token_savings,
                source_table="review_findings",
                source_id=finding_id or 0,
            )
            actions["decisions_recorded"] += 1

            # Archive low-scoring patterns
            if decision == DecisionType.ARCHIVE_PATTERN:
                self._archive_issue(issue)
                actions["rules_archived"] += 1

        # Step 4: HIGH/CRITICAL issues are immediately promoted (backward compatible)
        for issue in immediate:
            rule_type = "dont"
            if issue.suggested_fix:
                rule_text = f"{issue.title} — {issue.suggested_fix}"
            else:
                rule_text = f"{issue.title} in `{issue.file_path}`"

            # Score for the rule
            recurrence_count = self._get_recurrence_count(issue)
            success_rate = self._estimate_fix_success_rate(issue)
            task_relevance = self._estimate_task_relevance(issue)
            token_savings = self._estimate_token_savings(issue)
            score = self._decision_engine.score_finding(
                severity=issue.severity.name,
                recurrence_count=recurrence_count,
                success_rate=success_rate,
                task_relevance=task_relevance,
                token_savings_estimate=token_savings,
            )

            # Add to promoted rules for ClaudePublisher
            promoted_rules.append(
                {
                    "text": rule_text,
                    "score": score,
                    "validated_count": recurrence_count,
                    "severity": issue.severity.name,
                    "issue": issue,
                }
            )

            # Also write to internal markdown for backup (returns True if added, False if duplicate)
            if self.memory_manager.write_rule(
                rule_text=rule_text,
                rule_type=rule_type,
                severity=issue.severity.name.lower(),
                confidence="low",
                validated_count=0,
            ):
                actions["rules_added"] += 1

        # Step 5: Tracked issues go to MEMORY.md (backward compatible)
        for issue in tracked:
            self.memory_manager.update_memory_md(
                f"{issue.severity.name}: {issue.title} in `{issue.file_path}`",
                category="pattern",
            )

        # Step 6: Validate existing rules and run skill detection
        self._validate_existing_rules(review_result)
        actions["rules_validated"] = self._last_validated_count
        actions["rules_archived"] = self._last_archived_count

        # Step 7: Detect patterns and generate skills + agents (DB-first)
        skill_count, agent_count = self._detect_and_generate_specializations()
        actions["skills_generated"] = skill_count
        actions["agents_generated"] = agent_count

        # Step 8: Publish the final combined state to root CLAUDE.md in one pass.
        self._publish_active_specializations(critical_rules=promoted_rules)

        self._log_review_session(review_result, actions)
        actions["session_logged"] = True

        return actions

    def _build_rule_text(self, issue: ReviewIssue) -> str:
        """Build human-readable rule text from an issue."""
        if issue.suggested_fix:
            return f"{issue.title} — {issue.suggested_fix}"
        else:
            return f"{issue.title} in `{issue.file_path}`"

    def _get_recurrence_count(self, issue: ReviewIssue) -> int:
        """Get recurrence count for a finding from DB."""
        # For now, start at 1 for new findings
        # In future, could look up prior occurrences in review_findings table
        return 1

    def _estimate_fix_success_rate(self, issue: ReviewIssue) -> float:
        """Estimate fix success rate based on issue properties."""
        if issue.auto_fixable:
            return 0.7
        return 0.3

    def _estimate_task_relevance(self, issue: ReviewIssue) -> float:
        """Estimate task relevance based on issue severity."""
        # Higher severity = higher relevance
        severity_map = {
            "CRITICAL": 0.9,
            "HIGH": 0.7,
            "MEDIUM": 0.5,
            "LOW": 0.3,
            "INFO": 0.1,
        }
        return severity_map.get(issue.severity.name, 0.5)

    def _estimate_token_savings(self, issue: ReviewIssue) -> int:
        """Estimate token savings if this issue is fixed."""
        # Rough estimate: fix saves tokens in future reviews
        severity_tokens = {
            "CRITICAL": 500,
            "HIGH": 300,
            "MEDIUM": 150,
            "LOW": 50,
            "INFO": 20,
        }
        return severity_tokens.get(issue.severity.name, 100)

    def _archive_issue(self, issue: ReviewIssue) -> None:
        """Archive an issue pattern."""
        rule_text = self._build_rule_text(issue)
        self.memory_manager.archive_rule(rule_text, reason="low score from decision engine")

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
                title in rule_text_lower or rule_text_lower in title for title in issue_titles_lower
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

    def _detect_and_generate_specializations(self) -> tuple[int, int]:
        """Run pattern detection and generate skills for recurring patterns (DB-first).

        DB-first flow:
        1. PatternDetector uses memory_decisions for evidence
        2. SkillGenerator writes metadata to DB, suppresses duplicates
        3. Record skill decisions in memory_decisions for audit trail
        4. Archive stale skills with low evidence_count
        5. AgentGenerator creates agents for complex patterns, enforces cap
        6. Record agent decisions in memory_decisions for audit trail
        """
        try:
            detector = PatternDetector(
                kb_path=self._kb_path,
                m27_client=self.m27,
                project_memory=self._pm,
            )
            detector.detect_patterns()
            skill_candidates = detector.get_skill_candidates()
            agent_candidates = detector.get_agent_candidates()

            skill_count = 0
            agent_count = 0

            # Step 1: Generate skills
            if skill_candidates:
                skill_gen = SkillGenerator(
                    str(self.project_path),
                    self.m27,
                    project_memory=self._pm,
                )

                for pattern in skill_candidates:
                    if detector.should_create_skill(pattern):
                        # Check cap before creating (MAX_ACTIVE_AGENTS enforced separately for agents)
                        skill_path = skill_gen.generate_skill(
                            pattern,
                            pattern.semantically_related_issues,
                        )
                        if skill_path:
                            # Write skill ref to CLAUDE.md for backward compat
                            self.memory_manager.write_skill_ref(
                                pattern.pattern[:40],
                                skill_path,
                            )
                            skill_count += 1
                            # Record skill decision for audit trail
                            self._record_skill_decision(pattern, "promoted")

            # Step 2: Archive stale skills (low evidence, old)
            archived = self._archive_stale_skills()
            if archived > 0:
                logger.info(f"Archived {archived} stale skills")

            # Step 3: Generate agents for complex patterns
            if agent_candidates:
                agent_gen = AgentGenerator(
                    str(self.project_path),
                    self.m27,
                    project_memory=self._pm,
                )

                for pattern in agent_candidates:
                    if detector.should_create_agent(pattern):
                        # Check cap enforcement and evidence threshold before creating
                        can_create, reason = agent_gen.can_create_agent(pattern.pattern)
                        if can_create:
                            agent_path = agent_gen.generate_agent(
                                pattern,
                                pattern.semantically_related_issues,
                            )
                            if agent_path:
                                # Write agent ref to AGENT.md for backward compat
                                self.memory_manager.add_agent_reference(
                                    agent_gen._pattern_to_agent_name(pattern.pattern),
                                    agent_path,
                                )
                                agent_count += 1
                                # Record agent decision for audit trail
                                self._record_agent_decision(pattern, "promoted", agent_path)
                        else:
                            # Record why agent was not created
                            self._record_agent_decision(pattern, f"rejected: {reason}", None)

            # Return skill and agent counts
            return skill_count, agent_count
        except Exception as e:
            logger.warning(f"Skill/agent generation failed: {e}")
            return 0, 0

    def _record_skill_decision(self, pattern: Any, decision: str) -> None:
        """Record a skill decision in memory_decisions for audit trail.

        Args:
            pattern: PatternCluster with pattern info
            decision: Decision made (promoted, revised, retained, archived, rejected)
        """
        if self._pm is None:
            return
        try:
            evidence_json = json.dumps(
                {
                    "occurrences": getattr(pattern, "occurrences", 0),
                    "confidence": getattr(pattern, "confidence", 0.0),
                    "files": list(getattr(pattern, "files", []))[:5],
                    "severity_counts": getattr(pattern, "severity_counts", {}),
                }
            )
            reasoning = (
                f"Skill decision: {decision}. "
                f"Pattern: {getattr(pattern, 'pattern', 'unknown')}, "
                f"occurrences: {getattr(pattern, 'occurrences', 0)}, "
                f"confidence: {getattr(pattern, 'confidence', 0.0):.2f}. "
                f"Evidence from memory_decisions table."
            )
            # skill_id is 0 for decisions not tied to a specific skill yet
            self._pm.record_skill_decision(
                project_path=str(self.project_path),
                skill_id=0,
                reasoning=reasoning,
                evidence_json=evidence_json,
            )
        except Exception as e:
            logger.debug(f"Could not record skill decision: {e}")

    def _record_agent_decision(self, pattern: Any, decision: str, agent_path: str | None) -> None:
        """Record an agent decision in memory_decisions for audit trail.

        Args:
            pattern: PatternCluster with pattern info
            decision: Decision made (promoted, revised, retained, archived, rejected: <reason>)
            agent_path: Path to agent file if created
        """
        if self._pm is None:
            return
        try:
            evidence_json = json.dumps(
                {
                    "occurrences": getattr(pattern, "occurrences", 0),
                    "confidence": getattr(pattern, "confidence", 0.0),
                    "files": list(getattr(pattern, "files", []))[:5],
                    "severity_counts": getattr(pattern, "severity_counts", {}),
                    "agent_path": agent_path,
                }
            )
            reasoning = (
                f"Agent decision: {decision}. "
                f"Pattern: {getattr(pattern, 'pattern', 'unknown')}, "
                f"occurrences: {getattr(pattern, 'occurrences', 0)}, "
                f"confidence: {getattr(pattern, 'confidence', 0.0):.2f}. "
                f"Evidence from memory_decisions table."
            )
            # agent_id is 0 for rejected decisions
            self._pm.record_agent_decision(
                project_path=str(self.project_path),
                agent_id=0,
                decision_type="create_agent",
                reasoning=reasoning,
                evidence_json=evidence_json,
            )
        except Exception as e:
            logger.debug(f"Could not record agent decision: {e}")

    def _publish_active_specializations(
        self,
        critical_rules: list[dict[str, Any]] | None = None,
    ) -> None:
        """Publish active skills and agents to root CLAUDE.md (DB-first).

        Reads active skills and agents from project_memory.db and passes them
        to ClaudePublisher for marker-based publishing.

        This ensures root CLAUDE.md always reflects the current DB-backed state.
        """
        try:
            # Read active skills from DB
            active_skills = self._pm.list_skills(
                project_path=str(self.project_path),
                status="active",
                limit=50,
            )
            skill_calls = [
                {
                    "skill_name": s.get("name", ""),
                    "path": s.get("file_path", ""),
                    "use_count": s.get("evidence_count", 0),
                }
                for s in active_skills
                if s.get("file_path")
            ]

            # Read active agents from DB
            active_agents = self._pm.list_agents(
                project_path=str(self.project_path),
                status="active",
                limit=50,
            )
            agent_calls = [
                {
                    "agent_name": a.get("name", ""),
                    "path": a.get("file_path", ""),
                    "use_count": a.get("use_count", 0),
                }
                for a in active_agents
                if a.get("file_path")
            ]

            # Publish once with the final combined state so later sections do not
            # overwrite rules that were promoted earlier in the same review.
            if critical_rules or skill_calls or agent_calls:
                self._publisher.publish(
                    critical_rules=critical_rules if critical_rules else None,
                    skill_calls=skill_calls if skill_calls else None,
                    agent_calls=agent_calls if agent_calls else None,
                )
        except Exception as e:
            logger.debug(f"Could not publish active specializations: {e}")

    def _archive_stale_skills(self) -> int:
        """Archive active skills with low evidence_count (DB-first lifecycle rule).

        Skills are stale if they have low evidence_count relative to their age.
        This keeps the skills directory concise and prevents append-only bloat.
        """
        try:
            stale = self._pm.get_stale_skills(
                str(self.project_path),
                evidence_threshold=3,
                lookback_days=30,
            )
            archived = 0
            for skill in stale:
                skill_path = skill.get("file_path")
                if skill_path:
                    generator = SkillGenerator(
                        str(self.project_path),
                        project_memory=self._pm,
                    )
                    generator.archive_skill(
                        Path(skill_path),
                        reason=f"Stale: evidence_count={skill.get('evidence_count', 0)}",
                    )
                    archived += 1
            if archived > 0:
                logger.info(f"Archived {archived} stale skills")
            return archived
        except Exception as e:
            logger.debug(f"Could not archive stale skills: {e}")
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
