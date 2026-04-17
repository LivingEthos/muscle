"""MUSCLE integration adapters.

Fix: AD-04. Explicit ``__all__`` so downstream code and tooling can discover
the supported public adapter surface without importing internal helpers.
"""

from __future__ import annotations

from .git_adapter import GitAdapter, GitAdapterError
from .github import GitHubAdapter
from .gitlab import GitLabAdapter
from .jenkins import JenkinsAdapter
from .mcp_client import MCPClient

__all__ = [
    "GitAdapter",
    "GitAdapterError",
    "GitHubAdapter",
    "GitLabAdapter",
    "JenkinsAdapter",
    "MCPClient",
]
