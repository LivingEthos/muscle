"""
TUI Data Provider - Centralized DB/filesystem queries for TUI views.

Provides a clean interface for views to fetch live data from project_memory.db
and the filesystem without direct DB imports in view classes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..backup_manager import BackupInfo, BackupManager
from ..optimization import WorkflowOptimizer
from ..project_memory import ProjectMemory

logger = logging.getLogger(__name__)


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
    # Transferred lesson recommendations
    transferred_lessons: list[dict] = field(default_factory=list)
    # Debuggability
    latest_model_identity: dict[str, Any] = field(default_factory=dict)
    model_identity_history: list[dict] = field(default_factory=list)
    lesson_usage_events: list[dict] = field(default_factory=list)
    # Optimization
    optimization_hotspots: list[dict] = field(default_factory=list)
    optimization_recommendations: list[dict] = field(default_factory=list)
    token_savings_summary: dict[str, Any] = field(default_factory=dict)
    optimization_settings: dict[str, str] = field(default_factory=dict)


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
        """Load project config from ``.muscle/config.yaml``.

        Note: the file is currently written as JSON by ``ProjectManager``
        despite the ``.yaml`` extension. Fix: TU-01. Try JSON first, fall back
        to YAML if available, and log on parse failure so this ambiguity is
        diagnosable rather than silently returning defaults.
        """
        import json

        config_path = Path(self.project_path) / ".muscle" / "config.yaml"
        if not config_path.exists():
            return {}
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read %s: %s", config_path, exc)
            return {}
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml

                loaded = yaml.safe_load(text)
            except ImportError:
                logger.warning("Config at %s is not JSON and PyYAML is not installed", config_path)
                return {}
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to parse %s as YAML: %s", config_path, exc)
                return {}
        if not isinstance(loaded, dict):
            return {}
        project = loaded.get("project", {})
        return project if isinstance(project, dict) else {}

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

        optimization_hotspots: list[dict] = []
        optimization_recommendations: list[dict] = []
        token_savings_summary: dict[str, Any] = {}
        optimization_settings: dict[str, str] = {}
        transferred_lessons: list[dict] = []
        latest_model_identity: dict[str, Any] = {}
        model_identity_history: list[dict] = []
        lesson_usage_events: list[dict] = []
        if pm:
            try:
                optimizer = WorkflowOptimizer(pm, self.project_path)
                optimization_status = optimizer.get_status()
                optimization_hotspots = list(optimization_status.get("hotspots", []))
                optimization_recommendations = list(optimization_status.get("recommendations", []))
                token_savings_summary = dict(optimization_status.get("savings", {}))
                optimization_settings = dict(optimization_status.get("settings", {}))
            except Exception:
                pass
            try:
                transferred_lessons = pm.list_transferred_lesson_recommendations(
                    project_path=self.project_path,
                    include_inactive=True,
                    limit=10,
                )
            except Exception:
                pass
            try:
                latest_model_identity = pm.get_latest_model_identity(self.project_path) or {}
                model_identity_history = pm.list_model_identity_history(
                    project_path=self.project_path,
                    limit=8,
                )
                lesson_usage_events = pm.list_lesson_usage_events(
                    project_path=self.project_path,
                    limit=8,
                )
            except Exception:
                pass

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
            transferred_lessons=transferred_lessons,
            latest_model_identity=latest_model_identity,
            model_identity_history=model_identity_history,
            lesson_usage_events=lesson_usage_events,
            optimization_hotspots=optimization_hotspots,
            optimization_recommendations=optimization_recommendations,
            token_savings_summary=token_savings_summary,
            optimization_settings=optimization_settings,
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
