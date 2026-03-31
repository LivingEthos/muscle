"""
GitHub adapter for SCLE.

Provides integration with GitHub Actions, PR reviews, and webhooks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


class GitHubAdapter:
    def __init__(self, token: str | None = None, repo: str | None = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY")
        self.api_base = "https://api.github.com"

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
        }

        response = requests.post(url, headers=self._get_headers(), json=data)

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        else:
            logger.error(f"Failed to create PR: {response.status_code} - {response.text}")
            return None

    def get_pull_request(self, pr_number: int) -> dict | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/pulls/{pr_number}"
        response = requests.get(url, headers=self._get_headers())

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

        response = requests.post(url, headers=self._get_headers(), json=data)

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

        response = requests.post(url, headers=self._get_headers(), json=data)

        if response.status_code == 201:
            return response.json()  # type: ignore[no-any-return]
        return None

    def update_check_run(self, check_run_id: int, **kwargs: Any) -> dict[str, Any] | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/check-runs/{check_run_id}"

        response = requests.patch(url, headers=self._get_headers(), json=kwargs)

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None

    def get_file_content(self, path: str, ref: str = "main") -> str | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/contents/{path}"

        response = requests.get(url, headers=self._get_headers(), params={"ref": ref})

        if response.status_code == 200:
            import base64

            data = response.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8")
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

        response = requests.put(url, headers=self._get_headers(), json=data)

        if response.status_code in [200, 201]:
            return response.json()  # type: ignore[no-any-return]
        return None

    def download_artifact(self, artifact_id: int) -> bytes | None:
        if not self.repo:
            return None

        url = f"{self.api_base}/repos/{self.repo}/actions/artifacts/{artifact_id}/zip"

        response = requests.get(url, headers=self._get_headers(), allow_redirects=True)

        if response.status_code == 200:
            return response.content
        return None
