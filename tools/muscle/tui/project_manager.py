"""
Project Manager - Auto-detect projects and manage .muscle/ directories.

Handles:
- Project auto-detection from git/package files
- Creating .muscle/ directories
- Managing project configurations
- Multi-project support
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    pass

DEFAULT_MUSCLE_DIR = ".muscle"
CONFIG_FILE = "config.yaml"
PROJECT_DB = "project.db"
STRATEGY_KB = "strategy_kb.json"
CLAUDE_MEMORY = "CLAUDE.md"
AGENT_MEMORY = "AGENT.md"
MEMORY_MEMORY = "MEMORY.md"
SKILLS_DIR = "skills"
LOGS_DIR = "logs"


@dataclass
class ProjectConfig:
    name: str
    path: Path
    languages: list[str] = field(default_factory=list)
    automation_level: str = "auto-fix"
    review_gate: str = "block+fix"
    review_execution: str = "local"
    triggers: list[str] = field(default_factory=list)
    github_enabled: bool = False
    memory_location: str = DEFAULT_MUSCLE_DIR
    initialized: bool = False
    platform: str = "auto"
    api_key_source: str = "env"
    hooks_enabled: bool = True
    cli_path: str | None = None
    related_project_mode: str = "suggest"
    model_pack_mode: str = "suggest"
    canonical_model_key: str | None = None
    model_identity_source: str = "unresolved"
    model_manual_override: str | None = None


class ProjectManager:
    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path.cwd()
        self._current_project: ProjectConfig | None = None

    def detect_project(self) -> ProjectConfig | None:
        git_root = self._find_git_root()
        if git_root:
            name = git_root.name
            languages = self._detect_languages(git_root)
            self._current_project = ProjectConfig(
                name=name,
                path=git_root,
                languages=languages,
            )
            return self._current_project

        if self.base_path.exists():
            name = self.base_path.name
            languages = self._detect_languages(self.base_path)
            self._current_project = ProjectConfig(
                name=name,
                path=self.base_path,
                languages=languages,
            )
            return self._current_project

        return None

    def _find_git_root(self) -> Path | None:
        current = self.base_path
        while current != current.parent:
            if (current / ".git").exists():
                return current
            current = current.parent
        return None

    def _detect_languages(self, path: Path) -> list[str]:
        languages = []
        indicators = {
            "Python": ["pyproject.toml", "setup.py", "requirements.txt", "*.py"],
            "TypeScript": ["tsconfig.json", "package.json"],
            "JavaScript": ["package.json"],
            "Go": ["go.mod", "go.sum"],
            "Rust": ["Cargo.toml", "Cargo.lock"],
            "Java": ["pom.xml", "build.gradle"],
            "C/C++": ["CMakeLists.txt", "*.cmake"],
        }
        for lang, patterns in indicators.items():
            for pattern in patterns:
                if any(char in pattern for char in "*?[]"):
                    if any(path.rglob(pattern)):
                        languages.append(lang)
                        break
                elif (path / pattern).exists():
                    languages.append(lang)
                    break
        return languages

    def init_project(self, config: ProjectConfig) -> bool:
        muscle_dir = config.path / DEFAULT_MUSCLE_DIR
        try:
            muscle_dir.mkdir(exist_ok=True)
            (muscle_dir / SKILLS_DIR).mkdir(exist_ok=True)
            (muscle_dir / LOGS_DIR).mkdir(exist_ok=True)

            self._write_config(config, muscle_dir)
            self._create_memory_files(muscle_dir)
            self._init_knowledge_base(muscle_dir)
            self.register_project(config.path)

            config.initialized = True
            self._current_project = config
            return True
        except Exception as e:
            print(f"Failed to initialize project: {e}")
            return False

    def _write_config(self, config: ProjectConfig, muscle_dir: Path) -> None:
        config_path = muscle_dir / CONFIG_FILE
        config_data = {
            "project": {
                "name": config.name,
                "languages": config.languages,
                "automation_level": config.automation_level,
                "review_gate": config.review_gate,
                "review_execution": config.review_execution,
                "triggers": config.triggers,
                "github_enabled": config.github_enabled,
                "memory_location": config.memory_location,
                "platform": config.platform,
                "api_key_source": config.api_key_source,
                "hooks_enabled": config.hooks_enabled,
                "cli_path": config.cli_path,
                "related_project_mode": config.related_project_mode,
                "model_pack_mode": config.model_pack_mode,
                "canonical_model_key": config.canonical_model_key,
                "model_identity_source": config.model_identity_source,
                "model_manual_override": config.model_manual_override,
            }
        }
        config_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    def _create_memory_files(self, muscle_dir: Path) -> None:
        claude_md = muscle_dir / CLAUDE_MEMORY
        if not claude_md.exists():
            claude_md.write_text("""<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE_LEARNED_END -->
""")

        agent_md = muscle_dir / AGENT_MEMORY
        if not agent_md.exists():
            agent_md.write_text("""<!-- MUSCLE_LEARNED_START -->
<!-- MUSCLE_LEARNED_END -->
""")

        memory_md = muscle_dir / MEMORY_MEMORY
        if not memory_md.exists():
            memory_md.write_text("""# MUSCLE Memory

<!-- MUSCLE_MEMORY_START -->
<!-- MUSCLE_MEMORY_END -->
""")

    def _init_knowledge_base(self, muscle_dir: Path) -> None:
        strategy_path = muscle_dir / STRATEGY_KB
        if not strategy_path.exists():
            strategy_data = {
                "version": "1.0",
                "strategies": [],
                "evolution_history": [],
            }
            with open(strategy_path, "w") as f:
                json.dump(strategy_data, f, indent=2)

    def get_current_project(self) -> ProjectConfig | None:
        if self._current_project is None:
            return self.detect_project()
        return self._current_project

    def get_muscle_dir(self, project_path: Path | None = None) -> Path | None:
        path = (
            project_path or self._current_project.path if self._current_project else self.base_path
        )
        muscle_dir = path / DEFAULT_MUSCLE_DIR
        if muscle_dir.exists():
            return muscle_dir
        return None

    def find_nearest_muscle_dir(self, start_path: Path | None = None) -> Path | None:
        current = (start_path or self.base_path).resolve()
        if current.is_file():
            current = current.parent

        while True:
            muscle_dir = current / DEFAULT_MUSCLE_DIR
            if muscle_dir.exists():
                return muscle_dir
            if current == current.parent:
                return None
            current = current.parent

    def find_nearest_project_path(self, start_path: Path | None = None) -> Path | None:
        muscle_dir = self.find_nearest_muscle_dir(start_path)
        if muscle_dir is None:
            return None
        return muscle_dir.parent

    def load_config(self, project_path: Path) -> ProjectConfig | None:
        muscle_dir = project_path / DEFAULT_MUSCLE_DIR
        config_path = muscle_dir / CONFIG_FILE
        if not config_path.exists():
            return None

        try:
            text = config_path.read_text(encoding="utf-8")
            loaded = json.loads(text)
        except json.JSONDecodeError:
            try:
                loaded = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                return None
        except OSError:
            return None

        try:
            data = loaded["project"]
        except (KeyError, TypeError):
            return None

        return ProjectConfig(
            name=data["name"],
            path=project_path,
            languages=data.get("languages", []),
            automation_level=data.get("automation_level", "auto-fix"),
            review_gate=data.get("review_gate", "block+fix"),
            review_execution=data.get("review_execution", "local"),
            triggers=data.get("triggers", []),
            github_enabled=data.get("github_enabled", False),
            memory_location=data.get("memory_location", DEFAULT_MUSCLE_DIR),
            initialized=True,
            platform=data.get("platform", "auto"),
            api_key_source=data.get("api_key_source", "env"),
            hooks_enabled=data.get("hooks_enabled", True),
            cli_path=data.get("cli_path"),
            related_project_mode=data.get("related_project_mode", "suggest"),
            model_pack_mode=data.get("model_pack_mode", "suggest"),
            canonical_model_key=data.get("canonical_model_key") or None,
            model_identity_source=data.get("model_identity_source", "unresolved"),
            model_manual_override=data.get("model_manual_override") or None,
        )

    def load_nearest_config(self, start_path: Path | None = None) -> ProjectConfig | None:
        project_path = self.find_nearest_project_path(start_path)
        if project_path is None:
            return None
        return self.load_config(project_path)

    def find_all_projects(self) -> list[ProjectConfig]:
        from ..system_db import SystemDatabase

        projects = []
        system_db = SystemDatabase()
        for row in system_db.list_registered_projects():
            project_path = Path(str(row.get("project_path", "")))
            if not project_path.exists():
                continue
            project = self.load_config(project_path)
            if project:
                projects.append(project)

        if projects:
            return projects

        home = Path.home()
        for muscle_dir in home.rglob(DEFAULT_MUSCLE_DIR):
            project_path = muscle_dir.parent
            if project_path.exists():
                project = self.load_config(project_path)
                if project:
                    projects.append(project)
        return projects

    @staticmethod
    def detect_cli_location() -> str | None:
        import os
        import shutil

        # Check explicit env var first
        env_path = os.environ.get("MINIMAX_MUSCLE_PATH")
        if env_path and Path(env_path).exists():
            return env_path

        # Check PATH
        for name in ["muscle", "muscle.exe"]:
            path = shutil.which(name)
            if path:
                return path

        # Check common local locations
        for name in ["muscle", "muscle.exe"]:
            local_path = Path.cwd() / "tools" / "muscle" / "venv" / "bin" / name
            if local_path.exists():
                return str(local_path)

        # Check if runnable as module
        local_cli = Path.cwd() / "tools" / "muscle" / "cli.py"
        if local_cli.exists():
            return "python -m tools.muscle.cli"

        return None

    @staticmethod
    def detect_platform() -> str:
        import os

        forced_platform = os.environ.get("MUSCLE_FORCE_PLATFORM")
        if forced_platform:
            return forced_platform
        if os.environ.get("OPENCODE_SESSION"):
            return "opencode"
        if os.environ.get("CLAUDE_CODE"):
            return "claude-code"
        codex_originator = os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "")
        if (
            os.environ.get("CODEX_SHELL")
            or os.environ.get("CODEX_THREAD_ID")
            or codex_originator.startswith("Codex")
        ):
            return "codex"
        return "auto"

    def init_opencode_config(self, config: ProjectConfig, muscle_dir: Path) -> bool:
        opencode_dir = config.path / ".opencode"
        source_dir = Path(__file__).parent.parent / ".opencode"
        try:
            opencode_dir.mkdir(exist_ok=True)

            opencode_json = {
                "$schema": "https://opencode.ai/config.json",
                "model": os.environ.get("OPENCODE_MODEL", "anthropic/claude-sonnet-4-5"),
                "agent": {
                    "muscle-reviewer": {
                        "description": "MUSCLE code review agent with self-learning",
                        "mode": "subagent",
                        "prompt": "You are a code reviewer powered by MUSCLE. Use muscle tools for code review.",
                    }
                },
                "permission": {
                    "bash": {
                        "muscle *": "allow",
                        "git *": "allow",
                    }
                },
                "plugins": [
                    "./plugins/muscle-integration.ts",
                ],
            }

            opencode_json_path = opencode_dir / "opencode.json"
            with open(opencode_json_path, "w") as f:
                json.dump(opencode_json, f, indent=2)

            symlink_dirs = ["agents", "plugins", "skills"]
            for dir_name in symlink_dirs:
                source = source_dir / dir_name
                target = opencode_dir / dir_name
                if source.exists() and not target.exists():
                    try:
                        target.symlink_to(source.resolve())
                    except OSError:
                        # Symlink failed (e.g., Windows or permissions) — copy instead
                        import shutil

                        shutil.copytree(str(source), str(target))

            return True
        except Exception as e:
            print(f"Failed to initialize OpenCode config: {e}")
            return False

    def update_muscle_config(
        self,
        project_path: Path,
        api_key: str | None = None,
        hooks_enabled: bool | None = None,
        review_gate: str | None = None,
        review_execution: str | None = None,
        platform: str | None = None,
        cli_path: str | None = None,
        api_key_source: str | None = None,
        related_project_mode: str | None = None,
        model_pack_mode: str | None = None,
        canonical_model_key: str | None = None,
        model_identity_source: str | None = None,
        model_manual_override: str | None = None,
    ) -> bool:
        muscle_dir = project_path / DEFAULT_MUSCLE_DIR
        config_path = muscle_dir / CONFIG_FILE
        if not config_path.exists():
            return False

        try:
            text = config_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except json.JSONDecodeError:
            try:
                data = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                return False
        except OSError:
            return False

        if api_key is not None:
            os.environ["MINIMAX_API_KEY"] = api_key
            data["project"]["api_key_source"] = "manual"
        if hooks_enabled is not None:
            data["project"]["hooks_enabled"] = hooks_enabled
        if review_gate is not None:
            data["project"]["review_gate"] = review_gate
        if review_execution is not None:
            data["project"]["review_execution"] = review_execution
        if platform is not None:
            data["project"]["platform"] = platform
        if cli_path is not None:
            data["project"]["cli_path"] = cli_path
        if api_key_source is not None:
            data["project"]["api_key_source"] = api_key_source
        if related_project_mode is not None:
            data["project"]["related_project_mode"] = related_project_mode
        if model_pack_mode is not None:
            data["project"]["model_pack_mode"] = model_pack_mode
        if canonical_model_key is not None:
            data["project"]["canonical_model_key"] = canonical_model_key
        if model_identity_source is not None:
            data["project"]["model_identity_source"] = model_identity_source
        if model_manual_override is not None:
            data["project"]["model_manual_override"] = model_manual_override

        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        return True

    def register_project(self, project_path: Path) -> None:
        """Register the project in the global system database."""
        from ..project_fingerprint import build_project_fingerprint
        from ..system_db import SystemDatabase

        config = self.load_config(project_path)
        fingerprint = build_project_fingerprint(
            project_path,
            display_name=config.name if config else project_path.name,
            languages=config.languages if config else None,
        )
        SystemDatabase().register_project(fingerprint)

    def is_project_enabled(self, project_path: Path) -> bool:
        """Check if MUSCLE is enabled for a project.

        Args:
            project_path: Path to the project root.

        Returns:
            True if MUSCLE is enabled, False otherwise.
        """
        from ..project_memory import ProjectMemory

        try:
            pm = ProjectMemory(str(project_path))
            state = pm.get_automation_state(str(project_path), "project_enabled")
            if state and state.get("state_value"):
                state_val = state["state_value"]
                return str(state_val) == "true"
            # Default to True if never set (opt-out model)
            return True
        except Exception:
            return False

    def set_project_enabled(self, project_path: Path, enabled: bool) -> bool:
        """Enable or disable MUSCLE for a project.

        Args:
            project_path: Path to the project root.
            enabled: True to enable, False to disable.

        Returns:
            True if successful, False otherwise.
        """
        from ..project_memory import ProjectMemory

        try:
            pm = ProjectMemory(str(project_path))
            pm.set_automation_state(
                str(project_path),
                "project_enabled",
                "true" if enabled else "false",
            )
            return True
        except Exception as e:
            print(f"Failed to set project enabled state: {e}")
            return False
