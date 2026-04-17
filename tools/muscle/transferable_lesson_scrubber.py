"""
Shared scrubber for transferable lessons used in cross-project import and model-pack export.

Architecture Decision Record (ADR):
- Reject non-portable lessons instead of silently weakening them
- Keep rejection reasons deterministic and auditable
- Never persist rejected lesson text into transferable-memory surfaces
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .adapters.git_adapter import GitAdapter

SCRUBBER_VERSION = "1"

ABSOLUTE_PATH_RE = re.compile(
    r"(/Users/|/home/|/private/|/var/|/tmp/|/opt/|/etc/|/srv/|/mnt/|/Volumes/|[A-Za-z]:\\\\)"
)
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{12,}|api[_-]?key|secret|token-plan-api-key)",
    re.IGNORECASE,
)
GENERIC_BRANCHES = {"main", "master", "develop", "development", "dev", "trunk"}


@dataclass(frozen=True)
class TransferScrubContext:
    """Project-specific identifiers that make a lesson non-portable."""

    project_path: str
    project_name: str
    repo_name: str
    branch_names: tuple[str, ...] = ()
    extra_identifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransferScrubDecision:
    """Result of evaluating whether a lesson is portable."""

    accepted: bool
    normalized_text: str
    content_hash: str
    reason_codes: tuple[str, ...] = ()

    def metadata(self) -> dict[str, object]:
        """Return scrubber metadata suitable for persistence."""
        return {
            "scrubber_version": SCRUBBER_VERSION,
            "accepted": self.accepted,
            "content_hash": self.content_hash,
            "reason_codes": list(self.reason_codes),
        }


def build_transfer_scrub_context(
    project_path: str | Path,
    extra_identifiers: list[str] | None = None,
) -> TransferScrubContext:
    """Build a scrubber context for one project path."""
    resolved = Path(project_path).resolve()
    branch_names: list[str] = []
    try:
        git = GitAdapter(str(resolved))
        if git.is_git_repo():
            branch = git.get_current_branch().strip()
            if branch and branch.lower() not in GENERIC_BRANCHES:
                branch_names.append(branch)
    except Exception:
        branch_names = []

    repo_name = resolved.name
    return TransferScrubContext(
        project_path=str(resolved),
        project_name=repo_name,
        repo_name=repo_name,
        branch_names=tuple(sorted(set(branch_names))),
        extra_identifiers=tuple(sorted({item for item in extra_identifiers or [] if item.strip()})),
    )


def scrub_transferable_lesson(
    text: str,
    context: TransferScrubContext,
) -> TransferScrubDecision:
    """Return a deterministic decision about whether a lesson is portable."""
    normalized = text.strip()
    content_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]

    if not normalized:
        return TransferScrubDecision(
            accepted=False,
            normalized_text="",
            content_hash=content_hash,
            reason_codes=("empty_text",),
        )

    reason_codes: list[str] = []
    lowered = normalized.lower()

    if ABSOLUTE_PATH_RE.search(normalized):
        reason_codes.append("absolute_path")

    if SECRET_RE.search(normalized):
        reason_codes.append("secret_like_content")

    identifiers = {
        item.strip().lower()
        for item in (
            context.project_name,
            context.repo_name,
            *context.extra_identifiers,
        )
        if item.strip()
    }
    for identifier in sorted(identifiers):
        if len(identifier) < 4:
            continue
        if identifier in lowered:
            reason_codes.append("project_identifier")
            break

    for branch_name in context.branch_names:
        lowered_branch = branch_name.lower()
        if lowered_branch and lowered_branch in lowered:
            reason_codes.append("branch_identifier")
            break

    deduped_reasons = tuple(sorted(set(reason_codes)))
    return TransferScrubDecision(
        accepted=not deduped_reasons,
        normalized_text=normalized,
        content_hash=content_hash,
        reason_codes=deduped_reasons,
    )
