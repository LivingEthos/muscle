"""
Jenkins adapter for SCLE.

Provides integration with Jenkins CI/CD pipelines.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


class JenkinsAdapter:
    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        token: str | None = None,
    ):
        self.url = url or os.environ.get("JENKINS_URL")
        self.username = username or os.environ.get("JENKINS_USER")
        self.token = token or os.environ.get("JENKINS_TOKEN")
        self.session = requests.Session()
        self._authenticate()

    def _authenticate(self) -> None:
        if self.username and self.token:
            auth = base64.b64encode(f"{self.username}:{self.token}".encode()).decode()
            self.session.headers.update({"Authorization": f"Basic {auth}"})

    def get_job_info(self, job_name: str) -> dict[str, Any] | None:
        if not self.url:
            return None

        url = f"{self.url}/job/{job_name}/api/json"

        response = self.session.get(url)

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None

    def get_build_info(self, job_name: str, build_number: int) -> dict[str, Any] | None:
        if not self.url:
            return None

        url = f"{self.url}/job/{job_name}/{build_number}/api/json"

        response = self.session.get(url)

        if response.status_code == 200:
            return response.json()  # type: ignore[no-any-return]
        return None

    def get_build_console_output(self, job_name: str, build_number: int) -> str | None:
        if not self.url:
            return None

        url = f"{self.url}/job/{job_name}/{build_number}/consoleText"

        response = self.session.get(url)

        if response.status_code == 200:
            return response.text
        return None

    def trigger_build(
        self,
        job_name: str,
        parameters: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> int | None:
        if not self.url:
            return None

        if parameters:
            url = f"{self.url}/job/{job_name}/buildWithParameters"
            data: dict[str, Any] = parameters
        else:
            url = f"{self.url}/job/{job_name}/build"
            data = {}

        if token:
            url += f"?token={token}"

        response = self.session.post(url, data=data)

        if response.status_code in [200, 201]:
            queue_url = response.headers.get("Location", "")
            if queue_url:
                return self._get_build_number_from_queue(queue_url)

        logger.error(f"Failed to trigger build: {response.status_code}")
        return None

    def _get_build_number_from_queue(self, queue_url: str) -> int | None:
        response = self.session.get(queue_url + "/api/json")
        if response.status_code == 200:
            return response.json().get("number")  # type: ignore[no-any-return]
        return None

    def wait_for_build(
        self,
        job_name: str,
        build_number: int,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> str | None:
        import time

        start_time = time.time()

        while time.time() - start_time < timeout:
            build_info = self.get_build_info(job_name, build_number)
            if build_info:
                phase = build_info.get("phase", "").upper()
                result = build_info.get("result")

                if phase == "COMPLETED":
                    return result
                elif result:
                    return result  # type: ignore[no-any-return]

            time.sleep(poll_interval)

        return None

    def get_artifact(
        self,
        job_name: str,
        build_number: int,
        artifact_pattern: str,
    ) -> bytes | None:
        build_info = self.get_build_info(job_name, build_number)
        if not build_info:
            return None

        artifacts = build_info.get("artifacts", [])
        for artifact in artifacts:
            if artifact_pattern in artifact.get("displayPath", ""):
                url = f"{self.url}/job/{job_name}/{build_number}/artifact/" + artifact.get(
                    "relativePath", ""
                )
                response = self.session.get(url)
                if response.status_code == 200:
                    return response.content
        return None

    def create_or_update_build_description(
        self,
        job_name: str,
        build_number: int,
        description: str,
    ) -> bool:
        if not self.url:
            return False

        url = f"{self.url}/job/{job_name}/{build_number}/submitDescription"

        response = self.session.post(url, data={"description": description})

        return response.status_code == 200
