"""
LearningIngestor - Writes structured learning evidence to the project memory database.

Architecture Decision Record (ADR):
- Separates DB write concerns from ReviewController and CLI
- Accepts ProjectMemory as a dependency for testability
- Handles optional fields gracefully
- Supports both successful and failed outcomes

This service is called after reviews and tasks complete to record:
- Task runs to `tasks` table
- Review runs to `review_runs` table
- Findings to `review_findings` table
- Session metadata and outcome links
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .code_review.types import ReviewIssue, ReviewResult
from .project_memory_types import (
    TaskStatus,
)

if TYPE_CHECKING:
    from .project_memory import ProjectMemory

logger = logging.getLogger(__name__)


class LearningIngestor:
    """Service that writes task and review evidence to the project memory DB."""

    def __init__(self, project_memory: ProjectMemory):
        """
        Initialize the LearningIngestor with a ProjectMemory instance.

        Args:
            project_memory: The ProjectMemory database access layer.
        """
        self._pm = project_memory

    # -------------------------------------------------------------------------
    # Task ingestion
    # -------------------------------------------------------------------------

    def write_task_run(
        self,
        project_path: str,
        title: str,
        description: str,
        status: TaskStatus,
        outcome: str | None = None,
        token_cost: int = 0,
        duration_ms: int = 0,
        task_id: int | None = None,
    ) -> int | None:
        """
        Write a task run record to the `tasks` table.

        Args:
            project_path: Absolute path to the project.
            title: Task title.
            description: Task description.
            status: Current TaskStatus.
            outcome: Optional outcome message (e.g. error string on failure).
            token_cost: Token cost of the task.
            duration_ms: Duration in milliseconds.
            task_id: Optional existing task ID to link this run to.

        Returns:
            The row ID of the inserted record, or None on failure.
        """
        try:
            return self._pm.insert_task(
                project_path=project_path,
                created_at=datetime.now().isoformat(),
                title=title,
                description=description,
                status=status.value,
                outcome=outcome,
                token_cost=token_cost,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning(f"Failed to write task run: {e}")
            return None

    # -------------------------------------------------------------------------
    # Review ingestion
    # -------------------------------------------------------------------------

    def write_review_run(
        self,
        project_path: str,
        review_mode: str,
        target_path: str,
        findings_count: int = 0,
        token_cost: int = 0,
        duration_ms: int = 0,
    ) -> int | None:
        """
        Write a review run record to the `review_runs` table.

        Args:
            project_path: Absolute path to the project.
            review_mode: Review mode string (e.g. "review", "auto_fix").
            target_path: Path that was reviewed.
            findings_count: Number of findings produced.
            token_cost: Token cost of the review.
            duration_ms: Duration in milliseconds.

        Returns:
            The row ID of the inserted record, or None on failure.
        """
        try:
            return self._pm.insert_review_run(
                project_path=project_path,
                review_mode=review_mode,
                target_path=target_path,
                findings_count=findings_count,
                token_cost=token_cost,
                duration_ms=duration_ms,
                created_at=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.warning(f"Failed to write review run: {e}")
            return None

    def write_findings(
        self,
        review_run_id: int,
        issues: list[ReviewIssue],
        fix_results: dict[int, bool] | None = None,
    ) -> int:
        """
        Write review findings to the `review_findings` table.

        Args:
            review_run_id: The review_run_id to link findings to.
            issues: List of ReviewIssue objects from the review.
            fix_results: Optional dict mapping issue index to whether fix was applied.

        Returns:
            Number of findings written.
        """
        finding_ids = self.write_findings_with_ids(review_run_id, issues, fix_results)
        return sum(1 for finding_id in finding_ids if finding_id is not None)

    def write_findings_with_ids(
        self,
        review_run_id: int,
        issues: list[ReviewIssue],
        fix_results: dict[int, bool] | None = None,
    ) -> list[int | None]:
        """
        Write review findings and return the inserted IDs aligned to the input order.

        Args:
            review_run_id: The review_run_id to link findings to.
            issues: List of ReviewIssue objects from the review.
            fix_results: Optional dict mapping issue index to whether fix was applied.

        Returns:
            List of inserted finding IDs aligned to `issues`. Failed writes return `None`.
        """
        fix_results = fix_results or {}
        finding_ids: list[int | None] = []

        for idx, issue in enumerate(issues):
            try:
                rule_id = self._issue_to_rule_id(issue)
                finding_id = self._pm.insert_review_finding(
                    review_run_id=review_run_id,
                    rule_id=rule_id,
                    severity=issue.severity.name,
                    file_path=issue.file_path,
                    line_number=issue.line_number,
                    message=issue.description,
                    auto_fixable=issue.auto_fixable,
                    fix_applied=fix_results.get(idx, False),
                    outcome=None,
                )
                finding_ids.append(finding_id)
            except Exception as e:
                logger.warning(f"Failed to write finding: {e}")
                finding_ids.append(None)

        return finding_ids

    def _issue_to_rule_id(self, issue: ReviewIssue) -> str:
        """Derive a stable rule ID from a ReviewIssue."""
        # Use CWE if available, otherwise derive from title + file + line
        if issue.cwe_id:
            return issue.cwe_id
        # Generate a stable ID from title words
        words = issue.title.lower().split()[:3]
        safe_words = "".join(c if c.isalnum() else "_" for c in " ".join(words))
        return f"gen_{safe_words[:32]}"

    # -------------------------------------------------------------------------
    # Session metadata and outcome linking
    # -------------------------------------------------------------------------

    def link_session_outcome(
        self,
        session_id: str,
        project_path: str,
        success: bool,
        outcome_message: str | None = None,
        task_id: int | None = None,
    ) -> None:
        """
        Write session metadata linking a task to its outcome.

        This is called after a session completes to record whether it succeeded
        or failed, along with any error message.

        Args:
            session_id: The session ID.
            project_path: Absolute path to the project.
            success: Whether the session completed successfully.
            outcome_message: Optional message (e.g. error string).
            task_id: Optional task ID to update with the outcome.
        """
        try:
            outcome = (
                "success"
                if success
                else f"failed: {outcome_message}"
                if outcome_message
                else "failed"
            )
            if task_id is not None:
                self._pm.update_task_outcome(task_id, outcome)
        except Exception as e:
            logger.warning(f"Failed to link session outcome: {e}")

    # -------------------------------------------------------------------------
    # High-level ingest methods (composite operations)
    # -------------------------------------------------------------------------

    def ingest_review_result(
        self,
        review_result: ReviewResult,
        project_path: str,
        review_mode: str,
        token_cost: int = 0,
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        """
        Ingest a full review result into the DB.

        This writes the review run, all findings, and returns a summary.

        Args:
            review_result: The ReviewResult from the review.
            project_path: Absolute path to the project.
            review_mode: The review mode used.
            token_cost: Token cost of the review.
            duration_ms: Duration in milliseconds.

        Returns:
            Dict with keys: review_run_id, findings_written, task_id (None).
        """
        # Write review run
        review_run_id = self.write_review_run(
            project_path=project_path,
            review_mode=review_mode,
            target_path=review_result.target_path,
            findings_count=len(review_result.issues),
            token_cost=token_cost,
            duration_ms=duration_ms,
        )

        if review_run_id is None:
            logger.warning("Failed to write review run, skipping findings")
            return {"review_run_id": None, "findings_written": 0, "task_id": None}

        # Write findings
        fix_results = self._build_fix_results(review_result)
        findings_written = self.write_findings(review_run_id, review_result.issues, fix_results)

        return {
            "review_run_id": review_run_id,
            "findings_written": findings_written,
            "task_id": None,
        }

    def _build_fix_results(self, review_result: ReviewResult) -> dict[int, bool]:
        """Build a dict of issue index -> fix_applied from ReviewResult."""
        result: dict[int, bool] = {}
        for idx, issue in enumerate(review_result.issues):
            result[idx] = issue in review_result.fixed_issues
        return result

    def ingest_failed_review(
        self,
        project_path: str,
        review_mode: str,
        target_path: str,
        error_message: str,
        token_cost: int = 0,
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        """
        Ingest a failed review run (no results produced).

        Args:
            project_path: Absolute path to the project.
            review_mode: The review mode used.
            target_path: The path that was reviewed.
            error_message: Error message describing the failure.
            token_cost: Token cost incurred before failure.
            duration_ms: Duration in milliseconds.

        Returns:
            Dict with keys: review_run_id, findings_written, task_id.
        """
        review_run_id = self.write_review_run(
            project_path=project_path,
            review_mode=review_mode,
            target_path=target_path,
            findings_count=0,
            token_cost=token_cost,
            duration_ms=duration_ms,
        )

        return {
            "review_run_id": review_run_id,
            "findings_written": 0,
            "task_id": None,
        }

    # -------------------------------------------------------------------------
    # Correction signal ingestion (MUS-023)
    # -------------------------------------------------------------------------

    def write_correction_signal(
        self,
        project_path: str,
        correction_type: str,
        source_table: str,
        source_id: int,
        severity: str | None = None,
        file_path: str | None = None,
        line_number: int | None = None,
        rule_id: str | None = None,
        description: str | None = None,
        review_run_id: int | None = None,
    ) -> int | None:
        """
        Write a correction signal to the memory_decisions table.

        Records when:
        - An auto-fix fails verification (fix_failed)
        - A proposed fix is rejected/dismissed by user (fix_rejected)
        - A supposedly fixed pattern recurs (recurrence)

        Args:
            project_path: Absolute path to the project.
            correction_type: One of 'fix_failed', 'fix_rejected', 'recurrence'.
            source_table: Table the source record lives in (e.g. 'review_findings').
            source_id: ID of the source record.
            severity: Severity of the original finding (e.g. 'HIGH', 'MEDIUM').
            file_path: File path of the issue.
            line_number: Line number of the issue.
            rule_id: Rule/pattern ID of the issue.
            description: Human-readable description of the issue.
            review_run_id: Optional review run ID to link to.

        Returns:
            The row ID of the inserted record, or None on failure.
        """
        import json

        evidence: dict[str, Any] = {
            "correction_type": correction_type,
        }
        if severity:
            evidence["severity"] = severity
        if file_path:
            evidence["file_path"] = file_path
        if line_number is not None:
            evidence["line_number"] = line_number
        if rule_id:
            evidence["rule_id"] = rule_id
        if description:
            evidence["description"] = description
        if review_run_id is not None:
            evidence["review_run_id"] = review_run_id

        # Score: 1.0 for fix_failed/fix_rejected, lower for recurrence
        score: dict[str, Any] = {"quality": 1.0}
        if correction_type == "recurrence":
            score["quality"] = 0.5  # Lower score indicates pattern not resolved
        elif correction_type == "fix_failed":
            score["quality"] = 0.8

        reasoning = f"Correction signal: {correction_type}"
        if rule_id:
            reasoning += f" for rule {rule_id}"
        if file_path and line_number:
            reasoning += f" at {file_path}:{line_number}"

        try:
            return self._pm.insert_decision(
                project_path=project_path,
                decision_type="correction_signal",
                source_table=source_table,
                source_id=source_id,
                evidence_json=json.dumps(evidence),
                score_json=json.dumps(score),
                reasoning=reasoning,
            )
        except Exception as e:
            logger.warning(f"Failed to write correction signal: {e}")
            return None

    def detect_and_record_recurrence(
        self,
        project_path: str,
        current_review_run_id: int,
        issues: list[ReviewIssue],
    ) -> list[int]:
        """
        Detect when a pattern recurs after being supposedly fixed.

        Compares current findings against history of previously fixed issues.
        If the same rule_id appears at the same location after being marked
        as fixed, records a recurrence signal.

        Args:
            project_path: Absolute path to the project.
            current_review_run_id: ID of the current review run.
            issues: List of current ReviewIssue objects.

        Returns:
            List of memory_decisions row IDs for recurrence signals written.
        """
        recorded_ids: list[int] = []

        for issue in issues:
            rule_id = self._issue_to_rule_id(issue)

            # Check if this rule_id was previously fixed at the same location
            try:
                conn = self._pm._get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT rf.id, rf.file_path, rf.line_number, rf.severity,
                           fa.verification_passed, fa.created_at
                    FROM review_findings rf
                    JOIN fix_attempts fa ON fa.finding_id = rf.id
                    WHERE rf.rule_id = ?
                      AND rf.file_path = ?
                      AND rf.line_number = ?
                      AND fa.verification_passed = 1
                    ORDER BY fa.created_at DESC
                    LIMIT 1
                    """,
                    (rule_id, issue.file_path, issue.line_number),
                )
                row = cursor.fetchone()
                conn.close()

                if row:
                    # Found a previously fixed issue at same location
                    signal_id = self.write_correction_signal(
                        project_path=project_path,
                        correction_type="recurrence",
                        source_table="review_findings",
                        source_id=row["id"],
                        severity=issue.severity.name,
                        file_path=issue.file_path,
                        line_number=issue.line_number,
                        rule_id=rule_id,
                        description=issue.description,
                        review_run_id=current_review_run_id,
                    )
                    if signal_id:
                        recorded_ids.append(signal_id)
                        logger.debug(
                            f"Recorded recurrence for rule_id={rule_id} "
                            f"at {issue.file_path}:{issue.line_number}"
                        )
            except Exception as e:
                logger.warning(f"Recurrence detection failed: {e}")

        return recorded_ids
