"""
TUI Data Provider - Centralized DB/filesystem queries for TUI views.

Provides a clean interface for views to fetch live data from project_memory.db
and the filesystem without direct DB imports in view classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..backup_manager import BackupInfo, BackupManager
from ..project_memory import ProjectMemory


@dataclass
class TUIData:
    """All live data needed by TUI views, assembled by TUIDataProvider."""

    project_path: str
    # Statistics
    review_count: int = 0
    pattern_count: int = 0
    skill_count: int = 0
    agent_count: int = 0
    backup_count: int = 0
    last_review: str = ""
    # Review runs
    review_runs: list[dict] = field(default_factory=list)
    # Learned rules (patterns)
    learned_rules: list[dict] = field(default_factory=list)
    # Skills
    skills: list[dict] = field(default_factory=list)
    # Agents
    agents: list[dict] = field(default_factory=list)
    # Backups
    backups: list[BackupInfo] = field(default_factory=list)
    # Recent findings (from most recent review run)
    recent_findings: list[dict] = field(default_factory=list)
    # Config
    automation_level: str = "auto-fix"
    review_gate: str = "block+fix"
    triggers: list[str] = field(default_factory=list)
    github_enabled: bool = False
    memory_location: str = ".muscle"
    skill_generation: bool = True
    # Audit log
    action_logs: list[dict] = field(default_factory=list)


class TUIDataProvider:
    """
    Fetches live data for TUI views from project_memory.db and filesystem.

    All queries are fault-tolerant: failures return empty data so views
    always render something (empty state) rather than crash.
    """

    def __init__(self, project_path: str | None = None):
        """
        Args:
            project_path: Absolute path to project root. Defaults to cwd.
        """
        self.project_path = project_path or str(Path.cwd())
        self._pm: ProjectMemory | None = None
        self._backup_mgr: BackupManager | None = None

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _get_pm(self) -> ProjectMemory | None:
        """Lazily create ProjectMemory, returning None on failure."""
        if self._pm is None:
            try:
                self._pm = ProjectMemory(self.project_path)
            except Exception:
                return None
        return self._pm

    def _get_backup_mgr(self) -> BackupManager | None:
        """Lazily create BackupManager, returning None on failure."""
        if self._backup_mgr is None:
            pm = self._get_pm()
            if pm is None:
                return None
            try:
                self._backup_mgr = BackupManager(pm, self.project_path)
            except Exception:
                return None
        return self._backup_mgr

    def _load_config(self) -> dict[str, Any]:
        """Load project config from .muscle/config.yaml."""
        try:
            import json

            config_path = Path(self.project_path) / ".muscle" / "config.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    data: dict[str, Any] = json.load(f).get("project", {})
                    return data
        except Exception:
            pass
        return {}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_statistics(self) -> dict[str, Any]:
        """Get overall statistics from project_memory.db."""
        pm = self._get_pm()
        if pm is None:
            return {}
        try:
            return pm.get_statistics(self.project_path)
        except Exception:
            return {}

    def get_data(self) -> TUIData:
        """
        Fetch all data needed by TUI views.

        This is the main entry point — views call this once per render cycle.
        Individual getter methods are available for granular use.
        """
        stats = self.get_statistics()
        config = self._load_config()
        pm = self._get_pm()
        backup_mgr = self._get_backup_mgr()

        # Review runs
        review_runs = []
        if pm:
            try:
                review_runs = pm.list_review_runs(project_path=self.project_path, limit=20)
            except Exception:
                pass

        # Learned rules (patterns)
        learned_rules = []
        if pm:
            try:
                learned_rules = pm.list_learned_rules(project_path=self.project_path, limit=20)
            except Exception:
                pass

        # Skills
        skills = []
        if pm:
            try:
                skills = pm.list_skills(project_path=self.project_path, limit=50)
            except Exception:
                pass

        # Agents
        agents = []
        if pm:
            try:
                agents = pm.list_agents(project_path=self.project_path, limit=50)
            except Exception:
                pass

        # Backups
        backups: list[BackupInfo] = []
        if backup_mgr:
            try:
                backups = backup_mgr.list_backups(limit=20)
            except Exception:
                pass

        # Recent findings from latest review run
        recent_findings = []
        if pm and review_runs:
            latest_run_id = review_runs[0].get("id")
            if latest_run_id:
                try:
                    recent_findings = pm.list_findings_for_run(latest_run_id)
                except Exception:
                    pass

        # Derive last_review timestamp
        last_review = ""
        if review_runs:
            created = review_runs[0].get("created_at", "")
            if created:
                try:
                    dt = datetime.fromisoformat(created)
                    last_review = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    last_review = created[:16]

        return TUIData(
            project_path=self.project_path,
            review_count=stats.get("total_reviews", 0),
            pattern_count=stats.get("total_learned_rules", 0),
            skill_count=stats.get("total_skills", len(skills)),
            agent_count=stats.get("total_agents", len(agents)),
            backup_count=len(backups),
            last_review=last_review,
            review_runs=review_runs,
            learned_rules=learned_rules,
            skills=skills,
            agents=agents,
            backups=backups,
            recent_findings=recent_findings,
            automation_level=config.get("automation_level", "auto-fix"),
            review_gate=config.get("review_gate", "block+fix"),
            triggers=config.get("triggers", []),
            github_enabled=config.get("github_enabled", False),
            memory_location=config.get("memory_location", ".muscle"),
            skill_generation=config.get("skill_generation", True),
            action_logs=self.get_action_logs(limit=30),
        )

    def get_review_runs(self, limit: int = 20) -> list[dict]:
        """Get recent review runs."""
        pm = self._get_pm()
        if pm is None:
            return []
        try:
            return pm.list_review_runs(project_path=self.project_path, limit=limit)
        except Exception:
            return []

    def get_learned_rules(self, limit: int = 20) -> list[dict]:
        """Get learned rules (patterns)."""
        pm = self._get_pm()
        if pm is None:
            return []
        try:
            return pm.list_learned_rules(project_path=self.project_path, limit=limit)
        except Exception:
            return []

    def get_skills(self, limit: int = 50) -> list[dict]:
        """Get skills."""
        pm = self._get_pm()
        if pm is None:
            return []
        try:
            return pm.list_skills(project_path=self.project_path, limit=limit)
        except Exception:
            return []

    def get_agents(self, limit: int = 50) -> list[dict]:
        """Get agents."""
        pm = self._get_pm()
        if pm is None:
            return []
        try:
            return pm.list_agents(project_path=self.project_path, limit=limit)
        except Exception:
            return []

    def get_backups(self, limit: int = 20) -> list[BackupInfo]:
        """Get recent backups."""
        backup_mgr = self._get_backup_mgr()
        if backup_mgr is None:
            return []
        try:
            return backup_mgr.list_backups(limit=limit)
        except Exception:
            return []

    def get_action_logs(self, limit: int = 30) -> list[dict]:
        """Get recent action log entries."""
        pm = self._get_pm()
        if pm is None:
            return []
        try:
            return pm.list_action_logs(project_path=self.project_path, limit=limit)
        except Exception:
            return []

    def get_fix_attempts(self, finding_ids: list[int]) -> list[dict]:
        """Get fix attempts for given finding IDs."""
        # This would need a helper in ProjectMemory - return empty for now
        # and fix_attempts can be wired when the helper exists
        return []
