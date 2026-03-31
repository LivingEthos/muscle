"""
TUI Views - Dashboard, Reviews, History, Settings, Knowledge Base, Fixes.

Provides rich terminal UI views with arrow key navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class ViewInterface(Protocol):
    def render(self, state: ViewState) -> Panel: ...


console = Console()


class View(Enum):
    DASHBOARD = "dashboard"
    REVIEWS = "reviews"
    HISTORY = "history"
    SETTINGS = "settings"
    KNOWLEDGE = "knowledge"
    FIXES = "fixes"
    PROJECTS = "projects"


@dataclass
class ViewState:
    current_view: View = View.DASHBOARD
    selected_index: int = 0
    current_project: str = ""
    review_count: int = 0
    pattern_count: int = 0
    last_review: str = ""
    recent_issues: list[dict] = field(default_factory=list)


class DashboardView:
    def render(self, state: ViewState) -> Panel:
        health_table = Table(title="Project Health", show_header=False, box=None)
        health_table.add_column("Metric", style="cyan")
        health_table.add_column("Value", style="white")
        health_table.add_row("Total Issues Found", str(state.review_count))
        health_table.add_row("Patterns Learned", str(state.pattern_count))
        health_table.add_row("Last Review", state.last_review or "None")

        activity_table = Table(title="Recent Activity", show_header=True, box=None)
        activity_table.add_column("Time", style="dim")
        activity_table.add_column("Event", style="white")
        if state.recent_issues:
            for issue in state.recent_issues[:5]:
                activity_table.add_row(
                    issue.get("time", ""),
                    issue.get("description", ""),
                )
        else:
            activity_table.add_row("No recent activity", "")

        patterns_table = Table(title="Top Patterns Learned", show_header=False, box=None)
        patterns_table.add_column("Pattern", style="cyan")
        if state.recent_issues:
            for issue in state.recent_issues[:3]:
                patterns_table.add_row(issue.get("pattern", ""))
        else:
            patterns_table.add_row("No patterns learned yet")

        content = Table(box=None)
        content.add_column("Left", width=40)
        content.add_column("Right", width=40)
        content.add_row(health_table, activity_table)

        return Panel(content, title=f"[bold]MUSCLE Dashboard[/bold] - {state.current_project}")


class ReviewsView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Reviews", show_header=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Target", style="cyan")
        table.add_column("Mode", style="magenta")
        table.add_column("Issues", style="yellow")
        table.add_column("Status", style="green")
        table.add_column("Time", style="dim")

        for i in range(5):
            table.add_row(
                str(i + 1),
                f"src/module_{i}.py",
                "pressure",
                str((i * 3) % 10),
                "completed",
                "2 min ago",
            )

        return Panel(table, title="[bold]Reviews[/bold]")


class HistoryView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Review History", show_header=True)
        table.add_column("Session", style="cyan")
        table.add_column("Target", style="white")
        table.add_column("Issues", style="yellow")
        table.add_column("Auto-fixed", style="green")
        table.add_column("Date", style="dim")

        for i in range(8):
            table.add_row(
                f"sess_{i:04d}",
                "tools/muscle/code_review/",
                str((i * 2) % 15),
                str(i % 5),
                "2026-03-30",
            )

        return Panel(table, title="[bold]History[/bold]")


class SettingsView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Settings", show_header=False, box=None)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Automation Level", "[1] Auto-fix")
        table.add_row("Review Gate", "[1] Block + Fix")
        table.add_row("Triggers", "Review Gate, Manual")
        table.add_row("GitHub Integration", "Disabled")
        table.add_row("Memory Location", ".muscle/")
        table.add_row("Skill Generation", "Enabled")

        return Panel(table, title="[bold]Settings[/bold]")


class KnowledgeView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Knowledge Base", show_header=True)
        table.add_column("Category", style="cyan")
        table.add_column("Patterns", style="yellow")
        table.add_column("Last Updated", style="dim")

        categories = [
            ("Auth Patterns", "12", "2026-03-30"),
            ("API Conventions", "8", "2026-03-29"),
            ("Error Handling", "15", "2026-03-28"),
            ("Security", "6", "2026-03-27"),
            ("Performance", "4", "2026-03-26"),
        ]

        for cat in categories:
            table.add_row(*cat)

        return Panel(table, title="[bold]Knowledge Base[/bold]")


class FixesView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Auto-Fixes Applied", show_header=True)
        table.add_column("Issue", style="cyan")
        table.add_column("File", style="white")
        table.add_column("Status", style="green")
        table.add_column("Date", style="dim")

        for i in range(6):
            table.add_row(
                "Auth validation missing",
                f"src/auth.py:{100 + i}",
                "verified",
                "2026-03-30",
            )

        return Panel(table, title="[bold]Fixes[/bold]")


class ProjectsView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Projects", show_header=True)
        table.add_column("", style="dim", width=2)
        table.add_column("Project", style="cyan")
        table.add_column("Patterns", style="yellow")
        table.add_column("Last Activity", style="dim")

        projects = [
            ("*", state.current_project, str(state.pattern_count), "2 min ago"),
            (" ", "other-project", "89", "1 hour ago"),
            (" ", "side-project", "45", "yesterday"),
        ]

        for proj in projects:
            table.add_row(*proj)

        return Panel(table, title="[bold]Select Project[/bold]")


class TUI:
    def __init__(self) -> None:
        self.state = ViewState()
        self.views: dict[View, ViewInterface] = {
            View.DASHBOARD: DashboardView(),
            View.REVIEWS: ReviewsView(),
            View.HISTORY: HistoryView(),
            View.SETTINGS: SettingsView(),
            View.KNOWLEDGE: KnowledgeView(),
            View.FIXES: FixesView(),
            View.PROJECTS: ProjectsView(),
        }
        self.menu_items: list[tuple[str, str, View]] = [
            ("📊", "Dashboard", View.DASHBOARD),
            ("🔍", "Reviews", View.REVIEWS),
            ("📝", "History", View.HISTORY),
            ("⚙️", "Settings", View.SETTINGS),
            ("📚", "Knowledge", View.KNOWLEDGE),
            ("🔧", "Fixes", View.FIXES),
            ("📁", "Projects", View.PROJECTS),
        ]

    def render(self) -> Layout:
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3),
        )

        header_content = Text(
            "MUSCLE - MiniMax Unified Self-Correcting Learning Engine", style="bold cyan"
        )
        layout["header"].update(Panel(header_content, border_style="cyan"))

        current_view = self.views[self.state.current_view]
        layout["main"].update(current_view.render(self.state))

        menu_text = Text()
        for _i, (icon, name, view) in enumerate(self.menu_items):
            if view == self.state.current_view:
                menu_text.append(Text(f"[{icon}] {name} ", style="bold white on blue"))
            else:
                menu_text.append(Text(f"{icon} {name} ", style="dim"))
        menu_text.append("   [r] Run Review  [p] Pressure  [s] Settings  [q] Quit")

        layout["footer"].update(Panel(menu_text, border_style="dim"))

        return layout

    def handle_key(self, key: str) -> bool:
        if key == "q":
            return False
        elif key == "r":
            self.state.current_view = View.REVIEWS
        elif key == "p":
            self.state.current_view = View.REVIEWS
        elif key == "s":
            self.state.current_view = View.SETTINGS
        elif key == "up":
            current_idx = next(
                (i for i, (_, _, v) in enumerate(self.menu_items) if v == self.state.current_view),
                0,
            )
            current_idx = max(0, current_idx - 1)
            self.state.current_view = self.menu_items[current_idx][2]
        elif key == "down":
            current_idx = next(
                (i for i, (_, _, v) in enumerate(self.menu_items) if v == self.state.current_view),
                0,
            )
            current_idx = min(len(self.menu_items) - 1, current_idx + 1)
            self.state.current_view = self.menu_items[current_idx][2]
        elif key == "left":
            current_idx = next(
                (i for i, (_, _, v) in enumerate(self.menu_items) if v == self.state.current_view),
                0,
            )
            current_idx = max(0, current_idx - 1)
            self.state.current_view = self.menu_items[current_idx][2]
        elif key == "right":
            current_idx = next(
                (i for i, (_, _, v) in enumerate(self.menu_items) if v == self.state.current_view),
                0,
            )
            current_idx = min(len(self.menu_items) - 1, current_idx + 1)
            self.state.current_view = self.menu_items[current_idx][2]
        elif key == "enter":
            pass
        return True

    def run(self) -> None:
        from readchar import readkey  # type: ignore

        with Live(self.render(), refresh_per_second=10, screen=True) as live:
            running = True
            while running:
                try:
                    key = readkey()
                    if key == "q":
                        running = False
                    else:
                        running = self.handle_key(key)
                        live.update(self.render())
                except KeyboardInterrupt:
                    running = False
