"""
GitHub adapter for MUSCLE.

Provides integration with GitHub Actions, PR reviews, and webhooks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .http_utils import DEFAULT_HTTP_TIMEOUT_SECONDS, request_with_retries

logger = logging.getLogger(__name__)


class GitHubAdapter:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY")
        self.api_base = "https://api.github.com"
        self.timeout_seconds = DEFAULT_HTTP_TIMEOUT_SECONDS

    def _get_headers(self) -> dict:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        draft: bool = False,
    ) -> dict | None:
        if not self.repo:
            logger.warning("GITHUB_REPOSITORY not set")
            return None

        url = f"{self.api_base}/repos/{self.repo}/pulls"

        data = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }

        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        else:
            logger.error(f"Failed to create PR: {response.status_code} - {response.text}")
            return None

    def get_branch_sha(self, branch: str) -> str | None:
        """Get the current commit SHA for a branch."""
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/git/ref/heads/{branch}"
        response = request_with_retries(
            requests,
            "GET",
            url,
            headers=self._get_headers(),
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        sha = data.get("object", {}).get("sha")
        return str(sha) if isinstance(sha, str) else None

    def create_branch(self, branch: str, from_branch: str = "main") -> dict[str, Any] | None:
        """Create a branch ref from an existing branch if it does not already exist."""
        if not self.repo:
            return None

        existing_sha = self.get_branch_sha(branch)
        if existing_sha:
            return {"ref": f"refs/heads/{branch}", "object": {"sha": existing_sha}}

        base_sha = self.get_branch_sha(from_branch)
        if not base_sha:
            logger.error("Could not resolve base branch SHA for %s", from_branch)
            return None

        url = f"{self.api_base}/repos/{self.repo}/git/refs"
        data = {"ref": f"refs/heads/{branch}", "sha": base_sha}
        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        if response.status_code == 422:
            return {"ref": f"refs/heads/{branch}", "object": {"sha": base_sha}}
        logger.error(
            "Failed to create branch %s: %s - %s", branch, response.status_code, response.text
        )
        return None

    def get_pull_request(self, pr_number: int) -> dict | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/pulls/{pr_number}"
        response = request_with_retries(
            requests,
            "GET",
            url,
            headers=self._get_headers(),
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None

    def create_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> dict | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/pulls/{pr_number}/reviews"

        data = {
            "body": body,
            "event": event,
        }

        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None

    def create_check_run(
        self,
        name: str,
        head_sha: str,
        status: str = "in_progress",
        conclusion: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/check-runs"

        data: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
        }

        if conclusion:
            data["conclusion"] = conclusion
        if output:
            data["output"] = output

        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        return None

    def update_check_run(self, check_run_id: int, **kwargs: Any) -> dict[str, Any] | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/check-runs/{check_run_id}"

        response = request_with_retries(
            requests,
            "PATCH",
            url,
            headers=self._get_headers(),
            json=kwargs,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None

    def get_file_content(self, path: str, ref: str = "main") -> str | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/contents/{path}"

        response = request_with_retries(
            requests,
            "GET",
            url,
            headers=self._get_headers(),
            params={"ref": ref},
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            import base64

            data = response.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8")
        return None

    def get_file_metadata(self, path: str, ref: str = "main") -> dict[str, Any] | None:
        """Return GitHub contents API metadata for one path."""
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/contents/{path}"
        response = request_with_retries(
            requests,
            "GET",
            url,
            headers=self._get_headers(),
            params={"ref": ref},
            timeout=self.timeout_seconds,
        )
        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, dict) else None
        return None

    def create_commit(
        self,
        path: str,
        message: str,
        content: str,
        branch: str = "main",
    ) -> dict[str, Any] | None:
        if not self.repo:
            return None

        import base64

        url = f"{self.api_base}/repos/{self.repo}/contents/{path}"

        data: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }

        response = request_with_retries(
            requests,
            "PUT",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code in [200, 201]:
            return response.json()  # type: ignore[no-any-return]
        if response.status_code == 422:
            existing = self.get_file_metadata(path, ref=branch)
            sha = existing.get("sha") if isinstance(existing, dict) else None
            if isinstance(sha, str) and sha:
                data["sha"] = sha
                response = request_with_retries(
                    requests,
                    "PUT",
                    url,
                    headers=self._get_headers(),
                    json=data,
                    timeout=self.timeout_seconds,
                )
                if response.status_code in [200, 201]:
                    return response.json()  # type: ignore[no-any-return]
        return None

    def download_artifact(self, artifact_id: int) -> bytes | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/actions/artifacts/{artifact_id}/zip"

        response = request_with_retries(
            requests,
            "GET",
            url,
            headers=self._get_headers(),
            allow_redirects=True,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            return response.content
        return None

    def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict | None:
        if not self.repo:
            logger.warning("GITHUB_REPOSITORY not set")
            return None

        url = f"{self.api_base}/repos/{self.repo}/issues"

        data: dict[str, Any] = {
            "title": title,
            "body": body,
        }

        if labels:
            data["labels"] = labels
        if assignees:
            data["assignees"] = assignees

        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        else:
            logger.error(f"Failed to create issue: {response.status_code} - {response.text}")
            return None

    def create_issue_comment(self, issue_number: int, body: str) -> dict | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/issues/{issue_number}/comments"

        data = {"body": body}

        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        return None

    def add_labels(self, issue_number: int, labels: list[str]) -> dict | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/issues/{issue_number}/labels"

        data = {"labels": labels}

        response = request_with_retries(
            requests,
            "POST",
            url,
            headers=self._get_headers(),
            json=data,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None
