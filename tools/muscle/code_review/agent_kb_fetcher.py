"""
Agent Knowledge Base Fetcher - Fetches best practices from awesome-claude-* repos.

Downloads and parses well-designed agent and skill patterns from community repos.

Architecture Decision Record (ADR):
- Fetches from VoltAgent/awesome-claude-code-subagents
- Fetches from travisvn/awesome-claude-skills
- Caches locally to avoid repeated network calls
- Provides templates MUSCLE can refine for project needs
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..io_safety import atomic_write_text

logger = logging.getLogger(__name__)

AGENT_KB_CACHE_DIR = ".muscle/agent_kb"


@dataclass(frozen=True)
class PinnedKBSource:
    """A single upstream KB source pinned to an immutable commit + content hash.

    Hardening (commit-SHA pinning + content-hash verification): the upstream
    READMEs are fetched from a pinned commit SHA (NOT the mutable ``main``
    branch) and the raw fetched bytes are hashed and compared against
    ``expected_sha256`` before any parsing or caching happens. A mismatch is
    treated as untrusted/tampered content and rejected (fail closed).

    ``pinned_sha`` and ``expected_sha256`` are clearly-labeled constants that
    MUST be refreshed together via a controlled release process whenever the
    vendored upstream revision is bumped. They are intentionally NOT derived
    from a mutable ref so that drift is impossible without an explicit change.
    """

    repo_url: str
    pinned_sha: str
    expected_sha256: str
    kind: str  # "subagents" or "skills"

    def readme_url(self) -> str:
        """Raw README URL pinned to the immutable commit SHA (not /main)."""
        raw = self.repo_url.replace("github.com", "raw.githubusercontent.com")
        return f"{raw}/{self.pinned_sha}/README.md"


# Pinned upstream sources, vendored 2026-06-09. To bump a source: resolve the
# new commit SHA (`git ls-remote <repo_url> HEAD`), fetch
# `raw.githubusercontent.com/<org>/<repo>/<sha>/README.md`, review the diff for
# injected content, then update BOTH pinned_sha and expected_sha256 (SHA-256 of
# the raw README bytes) together via a controlled release. A source whose hash
# no longer matches fails closed: nothing is parsed or cached.
AGENT_REPOS: list[PinnedKBSource] = [
    PinnedKBSource(
        repo_url="https://github.com/VoltAgent/awesome-claude-code-subagents",
        pinned_sha="2f9cf8b9562dcc235cc2296bda6df82d60e800be",
        expected_sha256="ec52baa379192189b833ce9c9bec0bf0d0af28159eebdff363d3cede5c1f70b2",
        kind="subagents",
    ),
    PinnedKBSource(
        repo_url="https://github.com/travisvn/awesome-claude-skills",
        pinned_sha="1da55aa810f206d3fe2005e7e3989b15a275d942",
        expected_sha256="b15fa837edeb632f4a85871590df4dab64deec10af904d512a5ee12bce8773c9",
        kind="skills",
    ),
]

# Cap on embedded free-text fields sourced from upstream READMEs.
_MAX_FIELD_LEN = 300
# Lines that look like injected instructions are dropped before embedding.
_INJECTION_LINE_RE = re.compile(
    r"(?i)\b(ignore (the |all )?(previous|above)|disregard|system prompt|"
    r"you are now|act as|<\|?(system|im_start|im_end)\|?>)\b"
)


def _sanitize_field(value: str) -> str:
    """Sanitize an UNTRUSTED upstream string before it is embedded in a
    template that feeds the LLM.

    Upstream README content comes from a mutable branch and must be treated as
    attacker-controlled. We strip control/non-printable characters, neutralize
    markdown control sequences, drop obvious prompt-injection lines, and cap
    the length so a single entry cannot dominate a prompt.
    """
    if not value:
        return ""
    # Drop control / non-printable characters (keep ordinary whitespace).
    cleaned = "".join(ch for ch in value if ch == " " or (ch.isprintable() and ch != "\t"))
    # Remove lines that look like injected instructions.
    kept_lines = [line for line in cleaned.splitlines() if not _INJECTION_LINE_RE.search(line)]
    cleaned = " ".join(part.strip() for part in kept_lines if part.strip())
    # Neutralize markdown/HTML control sequences that could break out of the
    # template or inject formatting.
    cleaned = cleaned.replace("`", "'").replace("\\", "/")
    cleaned = re.sub(r"[<>]", "", cleaned)
    cleaned = re.sub(r"[*_#\[\]{}|]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > _MAX_FIELD_LEN:
        cleaned = cleaned[:_MAX_FIELD_LEN].rstrip() + "…"
    return cleaned


class AgentKBFetcher:
    def __init__(
        self,
        project_path: str | None = None,
        cache_ttl_hours: int = 24,
        sources: list[PinnedKBSource] | None = None,
    ):
        self.project_path = Path(project_path) if project_path else Path.cwd()
        self.cache_dir = self.project_path / AGENT_KB_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        # Sources are pinned commit SHAs with expected content hashes. Tests may
        # inject their own pins (with hashes computed from fixtures) so that the
        # happy path and the fail-closed path are both exercisable offline.
        self.sources = sources if sources is not None else AGENT_REPOS
        self._agents: list[dict[str, Any]] = []
        self._skills: list[dict[str, Any]] = []

    def fetch_all(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch and parse all agent KB sources."""
        self._agents = []
        self._skills = []

        for source in self.sources:
            if source.kind == "subagents":
                self._fetch_subagents(source)
            elif source.kind == "skills":
                self._fetch_skills(source)

        self._save_cache()
        return self._agents, self._skills

    @staticmethod
    def _verify_content_hash(content: str, source: PinnedKBSource) -> bool:
        """Fail closed: only accept content whose SHA-256 matches the pin.

        The README is fetched from a pinned commit SHA, but a hash check still
        guards against an upstream force-push to that SHA, a poisoned mirror, or
        an on-path tamper. A mismatch means the content is UNTRUSTED and must
        not be parsed or cached.
        """
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual != source.expected_sha256:
            logger.error(
                "Agent KB content hash mismatch for %s @ %s: expected %s, got %s; "
                "rejecting untrusted content (no parse, no cache write)",
                source.repo_url,
                source.pinned_sha,
                source.expected_sha256,
                actual,
            )
            return False
        return True

    def _fetch_subagents(self, source: PinnedKBSource) -> None:
        """Fetch subagent patterns from a pinned, hash-verified source."""
        try:
            content = self._fetch_url(source.readme_url())

            if content:
                if not self._verify_content_hash(content, source):
                    return
                agents = self._parse_subagents_from_readme(content)
                self._agents.extend(agents)
                logger.info(f"Fetched {len(agents)} subagent patterns")
        except Exception as e:
            logger.warning(f"Failed to fetch subagents from {source.repo_url}: {e}")
            self._load_from_cache()

    def _fetch_skills(self, source: PinnedKBSource) -> None:
        """Fetch skill patterns from a pinned, hash-verified source."""
        try:
            content = self._fetch_url(source.readme_url())

            if content:
                if not self._verify_content_hash(content, source):
                    return
                skills = self._parse_skills_from_readme(content)
                self._skills.extend(skills)
                logger.info(f"Fetched {len(skills)} skill patterns")
        except Exception as e:
            logger.warning(f"Failed to fetch skills from {source.repo_url}: {e}")
            self._load_from_cache()

    def _fetch_url(self, url: str) -> str | None:
        """Fetch URL content using urllib."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MUSCLE/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data: bytes = response.read()
                return data.decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None

    def _parse_subagents_from_readme(self, content: str) -> list[dict[str, Any]]:
        """Parse subagent entries from README markdown."""
        agents = []

        pattern = r"- \[([^\]]+)\]\(([^\)]+)\)\s*-?\s*([^\n]*)"
        matches = re.findall(pattern, content)

        for name, url, description in matches:
            if url.endswith(".md") or "agent" in name.lower():
                # Upstream README content is UNTRUSTED — sanitize before storing.
                agents.append(
                    {
                        "name": _sanitize_field(name.strip()),
                        "url": url.strip(),
                        "description": _sanitize_field(description.strip()),
                        "source": "awesome-claude-code-subagents",
                        "fetched_at": datetime.now().isoformat(),
                    }
                )

        return agents

    def _parse_skills_from_readme(self, content: str) -> list[dict]:
        """Parse skill entries from README markdown."""
        skills = []

        pattern = r"- \[([^\]]+)\]\(([^\)]+)\)\s*-?\s*([^\n]*)"
        matches = re.findall(pattern, content)

        for name, url, description in matches:
            if url.endswith(".md") or "skill" in name.lower():
                # Upstream README content is UNTRUSTED — sanitize before storing.
                skills.append(
                    {
                        "name": _sanitize_field(name.strip()),
                        "url": url.strip(),
                        "description": _sanitize_field(description.strip()),
                        "source": "awesome-claude-skills",
                        "fetched_at": datetime.now().isoformat(),
                    }
                )

        return skills

    def _save_cache(self) -> None:
        """Save fetched data to local cache.

        Written atomically with restrictive (0o600) permissions. The cache
        holds parsed UNTRUSTED upstream content, so it is treated as a
        sensitive file and re-validated on load (see _validate_cache_data).
        """
        cache_file = self.cache_dir / "agent_kb_cache.json"
        cache_data = {
            "agents": self._agents,
            "skills": self._skills,
            "cached_at": datetime.now().isoformat(),
        }
        atomic_write_text(cache_file, json.dumps(cache_data, indent=2))
        try:
            cache_file.chmod(0o600)
        except OSError as exc:
            logger.warning(f"Could not set restrictive perms on {cache_file}: {exc}")
        logger.debug(f"Saved agent KB cache to {cache_file}")

    @staticmethod
    def _validate_cache_data(cache_data: Any) -> bool:
        """Schema-check the loaded cache before trusting it.

        The cache file can be tampered with on disk (cache poisoning), so its
        structure is validated: a dict with a ``cached_at`` string and
        ``agents``/``skills`` lists of dicts. Anything else is rejected and the
        caller treats it as a cache miss.
        """
        if not isinstance(cache_data, dict):
            return False
        if not isinstance(cache_data.get("cached_at"), str):
            return False
        for key in ("agents", "skills"):
            value = cache_data.get(key, [])
            if not isinstance(value, list):
                return False
            if not all(isinstance(item, dict) for item in value):
                return False
        return True

    def _load_from_cache(self) -> None:
        """Load data from local cache if available, fresh, and well-formed."""
        cache_file = self.cache_dir / "agent_kb_cache.json"

        if not cache_file.exists():
            return

        try:
            cache_data = json.loads(cache_file.read_text())
            if not self._validate_cache_data(cache_data):
                logger.warning("Agent KB cache failed schema validation; ignoring")
                return
            cached_at = datetime.fromisoformat(cache_data["cached_at"])

            if datetime.now() - cached_at < self.cache_ttl:
                self._agents = cache_data.get("agents", [])
                self._skills = cache_data.get("skills", [])
                logger.debug("Loaded agent KB from cache")
            else:
                logger.debug("Agent KB cache expired")
        except Exception as e:
            logger.warning(f"Failed to load agent KB cache: {e}")

    def get_agents(self, force_refresh: bool = False) -> list[dict]:
        """Get cached or freshly-fetched agents."""
        if force_refresh or not self._agents:
            self.fetch_all()
        return self._agents

    def get_skills(self, force_refresh: bool = False) -> list[dict]:
        """Get cached or freshly-fetched skills."""
        if force_refresh or not self._skills:
            self.fetch_all()
        return self._skills

    def search_agents(self, query: str) -> list[dict]:
        """Search agents by name or description."""
        query_lower = query.lower()
        return [
            a
            for a in self.get_agents()
            if query_lower in a.get("name", "").lower()
            or query_lower in a.get("description", "").lower()
        ]

    def search_skills(self, query: str) -> list[dict]:
        """Search skills by name or description."""
        query_lower = query.lower()
        return [
            s
            for s in self.get_skills()
            if query_lower in s.get("name", "").lower()
            or query_lower in s.get("description", "").lower()
        ]

    def get_agent_template(self, category: str) -> str | None:
        """Get agent template for a specific category."""
        agents = self.search_agents(category)
        if agents:
            return f"""# Template for {category} Agent

Based on patterns from community agents.

## Common Patterns
{agents[0].get("description", "N/A")}

## Recommended Structure
- Name: {category.lower()}-specialist
- Triggers: {category.lower()}, related keywords
- Capabilities: Domain-specific checks and validations
"""
        return None

    def get_skill_template(self, category: str) -> str | None:
        """Get skill template for a specific category."""
        skills = self.search_skills(category)
        if skills:
            return f"""# Template for {category} Skill

Based on patterns from community skills.

## Common Patterns
{skills[0].get("description", "N/A")}

## Recommended Structure
- Triggers: {category.lower()}, related keywords
- Patterns to avoid
- Recommended patterns
- Implementation guide
"""
        return None
