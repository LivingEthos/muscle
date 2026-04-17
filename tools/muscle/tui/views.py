"""
TUI Views - Dashboard, Reviews, History, Settings, Knowledge Base, Fixes, Skills, Agents, Backups, Memory.

Provides rich terminal UI views with arrow key navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..audit_presenter import format_action_log_entry

if TYPE_CHECKING:
    from .data_provider import TUIData


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
    NOTES = "notes"
    SKILLS = "skills"
    AGENTS = "agents"
    BACKUPS = "backups"
    MEMORY = "memory"
    AUDIT = "audit"
    OPTIMIZE = "optimize"


@dataclass
class ViewState:
    current_view: View = View.DASHBOARD
    selected_index: int = 0
    current_project: str = ""
    review_count: int = 0
    pattern_count: int = 0
    last_review: str = ""
    recent_issues: list[dict] = field(default_factory=list)
    # Live data from TUIDataProvider (populated by TUI class)
    data: TUIData | None = field(default=None, repr=False)
    # Data-unavailable state (set when provider raises). Fix: TU-02.
    data_unavailable: bool = False
    data_error: str = ""


class DashboardView:
    def render(self, state: ViewState) -> Panel:
        # Fix: TU-02. Show explicit error panel instead of hardcoded defaults.
        if state.data_unavailable:
            error_text = Text()
            error_text.append("Data unavailable", style="bold red")
            if state.data_error:
                error_text.append(f"\n\nReason: {state.data_error}", style="yellow")
            error_text.append("\n\nPress [r] to retry.", style="dim")
            return Panel(
                error_text,
                title=f"[bold]MUSCLE Dashboard[/bold] - {state.current_project}",
                border_style="red",
            )

        data: TUIData | None = state.data

        if data is not None:
            review_count = data.review_count
            pattern_count = data.pattern_count
            last_review = data.last_review
            skill_count = data.skill_count
            agent_count = data.agent_count
            recent_findings = data.recent_findings
            learned_rules = data.learned_rules
        else:
            review_count = state.review_count
            pattern_count = state.pattern_count
            last_review = state.last_review
            skill_count = 0
            agent_count = 0
            recent_findings = state.recent_issues
            learned_rules = []

        health_table = Table(title="Project Health", show_header=False, box=None)
        health_table.add_column("Metric", style="cyan")
        health_table.add_column("Value", style="white")
        health_table.add_row("Total Reviews", str(review_count))
        health_table.add_row("Patterns Learned", str(pattern_count))
        health_table.add_row("Skills", str(skill_count))
        health_table.add_row("Agents", str(agent_count))
        health_table.add_row("Last Review", last_review or "None")

        activity_table = Table(title="Recent Findings", show_header=True, box=None)
        activity_table.add_column("Rule", style="white")
        activity_table.add_column("File", style="cyan")
        activity_table.add_column("Auto-fix", style="green")
        if recent_findings:
            for f in recent_findings[:5]:
                auto_fix = "yes" if f.get("auto_fixable") else "no"
                file_path = f.get("file_path", "")
                if "/" in file_path:
                    file_path = file_path.split("/")[-1]
                activity_table.add_row(
                    f.get("rule_id", "")[:30],
                    f"{file_path}:{f.get('line_number', '')}",
                    auto_fix,
                )
        else:
            activity_table.add_row("No recent findings", "", "")

        patterns_table = Table(title="Top Patterns Learned", show_header=False, box=None)
        patterns_table.add_column("Pattern", style="cyan")
        patterns_table.add_column("Recurrences", style="yellow")
        patterns_table.add_column("Success", style="green")
        if learned_rules:
            for rule in learned_rules[:5]:
                success = f"{float(rule.get('success_rate', 0) or 0) * 100:.0f}%"
                patterns_table.add_row(
                    rule.get("trigger_pattern", "")[:35],
                    str(rule.get("recurrence_count", 0)),
                    success,
                )
        else:
            patterns_table.add_row("No patterns learned yet", "", "")

        # Stack health + patterns vertically, findings to the right
        content = Table(box=None)
        content.add_column("Stats", width=38)
        content.add_column("Findings / Patterns", width=50)

        stats_inner = Table(show_header=False, box=None)
        stats_inner.add_column("m", style="cyan")
        stats_inner.add_column("v", style="white")
        stats_inner.add_row("Total Reviews", str(review_count))
        stats_inner.add_row("Patterns Learned", str(pattern_count))
        stats_inner.add_row("Skills", str(skill_count))
        stats_inner.add_row("Agents", str(agent_count))
        stats_inner.add_row("Last Review", last_review or "None")

        content.add_row(stats_inner, activity_table)

        patterns_panel = Panel(patterns_table, title="[bold]Top Patterns[/bold]")
        bottom = Table(box=None)
        bottom.add_column("Full", width=90)
        bottom.add_row(patterns_panel)

        # Return a single merged layout (``Layout`` is already imported at
        # module scope; fix: TU-03).
        layout = Layout()
        layout.split_column(Layout(name="top", size=12), Layout(name="bottom"))
        layout["top"].update(
            Panel(
                content,
                border_style="cyan",
                title=f"[bold]MUSCLE Dashboard[/bold] - {state.current_project}",
            )
        )
        layout["bottom"].update(patterns_panel)

        return Panel(
            layout,
            title=f"[bold]MUSCLE Dashboard[/bold] - {state.current_project}",
            border_style="cyan",
        )


class ReviewsView:
    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Reviews", show_header=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Target", style="cyan")
        table.add_column("Mode", style="magenta")
        table.add_column("Findings", style="yellow")
        table.add_column("Duration", style="dim")
        table.add_column("Date", style="dim")

        if data is not None and data.review_runs:
            for i, run in enumerate(data.review_runs[:15]):
                target = run.get("target_path", "")
                if "/" in target:
                    target = target.split("/")[-1]
                duration_ms = run.get("duration_ms", 0)
                duration_str = f"{duration_ms / 1000:.1f}s" if duration_ms else "—"
                created = run.get("created_at", "")[:10]
                table.add_row(
                    str(i + 1),
                    target[:30],
                    run.get("review_mode", "—"),
                    str(run.get("findings_count", 0)),
                    duration_str,
                    created,
                )
        else:
            table.add_row(
                "—",
                "No reviews yet",
                "Run 'muscle review' to start",
                "—",
                "—",
                "—",
            )

        return Panel(table, title="[bold]Reviews[/bold]")


class HistoryView:
    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        review_table = Table(title="Review History", show_header=True)
        review_table.add_column("Session", style="cyan")
        review_table.add_column("Target", style="white")
        review_table.add_column("Findings", style="yellow")
        review_table.add_column("Tokens", style="magenta")
        review_table.add_column("Date", style="dim")

        if data is not None and data.review_runs:
            for run in data.review_runs:
                target = run.get("target_path", "")
                if "/" in target:
                    target = target.split("/")[-1]
                tokens = run.get("token_cost", 0)
                tokens_str = f"{tokens:,}" if tokens else "—"
                created = run.get("created_at", "")[:10]
                session = f"run_{run.get('id', '?')}"
                review_table.add_row(
                    session,
                    target[:35],
                    str(run.get("findings_count", 0)),
                    tokens_str,
                    created,
                )
        else:
            review_table.add_row(
                "—",
                "No review history yet",
                "—",
                "—",
                "—",
            )

        identity_table = Table(title="Model Identity History", show_header=True, box=None)
        identity_table.add_column("When", style="dim", width=16)
        identity_table.add_column("Requested", style="cyan")
        identity_table.add_column("Canonical", style="green")
        identity_table.add_column("Source", style="magenta")
        identity_table.add_column("Conf", style="yellow", justify="right")
        identity_history = getattr(data, "model_identity_history", []) if data else []
        if identity_history:
            for row in identity_history[:6]:
                identity_table.add_row(
                    str(row.get("created_at", ""))[:16],
                    str(row.get("requested_label") or "—")[:22],
                    str(row.get("canonical_model_key") or "Unresolved")[:24],
                    str(row.get("identity_source") or "unresolved")[:18],
                    f"{float(row.get('confidence', 0.0) or 0.0):.2f}",
                )
        else:
            identity_table.add_row("—", "No model identity history yet", "—", "—", "—")

        usage_table = Table(title="Lesson Usage Events", show_header=True, box=None)
        usage_table.add_column("When", style="dim", width=16)
        usage_table.add_column("Stage", style="cyan")
        usage_table.add_column("Source", style="magenta")
        usage_table.add_column("Lesson", style="white")
        usage_table.add_column("Outcome", style="green")
        usage_events = getattr(data, "lesson_usage_events", []) if data else []
        if usage_events:
            for event in usage_events[:6]:
                lesson_source = str(event.get("lesson_source") or "unknown")
                if lesson_source == "related_project":
                    source_label = (
                        f"related:{str(event.get('source_project_path') or '').split('/')[-1]}"
                    )
                elif lesson_source == "model_pack":
                    source_label = f"pack:{str(event.get('canonical_model_key') or 'unknown')[:18]}"
                else:
                    source_label = lesson_source
                usage_table.add_row(
                    str(event.get("created_at", ""))[:16],
                    str(event.get("stage") or "—")[:18],
                    source_label[:22],
                    str(event.get("lesson_key") or "—")[:24],
                    str(event.get("outcome") or "pending")[:20],
                )
        else:
            usage_table.add_row("—", "No lesson-usage history yet", "—", "—", "—")

        content = Table.grid(expand=True)
        content.add_row(Panel(review_table, title="[bold]Reviews[/bold]"))
        content.add_row(Panel(identity_table, title="[bold]Model Identity[/bold]"))
        content.add_row(Panel(usage_table, title="[bold]Lesson Usage[/bold]"))

        return Panel(content, title="[bold]History[/bold]")


class SettingsView:
    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Settings", show_header=False, box=None)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")

        if data is not None:
            table.add_row("Automation Level", data.automation_level)
            table.add_row("Review Gate", data.review_gate)
            triggers_str = ", ".join(data.triggers) if data.triggers else "None"
            table.add_row("Triggers", triggers_str)
            table.add_row("GitHub Integration", "Enabled" if data.github_enabled else "Disabled")
            table.add_row("Memory Location", data.memory_location)
            table.add_row("Skill Generation", "Enabled" if data.skill_generation else "Disabled")
        else:
            table.add_row("Automation Level", "[1] Auto-fix")
            table.add_row("Review Gate", "[1] Block + Fix")
            table.add_row("Triggers", "Review Gate, Manual")
            table.add_row("GitHub Integration", "Disabled")
            table.add_row("Memory Location", ".muscle/")
            table.add_row("Skill Generation", "Enabled")

        return Panel(table, title="[bold]Settings[/bold]")


class KnowledgeView:
    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        local_table = Table(title="Learned Patterns", show_header=True)
        local_table.add_column("Pattern", style="cyan", min_width=24, no_wrap=True)
        local_table.add_column("Rule", style="white")
        local_table.add_column("Recurrences", style="yellow")
        local_table.add_column("Success", style="green")
        local_table.add_column("Status", style="dim")

        if data is not None and data.learned_rules:
            for rule in data.learned_rules:
                success = f"{float(rule.get('success_rate', 0) or 0) * 100:.0f}%"
                local_table.add_row(
                    rule.get("trigger_pattern", "")[:35],
                    rule.get("rule_text", "")[:35],
                    str(rule.get("recurrence_count", 0)),
                    success,
                    rule.get("status", ""),
                )
        else:
            local_table.add_row(
                "No learned patterns yet",
                "Patterns appear after validated fixes",
                "—",
                "—",
                "—",
            )

        overlay_table = Table(title="External Overlays", show_header=True)
        overlay_table.add_column("Source", style="blue", min_width=12)
        overlay_table.add_column("State", style="magenta", min_width=10)
        overlay_table.add_column("Next", style="green", min_width=10)
        overlay_table.add_column("Why", style="white", min_width=32)

        transferred_lessons = getattr(data, "transferred_lessons", []) if data else []
        if transferred_lessons:
            for lesson in transferred_lessons[:6]:
                source_path = str(lesson.get("source_project_path", "") or "")
                source_label = source_path.split("/")[-1] if source_path else "—"
                overlay_table.add_row(
                    source_label,
                    str(lesson.get("validation_status", "")),
                    str(lesson.get("recommendation", "")),
                    str(
                        lesson.get("status_explanation", "")
                        or lesson.get("recommendation_reason", "")
                    )[:60],
                )
        else:
            overlay_table.add_row(
                "—",
                "No external overlays",
                "Project-local memory remains primary",
                "Use related-project import or attach to populate overlays",
            )

        layout = Table(box=None)
        layout.add_column("Local", width=50)
        layout.add_column("External", width=100)
        layout.add_row(local_table, overlay_table)

        return Panel(layout, title="[bold]Knowledge Base[/bold]")


class FixesView:
    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Recent Findings", show_header=True)
        table.add_column("Rule", style="cyan")
        table.add_column("File", style="white")
        table.add_column("Line", style="yellow")
        table.add_column("Auto-fix", style="green")
        table.add_column("Severity", style="red")

        if data is not None and data.recent_findings:
            for f in data.recent_findings[:20]:
                file_path = f.get("file_path", "")
                if "/" in file_path:
                    file_path = file_path.split("/")[-1]
                auto_fix = "yes" if f.get("auto_fixable") else "no"
                table.add_row(
                    f.get("rule_id", "")[:25],
                    f"{file_path}:{f.get('line_number', '')}",
                    str(f.get("line_number", "")),
                    auto_fix,
                    f.get("severity", "—"),
                )
        else:
            table.add_row(
                "No findings yet",
                "Run 'muscle review' to analyze code",
                "—",
                "—",
                "—",
            )

        return Panel(table, title="[bold]Fixes[/bold]")


class ProjectsView:
    def render(self, state: ViewState) -> Panel:
        table = Table(title="Projects", show_header=True)
        table.add_column("", style="dim", width=2)
        table.add_column("Project", style="cyan")
        table.add_column("Reviews", style="yellow")
        table.add_column("Last Activity", style="dim")

        if state.current_project:
            table.add_row(
                "*", state.current_project, str(state.review_count), state.last_review or "—"
            )
        else:
            table.add_row("*", "(none)", "—", "—")

        return Panel(table, title="[bold]Select Project[/bold]")


class NotesView:
    """Display project notes grouped by category (architecture, workflow, gotcha, dependency, integration)."""

    CATEGORIES = ["architecture", "workflow", "gotcha", "dependency", "integration"]

    def render(self, state: ViewState) -> Panel:
        from pathlib import Path

        try:
            from tools.muscle.project_memory import ProjectMemory
            from tools.muscle.project_notes import ProjectNotes
        except Exception:
            table = Table(title="Project Notes", show_header=True)
            table.add_column("Category", style="cyan")
            table.add_column("Title", style="white")
            table.add_column("Note", style="dim")
            table.add_row("Notes", "Not available", "Run 'muscle notes list' to view notes")
            return Panel(table, title="[bold]Notes[/bold]")

        project_path = str(Path.cwd())
        try:
            memory = ProjectMemory(project_path)
            notes = ProjectNotes(memory, project_path)
        except Exception:
            table = Table(title="Project Notes", show_header=True)
            table.add_column("Category", style="cyan")
            table.add_column("Title", style="white")
            table.add_row("Notes", "No project initialized", "Run 'muscle init' first")
            return Panel(table, title="[bold]Notes[/bold]")

        table = Table(title="Project Notes", show_header=True)
        table.add_column("Category", style="cyan", width=14)
        table.add_column("Title", style="white")
        table.add_column("Updated", style="dim")

        all_notes = notes.get_notes(limit=200)
        if not all_notes:
            table.add_row("—", "No notes yet", "Use 'muscle notes add' to capture knowledge")
        else:
            for note in all_notes:
                table.add_row(
                    note.category,
                    note.title[:55],
                    note.updated_at[:10],
                )

        return Panel(table, title="[bold]Notes[/bold]")


class MemoryView:
    """Display learned memory entries from CLAUDE.md, AGENT.md, and MEMORY.md."""

    def render(self, state: ViewState) -> Panel:
        from pathlib import Path

        muscle_dir = Path(state.current_project or ".") / ".muscle"
        claude_md = muscle_dir / "CLAUDE.md"
        agent_md = muscle_dir / "AGENT.md"
        memory_md = muscle_dir / "MEMORY.md"

        table = Table(title="Memory Files", show_header=True)
        table.add_column("File", style="cyan")
        table.add_column("Size", style="yellow")
        table.add_column("Modified", style="dim")
        table.add_column("Entries", style="green")

        files = [
            ("CLAUDE.md", claude_md),
            ("AGENT.md", agent_md),
            ("MEMORY.md", memory_md),
        ]

        has_any = False
        for name, path in files:
            if path.exists():
                stat = path.stat()
                size_kb = stat.st_size / 1024
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                # Count <!-- MUSCLE_LEARNED blocks as entries
                try:
                    content = path.read_text()
                    # Count blocks betweenLearned markers
                    import re

                    entries = len(re.findall(r"<!--\s*MUSCLE_LEARNED", content))
                except Exception:
                    entries = 0
                table.add_row(name, f"{size_kb:.1f} KB", mtime, str(entries) if entries else "—")
                has_any = True
            else:
                table.add_row(name, "missing", "—", "—")

        if not has_any:
            table.add_row("—", "No .muscle memory files found", "Run 'muscle review' first", "—")

        return Panel(table, title="[bold]Memory[/bold]")


class SkillsView:
    """Display generated Claude Code skills from learned patterns."""

    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Skills", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Trigger", style="white")
        table.add_column("Uses", style="yellow")
        table.add_column("Status", style="green")
        table.add_column("Last Used", style="dim")

        if data is not None and data.skills:
            for skill in data.skills[:30]:
                last_used = skill.get("last_used", "")
                if last_used:
                    last_used = last_used[:10]
                table.add_row(
                    skill.get("name", "")[:30],
                    skill.get("trigger_pattern", "")[:25],
                    str(skill.get("use_count", 0)),
                    skill.get("status", "—"),
                    last_used,
                )
        else:
            table.add_row(
                "No skills yet",
                "Skills are auto-generated from validated review patterns",
                "—",
                "—",
                "—",
            )

        return Panel(table, title="[bold]Skills[/bold]")


class AgentsView:
    """Display generated sub-agents from complex review patterns."""

    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Agents", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Trigger", style="yellow")
        table.add_column("Uses", style="magenta")
        table.add_column("File", style="dim")

        if data is not None and data.agents:
            for agent in data.agents[:30]:
                file_path = agent.get("file_path", "")
                if file_path and "/" in file_path:
                    file_path = file_path.split("/")[-1]
                table.add_row(
                    agent.get("name", "")[:25],
                    agent.get("description", "")[:30],
                    agent.get("trigger_pattern", "")[:20],
                    str(agent.get("use_count", 0)),
                    file_path[:20],
                )
        else:
            table.add_row(
                "No agents yet",
                "Agents are generated for complex multi-file review patterns",
                "—",
                "—",
                "—",
            )

        return Panel(table, title="[bold]Agents[/bold]")


class BackupsView:
    """Display recent backups from BackupManager."""

    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Backups", show_header=True)
        table.add_column("ID", style="dim", width=3)
        table.add_column("Type", style="cyan")
        table.add_column("Size", style="yellow")
        table.add_column("Created", style="dim")
        table.add_column("Retention", style="green")
        table.add_column("Path", style="white")

        if data is not None and data.backups:
            for b in data.backups[:20]:
                size_kb = b.size_bytes / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                created = b.created_at[:16]
                file_path = b.file_path
                if file_path and "/" in file_path:
                    file_path = "/".join(file_path.split("/")[-2:])
                table.add_row(
                    str(b.id),
                    b.backup_type,
                    size_str,
                    created,
                    f"{b.retention_days}d",
                    file_path[:40],
                )
        else:
            table.add_row(
                "—",
                "No backups yet",
                "Run 'muscle backup create' to create one",
                "—",
                "—",
                "—",
            )

        return Panel(table, title="[bold]Backups[/bold]")


class AuditView:
    """Display recent action log entries from project_memory.db."""

    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data

        table = Table(title="Audit Log", show_header=True)
        table.add_column("When", style="dim", width=16)
        table.add_column("Action", style="cyan", min_width=24)
        table.add_column("Entity", style="yellow", min_width=24)
        table.add_column("Details", style="white", min_width=36)

        action_logs = getattr(data, "action_logs", []) if data else []

        if not action_logs:
            table.add_row(
                "—",
                "No audit entries yet",
                "Run review/backup to generate entries",
                "—",
            )
        else:
            for entry in action_logs[:30]:
                formatted = format_action_log_entry(entry)
                table.add_row(
                    formatted["when"],
                    formatted["action"],
                    formatted["entity"] or "—",
                    formatted["details"][:60],
                )

        return Panel(table, title="[bold]Audit Log[/bold]")


class OptimizationView:
    """Display optimization hotspots, savings, and recommendations."""

    def render(self, state: ViewState) -> Panel:
        data: TUIData | None = state.data
        savings = data.token_savings_summary if data is not None else {}
        hotspots = data.optimization_hotspots if data is not None else []
        recommendations = data.optimization_recommendations if data is not None else []
        settings = data.optimization_settings if data is not None else {}

        summary = Table(title="Token Savings", show_header=False, box=None)
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="white")
        summary.add_row(
            "Net Saved",
            f"{int(savings.get('net_tokens_saved', 0) or 0):,}",
        )
        summary.add_row(
            "Gross Saved",
            f"{int(savings.get('gross_tokens_saved', 0) or 0):,}",
        )
        summary.add_row(
            "Overspend",
            f"{int(savings.get('overspend_tokens', 0) or 0):,}",
        )
        summary.add_row(
            "Confidence",
            f"{float(savings.get('confidence', 0.0) or 0.0):.0%}",
        )
        summary.add_row(
            "Workflow Default",
            settings.get("optimize.default_workflow", "review-smart"),
        )

        hotspots_table = Table(title="Top Hotspots", show_header=True, box=None)
        hotspots_table.add_column("Stage", style="magenta")
        hotspots_table.add_column("Tokens", style="yellow")
        hotspots_table.add_column("Calls", style="white")
        hotspots_table.add_column("Avg Context", style="dim")
        if hotspots:
            for hotspot in hotspots[:5]:
                hotspots_table.add_row(
                    str(hotspot.get("stage", "unknown")),
                    f"{int(hotspot.get('total_tokens', 0) or 0):,}",
                    str(hotspot.get("call_count", 0)),
                    str(int(float(hotspot.get("avg_context_chars", 0) or 0))),
                )
        else:
            hotspots_table.add_row("No telemetry yet", "0", "0", "0")

        recommendations_table = Table(title="Recommendations", show_header=True, box=None)
        recommendations_table.add_column("Scope", style="cyan")
        recommendations_table.add_column("Current", style="white")
        recommendations_table.add_column("Recommended", style="green")
        recommendations_table.add_column("Why", style="dim")
        if recommendations:
            for recommendation in recommendations[:5]:
                recommendations_table.add_row(
                    str(recommendation.get("decision_scope", "unknown")),
                    str(recommendation.get("current_value", "—")),
                    str(recommendation.get("recommended_value", "—")),
                    str(recommendation.get("reason", ""))[:70],
                )
        else:
            recommendations_table.add_row("No recommendations yet", "—", "—", "Run more reviews")

        content = Table.grid(expand=True)
        content.add_row(Panel(summary, title="[bold]Savings[/bold]"))
        content.add_row(Panel(hotspots_table, title="[bold]Hotspots[/bold]"))
        content.add_row(Panel(recommendations_table, title="[bold]Recommendations[/bold]"))
        return Panel(content, title="[bold]Optimize[/bold]")


class TUI:
    def __init__(self, project_path: str | None = None) -> None:
        from .data_provider import TUIDataProvider

        self.state = ViewState()
        self.provider = TUIDataProvider(project_path)
        self._refresh_data()

        self.views: dict[View, ViewInterface] = {
            View.DASHBOARD: DashboardView(),
            View.REVIEWS: ReviewsView(),
            View.HISTORY: HistoryView(),
            View.SETTINGS: SettingsView(),
            View.KNOWLEDGE: KnowledgeView(),
            View.FIXES: FixesView(),
            View.PROJECTS: ProjectsView(),
            View.NOTES: NotesView(),
            View.SKILLS: SkillsView(),
            View.AGENTS: AgentsView(),
            View.BACKUPS: BackupsView(),
            View.MEMORY: MemoryView(),
            View.AUDIT: AuditView(),
            View.OPTIMIZE: OptimizationView(),
        }
        self.menu_items: list[tuple[str, str, View]] = [
            ("D", "Dashboard", View.DASHBOARD),
            ("R", "Reviews", View.REVIEWS),
            ("H", "History", View.HISTORY),
            ("S", "Settings", View.SETTINGS),
            ("K", "Knowledge", View.KNOWLEDGE),
            ("F", "Fixes", View.FIXES),
            ("P", "Projects", View.PROJECTS),
            ("N", "Notes", View.NOTES),
            ("M", "Memory", View.MEMORY),
            ("L", "Skills", View.SKILLS),
            ("A", "Agents", View.AGENTS),
            ("B", "Backups", View.BACKUPS),
            ("U", "Audit", View.AUDIT),
            ("O", "Optimize", View.OPTIMIZE),
        ]

    def _refresh_data(self) -> None:
        """Refresh live data from DB/filesystem into state.

        Fix: TU-02. Sets data_unavailable=True and captures the error string
        when the provider raises, so views render an explicit error panel
        instead of silently falling back to hardcoded defaults.
        """
        try:
            data = self.provider.get_data()
            self.state.data = data
            self.state.data_unavailable = False
            self.state.data_error = ""
            self.state.current_project = data.project_path.split("/")[-1]
            self.state.review_count = data.review_count
            self.state.pattern_count = data.pattern_count
            self.state.last_review = data.last_review
        except Exception as exc:
            self.state.data_unavailable = True
            self.state.data_error = str(exc)
            self.state.data = None

    def refresh(self) -> None:
        """Public method to refresh data and re-render."""
        self._refresh_data()

    def render(self) -> Layout:
        self._refresh_data()
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
        menu_text.append("   [r] Run Review  [p] Pressure  [o] Optimize  [s] Settings  [q] Quit")

        layout["footer"].update(Panel(menu_text, border_style="dim"))

        return layout

    def handle_key(self, key: str) -> bool:
        if key == "q":
            return False
        elif key == "r":
            if self.state.data_unavailable:
                # Fix: TU-02. Retry data load when provider previously failed.
                self._refresh_data()
            else:
                self.state.current_view = View.REVIEWS
        elif key == "p":
            self.state.current_view = View.REVIEWS
        elif key == "s":
            self.state.current_view = View.SETTINGS
        elif key == "n":
            self.state.current_view = View.NOTES
        elif key == "u":
            self.state.current_view = View.AUDIT
        elif key == "o":
            self.state.current_view = View.OPTIMIZE
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
