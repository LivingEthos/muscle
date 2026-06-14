"""
GitHub Integration - High-level GitHub integration for MUSCLE reviews.

Ties together GitHub adapter with review workflow for:
- Creating PRs with fixes
- Posting review comments
- Creating issues for unfixed issues
- Status checks for review gate

Architecture Decision Record (ADR):
- Non-blocking integration (doesn't fail review if GitHub is unavailable)
- Formats review results as GitHub-native artifacts
- Supports both commit-level and PR-level workflows
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..code_review.types import ReviewResult
from .github import GitHubAdapter

logger = logging.getLogger(__name__)


@dataclass
class GitHubIntegrationConfig:
    enabled: bool = False
    create_prs: bool = True
    create_issues: bool = True
    post_comments: bool = True
    require_review_gate: bool = False
    auto_merge: bool = False


class GitHubIntegration:
    def __init__(
        self,
        project_path: str,
        config: GitHubIntegrationConfig | None = None,
        github_adapter: GitHubAdapter | None = None,
    ):
        self.project_path = Path(project_path)
        self.config = config or GitHubIntegrationConfig()
        self.github = github_adapter or GitHubAdapter()
        self._check_run_id: int | None = None

    def post_review_as_check(self, review_result: ReviewResult, head_sha: str) -> bool:
        """Post review as a GitHub check run."""
        if not self.config.enabled:
            return False

        try:
            conclusion = self._get_check_conclusion(review_result)
            output = self._format_review_output(review_result)

            check_run = self.github.create_check_run(
                name="muscle-review",
                head_sha=head_sha,
                status="completed",
                conclusion=conclusion,
                output=output,
            )

            if check_run:
                self._check_run_id = check_run.get("id")
                logger.info(f"Created check run {self._check_run_id}")
                return True

            return False
        except Exception as e:
            logger.error(f"Failed to post review as check: {e}")
            return False

    def _get_check_conclusion(self, review_result: ReviewResult) -> str:
        if review_result.critical_count > 0 or review_result.high_count > 0:
            return "failure"
        elif review_result.medium_count > 0:
            return "neutral"
        return "success"

    def _format_review_output(self, review_result: ReviewResult) -> dict:
        summary = [
            "## MUSCLE Code Review",
            "",
            f"**Files reviewed:** {review_result.files_reviewed}",
            f"**Lines reviewed:** {review_result.lines_reviewed}",
            "",
            "### Issues Found",
            f"- 🔴 Critical: {review_result.critical_count}",
            f"- 🟠 High: {review_result.high_count}",
            f"- 🟡 Medium: {review_result.medium_count}",
            f"- 🟢 Low: {review_result.low_count}",
            f"- 🔵 Info: {review_result.info_count}",
            "",
        ]

        if review_result.fixed_issues:
            summary.append(f"### Auto-fixed Issues: {len(review_result.fixed_issues)}")

        if review_result.unfixed_issues:
            summary.append(f"### Unfixed Issues: {len(review_result.unfixed_issues)}")
            for issue in review_result.unfixed_issues[:5]:
                summary.append(f"- `{issue.file_path}:{issue.line_number}` {issue.title}")

        if review_result.critical_count > 0 or review_result.high_count > 0:
            summary.append("")
            summary.append("⚠️ **Review gate blocked** - Critical/High issues must be addressed")

        return {
            "title": f"MUSCLE Review: {review_result.files_reviewed} files",
            "summary": "\n".join(summary),
        }

    def create_fix_pr(
        self,
        review_result: ReviewResult,
        branch_name: str = "muscle/fixes",
        base_branch: str = "main",
    ) -> dict | None:
        """Create a PR with auto-fixed issues."""
        if not self.config.enabled or not self.config.create_prs:
            return None

        if not review_result.fixed_issues:
            logger.info("No fixed issues to create PR for")
            return None

        try:
            fixes_content = self._format_fixes_markdown(review_result)

            pr_body = self._format_pr_body(review_result, fixes_content)

            pr = self.github.create_pull_request(
                title=f"fix: MUSCLE auto-fixes ({len(review_result.fixed_issues)} issues)",
                body=pr_body,
                head=branch_name,
                base=base_branch,
            )

            if pr:
                logger.info(f"Created fix PR #{pr.get('number')}")
                return pr

            return None
        except Exception as e:
            logger.error(f"Failed to create fix PR: {e}")
            return None

    def _format_fixes_markdown(self, review_result: ReviewResult) -> str:
        fixes = ["### Auto-Fixed Issues\n"]
        for issue in review_result.fixed_issues:
            fixes.append(f"**{issue.file_path}:{issue.line_number}** - {issue.title}")
            if issue.suggested_fix:
                fixes.append(f"```\n{issue.suggested_fix}\n```")
            fixes.append("")
        return "\n".join(fixes)

    def _format_pr_body(self, review_result: ReviewResult, fixes_content: str) -> str:
        return f"""## MUSCLE Auto-Fix PR

This PR contains {len(review_result.fixed_issues)} auto-fixed issues found by MUSCLE.

### Summary
| Severity | Count |
|----------|-------|
| Critical | {review_result.critical_count} |
| High | {review_result.high_count} |
| Medium | {review_result.medium_count} |
| Low | {review_result.low_count} |

{fixes_content}

---
*Generated by MUSCLE on {datetime.now().isoformat()}*"""

    def post_review_comment(self, pr_number: int, review_result: ReviewResult) -> bool:
        """Post review summary as PR comment."""
        if not self.config.enabled or not self.config.post_comments:
            return False

        try:
            comment_body = self._format_review_output(review_result)["summary"]

            result = self.github.create_review(
                pr_number=pr_number,
                body=comment_body,
                event="COMMENT",
            )

            if result:
                logger.info(f"Posted review comment on PR #{pr_number}")
                return True

            return False
        except Exception as e:
            logger.error(f"Failed to post review comment: {e}")
            return False

    def create_issues_for_unfixed(
        self,
        review_result: ReviewResult,
        assignees: list[str] | None = None,
    ) -> list[dict]:
        """Create GitHub issues for unfixed critical/high issues."""
        if not self.config.enabled or not self.config.create_issues:
            return []

        issues_created = []

        for issue in review_result.unfixed_issues:
            if issue.severity.value >= 4:
                try:
                    issue_body = f"""## MUSCLE Issue: {issue.title}

**File:** `{issue.file_path}:{issue.line_number}`
**Severity:** {issue.severity.name}
**Category:** {issue.category.value}

### Description
{issue.description}

### Code Snippet
```
{issue.code_snippet}
```

### Suggested Fix
{issue.suggested_fix or "_No auto-fix available_"}

---
*Created by MUSCLE on {datetime.now().isoformat()}*"""

                    gh_issue = self.github.create_issue(
                        title=f"[{issue.severity.name}] {issue.title}",
                        body=issue_body,
                        labels=["muscle", issue.category.value],
                        assignees=assignees,
                    )

                    if gh_issue:
                        issues_created.append(gh_issue)
                        logger.info(f"Created issue #{gh_issue.get('number')}: {issue.title}")

                except Exception as e:
                    logger.error(f"Failed to create issue for {issue.title}: {e}")

        return issues_created

    def update_review_status(
        self,
        review_result: ReviewResult,
        status: str,
        conclusion: str | None = None,
    ) -> bool:
        """Update the check run status."""
        if not self.config.enabled or self._check_run_id is None:
            return False

        try:
            kwargs: dict = {"status": status}
            if conclusion:
                kwargs["conclusion"] = conclusion
            if status == "completed":
                kwargs["output"] = self._format_review_output(review_result)

            result = self.github.update_check_run(self._check_run_id, **kwargs)
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update check run: {e}")
            return False

    def should_block_merge(self, review_result: ReviewResult) -> bool:
        """Check if review should block merge based on severity."""
        if not self.config.require_review_gate:
            return False

        return review_result.critical_count > 0 or review_result.high_count > 0
