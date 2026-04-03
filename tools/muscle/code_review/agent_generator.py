"""
Agent Generator - Creates and revises specialized sub-agents from complex patterns.

Generates Claude Code sub-agent definitions in `.muscle/agents/`.

Architecture Decision Record (ADR):
- Agents are more complex than skills, requiring specialized prompts
- Maximum 10 active agents per project to avoid bloat
- Agents reference skills for domain knowledge
- Evidence threshold of 3+ matching decisions before creating agent
- Maximum 5 revisions per agent before requiring manual intervention
- Agents can be revised without manual rewrites using evidence from memory_decisions
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..backup_manager import BackupManager
from ..m27_client import M27Client
from ..project_memory import ProjectMemory

logger = logging.getLogger(__name__)

# Lifecycle constants
MAX_ACTIVE_AGENTS = 10
MAX_AGENT_REVISIONS = 5
MIN_EVIDENCE_COUNT = 3
DECISION_TYPE_AGENT_CANDIDATE = "agent_candidate"

AGENT_TEMPLATE = """---
name: {name}
description: {description}
triggers:
{trigger_list}
capabilities:
{capability_list}
---

# {title}

## Role

{role}

## Capabilities

{capabilities_detail}

## This Project's Conventions

{conventions}

## Workflow

{workflow}

## Output Format

```json
{{
  "status": "success|partial|failed",
  "findings": [],
  "recommendations": []
}}
```

## Notes

{notes}
"""


class AgentGenerator:
    def __init__(
        self,
        project_path: str,
        m27_client: M27Client | None = None,
        project_memory: ProjectMemory | None = None,
    ):
        self.project_path = Path(project_path)
        self.agents_dir = self.project_path / ".muscle" / "agents"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.m27 = m27_client or M27Client()
        self._pm = project_memory
        self._generated_agents: list[str] = []
        self.max_agents = MAX_ACTIVE_AGENTS
        self.max_revisions = MAX_AGENT_REVISIONS
        self.min_evidence_count = MIN_EVIDENCE_COUNT

    def _get_backup_manager(self) -> BackupManager | None:
        """Get BackupManager instance if project_memory is available."""
        if self._pm is None:
            return None
        return BackupManager(self._pm, str(self.project_path))

    def _check_evidence_threshold(self, trigger_pattern: str) -> bool:
        """Check if there are enough memory_decisions to justify agent creation."""
        if self._pm is None:
            logger.warning("ProjectMemory not available, skipping evidence check")
            return True
        count = self._pm.count_decisions_for_pattern(
            str(self.project_path),
            trigger_pattern,
            DECISION_TYPE_AGENT_CANDIDATE,
        )
        meets_threshold = count >= self.min_evidence_count
        logger.debug(
            f"Evidence check for '{trigger_pattern}': {count}/{self.min_evidence_count} "
            f"(meets threshold: {meets_threshold})"
        )
        return meets_threshold

    def generate_agent(
        self,
        pattern_info: Any,
        reviewed_issues: list[dict[str, Any]],
    ) -> str | None:
        """Generate an agent from pattern information."""
        if len(self.list_agents()) >= self.max_agents:
            logger.warning(f"Maximum agents ({self.max_agents}) reached")
            return None

        agent_name = self._pattern_to_agent_name(pattern_info.pattern)
        agent_path = self.agents_dir / f"{agent_name}.md"

        if agent_path.exists():
            logger.info(f"Agent already exists: {agent_path}")
            return None

        # Check evidence threshold
        if not self._check_evidence_threshold(pattern_info.pattern):
            logger.info(
                f"Evidence threshold not met for '{pattern_info.pattern}' "
                f"(need {self.min_evidence_count}+ decisions)"
            )
            return None

        prompt = self._build_agent_prompt(pattern_info, reviewed_issues)

        response_text, _ = self.m27.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are an expert at designing Claude Code sub-agents. Generate an agent definition.",
        )

        if response_text:
            content = self._parse_agent_content(response_text, pattern_info)
            if content:
                agent_path.write_text(content)
                self._generated_agents.append(agent_name)
                self._register_agent_in_db(agent_name, pattern_info)
                logger.info(f"Generated agent: {agent_path}")
                return str(agent_path)

        return None

    def _register_agent_in_db(self, agent_name: str, pattern_info: Any) -> int | None:
        """Register created agent in project_memory.db.

        Returns the agent_id if successful, None otherwise.
        """
        if self._pm is None:
            return None
        agent_path = str(self.agents_dir / f"{agent_name}.md")
        agent_id = self._pm.insert_agent(
            project_path=str(self.project_path),
            name=agent_name,
            description=getattr(pattern_info, "category", "") or "",
            trigger_pattern=getattr(pattern_info, "pattern", agent_name),
            file_path=agent_path,
            status="active",
        )

        self._pm.insert_action_log(
            project_path=str(self.project_path),
            action_type="agent_create",
            entity_type="agent",
            entity_id=agent_id,
            details_json=json.dumps(
                {
                    "agent_name": agent_name,
                    "trigger_pattern": getattr(pattern_info, "pattern", ""),
                }
            ),
        )

        # Record agent creation decision for audit trail
        if agent_id:
            evidence_json = json.dumps(
                {
                    "occurrences": getattr(pattern_info, "occurrences", 0),
                    "confidence": getattr(pattern_info, "confidence", 0.0),
                    "files": list(getattr(pattern_info, "files", []))[:5],
                    "category": getattr(pattern_info, "category", ""),
                }
            )
            reasoning = (
                f"Agent created for pattern '{getattr(pattern_info, 'pattern', 'unknown')}'. "
                f"occurrences: {getattr(pattern_info, 'occurrences', 0)}, "
                f"confidence: {getattr(pattern_info, 'confidence', 0.0):.2f}. "
                f"Evidence from memory_decisions table."
            )
            self._pm.record_agent_decision(
                project_path=str(self.project_path),
                agent_id=agent_id,
                decision_type="create_agent",
                reasoning=reasoning,
                evidence_json=evidence_json,
            )

        return agent_id

    def can_create_agent(self, trigger_pattern: str) -> tuple[bool, str]:
        """
        Check if a new agent can be created.

        Returns (True, reason) if can create, (False, reason) if cannot.
        """
        if self._pm is None:
            return True, "ProjectMemory not available, proceeding without DB check"

        active_count = self._pm.get_active_agents_count(str(self.project_path))
        if active_count >= self.max_agents:
            # Try to archive least-used agent
            least_used = self._pm.get_least_used_active_agent(str(self.project_path))
            if least_used is None:
                return False, f"At max capacity ({self.max_agents}) and no agents to archive"
            self.archive_agent(least_used["id"])
            return True, f"Archived least-used agent '{least_used['name']}' to make room"

        if not self._check_evidence_threshold(trigger_pattern):
            return False, (
                f"Evidence threshold not met (need {self.min_evidence_count}+ "
                f"matching decisions for '{trigger_pattern}')"
            )

        return True, "All checks passed"

    def archive_agent(self, agent_id: int) -> bool:
        """
        Archive an agent by ID.

        Creates a backup before archiving.
        """
        if self._pm is None:
            logger.warning("Cannot archive agent: ProjectMemory not available")
            return False

        agent = self._pm.get_agent(agent_id)
        if agent is None:
            logger.warning(f"Agent {agent_id} not found")
            return False

        # Create backup before archiving
        backup_mgr = self._get_backup_manager()
        if backup_mgr is not None and agent.get("file_path"):
            agent_file = Path(agent["file_path"])
            if agent_file.exists():
                try:
                    backup_info = backup_mgr.create_backup("memory")
                    if backup_info:
                        logger.info(f"Backed up agent {agent['name']} before archiving")
                except Exception as e:
                    logger.warning(f"Failed to backup agent before archiving: {e}")

        # Archive in DB
        success = self._pm.archive_agent(agent_id)

        if success:
            self._pm.insert_action_log(
                project_path=str(self.project_path),
                action_type="agent_archive",
                entity_type="agent",
                entity_id=agent_id,
                details_json=json.dumps({"agent_name": agent.get("name", "")}),
            )

        # Record archive decision for audit trail
        if success:
            evidence_json = json.dumps(
                {
                    "agent_name": agent.get("name", ""),
                    "trigger_pattern": agent.get("trigger_pattern", ""),
                    "use_count": agent.get("use_count", 0),
                    "revision_count": agent.get("revision_count", 0),
                }
            )
            reasoning = (
                f"Agent '{agent.get('name', '')}' archived. "
                f"trigger_pattern: {agent.get('trigger_pattern', '')}, "
                f"use_count: {agent.get('use_count', 0)}, "
                f"revision_count: {agent.get('revision_count', 0)}."
            )
            self._pm.record_agent_decision(
                project_path=str(self.project_path),
                agent_id=agent_id,
                decision_type="archive_agent",
                reasoning=reasoning,
                evidence_json=evidence_json,
            )

        return success

    def revise_agent(
        self,
        agent_id: int,
        pattern_info: Any | None = None,
        reviewed_issues: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """
        Revise an existing agent using evidence from memory_decisions.

        Creates a backup before revision. Updates revision_count in DB.
        Returns the new agent path, or None if revision failed or at max revisions.
        """
        if self._pm is None:
            logger.warning("Cannot revise agent: ProjectMemory not available")
            return None

        agent = self._pm.get_agent(agent_id)
        if agent is None:
            logger.warning(f"Agent {agent_id} not found")
            return None

        if agent.get("archived_at"):
            logger.warning(f"Cannot revise archived agent: {agent['name']}")
            return None

        revision_count = agent.get("revision_count", 0)
        if revision_count >= self.max_revisions:
            logger.warning(f"Agent '{agent['name']}' at max revisions ({self.max_revisions})")
            return None

        agent_path = Path(agent["file_path"]) if agent.get("file_path") else None
        if agent_path is None or not agent_path.exists():
            logger.warning(f"Agent file not found: {agent_path}")
            return None

        # Backup before revision
        backup_mgr = self._get_backup_manager()
        if backup_mgr is not None:
            try:
                # Create a targeted backup of just this agent file
                backup_info = self._backup_agent_file(agent_path)
                if backup_info:
                    logger.info(f"Backed up agent '{agent['name']}' before revision")
            except Exception as e:
                logger.warning(f"Failed to backup agent before revision: {e}")

        # Build new content from evidence
        trigger_pattern = agent.get("trigger_pattern", "")

        # If pattern_info not provided, try to fetch evidence from memory_decisions
        if pattern_info is None:
            pattern_info = self._build_pattern_from_evidence(trigger_pattern)

        if reviewed_issues is None:
            reviewed_issues = self._fetch_reviewed_issues(trigger_pattern)

        # Generate revised agent content
        prompt = self._build_revision_prompt(agent, pattern_info, reviewed_issues)
        response_text, _ = self.m27.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are an expert at revising Claude Code sub-agents. Generate an improved agent definition.",
        )

        if not response_text:
            return None

        content = self._parse_agent_content(response_text, pattern_info)
        if not content:
            return None

        # Write revised content
        agent_path.write_text(content)

        # Update revision history in DB
        revision_entry = {
            "revised_at": datetime.now().isoformat(),
            "revision_number": revision_count + 1,
            "trigger_pattern": trigger_pattern,
        }
        existing_history = []
        if agent.get("revision_history_json"):
            try:
                existing_history = json.loads(agent["revision_history_json"])
            except json.JSONDecodeError:
                existing_history = []
        existing_history.append(revision_entry)
        new_history_json = json.dumps(existing_history)

        self._pm.update_agent_revision(agent_id, new_history_json)
        logger.info(f"Revised agent '{agent['name']}' (revision {revision_count + 1})")

        # Record revision decision for audit trail
        evidence_json = json.dumps(
            {
                "agent_name": agent.get("name", ""),
                "trigger_pattern": trigger_pattern,
                "revision_number": revision_count + 1,
                "reviewed_issues_count": len(reviewed_issues) if reviewed_issues else 0,
            }
        )
        reasoning = (
            f"Agent '{agent.get('name', '')}' revised to revision {revision_count + 1}. "
            f"trigger_pattern: {trigger_pattern}, "
            f"reviewed_issues: {len(reviewed_issues) if reviewed_issues else 0}."
        )
        self._pm.record_agent_decision(
            project_path=str(self.project_path),
            agent_id=agent_id,
            decision_type="revise_agent",
            reasoning=reasoning,
            evidence_json=evidence_json,
        )

        return str(agent_path)

    def _backup_agent_file(self, agent_file: Path) -> Any | None:
        """Create a backup of a single agent file using BackupManager."""
        if self._pm is None:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.project_path / ".muscle" / "backups" / "agent" / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        import hashlib
        import shutil

        dest_path = backup_dir / agent_file.name
        shutil.copy2(agent_file, dest_path)

        # Compute checksum
        sha256 = hashlib.sha256()
        with open(dest_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        checksum = sha256.hexdigest()
        size_bytes = dest_path.stat().st_size

        backup_record = self._pm.insert_backup(
            project_path=str(self.project_path),
            created_at=datetime.now().isoformat(),
            backup_type="agent",
            file_path=str(dest_path),
            checksum=checksum,
            size_bytes=size_bytes,
            retention_days=30,
        )
        return backup_record

    def _build_pattern_from_evidence(self, trigger_pattern: str) -> Any:
        """Build a pattern_info-like object from memory_decisions evidence."""
        if self._pm is None:
            return _EvidencePattern(
                pattern=trigger_pattern, category="inferred", occurrences=0, files=[]
            )
        decisions = self._pm.list_decisions(
            project_path=str(self.project_path),
            decision_type=DECISION_TYPE_AGENT_CANDIDATE,
            limit=100,
        )
        matching = [d for d in decisions if trigger_pattern in d.get("evidence_json", "")]
        return _EvidencePattern(
            pattern=trigger_pattern,
            category="inferred",
            occurrences=len(matching),
            files=[],
        )

    def _fetch_reviewed_issues(self, trigger_pattern: str) -> list[dict[str, Any]]:
        """Fetch reviewed issues related to a trigger pattern from memory_decisions."""
        if self._pm is None:
            return []
        decisions = self._pm.list_decisions(
            project_path=str(self.project_path),
            decision_type=DECISION_TYPE_AGENT_CANDIDATE,
            limit=50,
        )
        issues = []
        for d in decisions:
            try:
                evidence = json.loads(d.get("evidence_json", "{}"))
                if isinstance(evidence, dict) and evidence.get("trigger") == trigger_pattern:
                    if "issues" in evidence:
                        issues.extend(evidence["issues"][:5])
            except json.JSONDecodeError:
                continue
        return issues[:10]

    def _build_revision_prompt(
        self,
        agent: dict,
        pattern_info: Any,
        reviewed_issues: list[dict[str, Any]],
    ) -> str:
        """Build a prompt for revising an existing agent."""
        issues_text = json.dumps(reviewed_issues[:10], indent=2)
        revision_count = agent.get("revision_count", 0)

        return f"""Revise the existing Claude Code sub-agent based on new evidence.

Current Agent Name: {agent["name"]}
Current Description: {agent.get("description", "")}
Trigger Pattern: {agent.get("trigger_pattern", "")}
Revision Number: {revision_count + 1}

New Pattern Evidence:
Pattern: {pattern_info.pattern}
Category: {pattern_info.category}
Occurrences: {pattern_info.occurrences}

New Issues to Address:
{issues_text}

Generate a revised agent definition that:
1. Incorporates lessons from previous revisions
2. Addresses the new issues
3. Maintains the same triggers and role
4. Updates capabilities if needed based on new evidence

The agent should be invoked when the user asks about topics related to {pattern_info.category}.
"""

    def _pattern_to_agent_name(self, pattern: str) -> str:
        name = pattern.lower()[:30]
        name = "".join(c if c.isalnum() else "_" for c in name)
        name = "_".join(w for w in name.split("_") if w)
        return name or "specialist"

    def _build_agent_prompt(self, pattern_info: Any, reviewed_issues: list[dict[str, Any]]) -> str:
        issues_text = json.dumps(reviewed_issues[:10], indent=2)

        return f"""Generate a specialized Claude Code sub-agent based on this pattern:

Pattern: {pattern_info.pattern}
Category: {pattern_info.category}
Occurrences: {pattern_info.occurrences}
Files affected: {", ".join(pattern_info.files[:5])}

Sample issues:
{issues_text}

Generate an agent definition with:
1. Frontmatter with name, description, triggers (keywords that invoke this agent)
2. Role description
3. Specific capabilities this agent has
4. This project's conventions (reference .muscle/skills/ if available)
5. Workflow steps
6. Expected output format
7. Notes on usage

The agent should be invoked when the user asks about topics related to {pattern_info.category}.
"""

    def _parse_agent_content(self, content: str, pattern_info: Any) -> str:
        if "---" not in content:
            content = f"---\nname: {pattern_info.pattern}\ndescription: Agent for {pattern_info.category}\n---\n\n{content}"
        return content

    def get_generated_agents(self) -> list[str]:
        """Return list of agents generated this session."""
        return self._generated_agents.copy()

    def list_agents(self) -> list[Path]:
        """List all agent files in the project."""
        if not self.agents_dir.exists():
            return []
        return list(self.agents_dir.glob("*.md"))

    def validate_agent(self, agent_path: Path) -> bool:
        """Validate agent has required frontmatter fields."""
        content = agent_path.read_text()
        required_fields = ["name:", "description:", "triggers:", "capabilities:"]
        return all(field in content for field in required_fields)


class _EvidencePattern:
    """Internal class to hold pattern info from evidence."""

    def __init__(self, pattern: str, category: str, occurrences: int, files: list[str]):
        self.pattern = pattern
        self.category = category
        self.occurrences = occurrences
        self.files = files
