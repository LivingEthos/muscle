"""
MUSCLE TUI - Terminal User Interface.

Provides:
- Dashboard view with project health
- Reviews view
- History view
- Settings view
- Knowledge base view
- Project switcher
"""

from __future__ import annotations

from .project_manager import ProjectConfig, ProjectManager
from .views import TUI, View, ViewState

__all__ = ["TUI", "View", "ViewState", "ProjectManager", "ProjectConfig"]
