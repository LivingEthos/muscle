"""
GitLab adapter for MUSCLE.

Provides integration with GitLab CI/CD and Merge Requests.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from .http_utils import DEFAULT_HTTP_TIMEOUT_SECONDS, request_with_retries

logger = logging.getLogger(__name__)


class GitLabAdapter:
    def __init__(
        self,
        token: str | None = None,
        project_id: str | None = None,
        base_url: str | None = None,
    ):
        self.token = token or os.environ.get("GITLAB_TOKEN")
        self.project_id = project_id or os.environ.get("CI_PROJECT_ID")
        self.base_url = base_url or os.environ.get("CI_API_V4_URL", "https://gitlab.com/api/v4")
        self.timeout_seconds = DEFAULT_HTTP_TIMEOUT_SECONDS

    def _get_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        return headers

    def create_merge_request(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict | None:
        if not self.project_id:
            logger.warning("CI_PROJECT_ID not set")
            return None

        url = f"{self.base_url}/projects/{self.project_id}/merge_requests"

        data = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
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
            logger.error(f"Failed to create MR: {response.status_code} - {response.text}")
            return None

    def get_merge_request(self, mr_iid: int) -> dict | None:
        if not self.project_id:
            return None

        url = f"{self.base_url}/projects/{self.project_id}/merge_requests/{mr_iid}"

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

    def create_note(
        self,
        mr_iid: int,
        body: str,
    ) -> dict | None:
        if not self.project_id:
            return None

        url = f"{self.base_url}/projects/{self.project_id}/merge_requests/{mr_iid}/notes"

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

    def create_pipeline(
        self,
        ref: str,
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        if not self.project_id:
            return None

        url = f"{self.base_url}/projects/{self.project_id}/pipeline"

        data: dict[str, Any] = {"ref": ref}
        if variables:
            data["variables"] = [{"key": k, "value": v} for k, v in variables.items()]

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

    def get_pipeline_status(self, pipeline_id: int) -> str | None:
        if not self.project_id:
            return None

        url = f"{self.base_url}/projects/{self.project_id}/pipelines/{pipeline_id}"

        response = request_with_retries(
            requests,
            "GET",
            url,
            headers=self._get_headers(),
            timeout=self.timeout_seconds,
        )

        if response.status_code == 200:
            return response.json().get("status")  # type: ignore[no-any-return]
        return None

    def create_job(
        self,
        job_name: str,
        variables: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        if not self.project_id:
            return None

        url = f"{self.base_url}/projects/{self.project_id}/jobs"

        data: dict[str, Any] = {
            "name": job_name,
            "variables": [{"key": k, "value": v} for k, v in (variables or {}).items()],
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
        return None

    def download_artifact(
        self,
        job_id: int,
        artifact_path: str,
    ) -> bytes | None:
        if not self.project_id:
            return None

        url = f"{self.base_url}/projects/{self.project_id}/jobs/{job_id}/artifacts/{artifact_path}"

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
