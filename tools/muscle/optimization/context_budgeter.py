"""
Context budgeter for MUSCLE prompts.

This module reduces prompt size by selecting issue-centered code windows and
compact strategy excerpts before escalating to broader context when needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .types import PromptBudget

logger = logging.getLogger(__name__)

DEFAULT_IMPORT_SCAN = 40
DEFAULT_WINDOW_RADIUS = 8
DEFAULT_REVIEW_LINE_BUDGET = 220
DEFAULT_FIX_LINE_BUDGET = 180
DEFAULT_TEXT_BUDGET = 1500


@dataclass(frozen=True)
class _LineWindow:
    start: int
    end: int


class ContextBudgeter:
    """Select compact, high-signal prompt context for MUSCLE stages."""

    def __init__(
        self,
        line_budget: int = DEFAULT_REVIEW_LINE_BUDGET,
        review_strategy: str | None = None,
        fix_strategy: str | None = None,
    ):
        self.line_budget = max(80, line_budget)
        self.review_strategy = review_strategy or "issue_windows"
        self.fix_strategy = fix_strategy or "patch_hunk_context"

    def build_semantic_review_budget(
        self,
        file_path: str,
        code_content: str,
        issues: list[dict],
        proactive: bool = False,
        escalate: bool = False,
    ) -> PromptBudget:
        """Build prompt context for semantic review."""
        if not code_content.strip():
            return PromptBudget(content="", strategy="empty", context_chars=0)

        lines = code_content.splitlines()
        if escalate or self.review_strategy == "expanded_file_slice":
            selected = self._take_head(lines, min(len(lines), 420))
            return PromptBudget(
                content="\n".join(selected),
                strategy="expanded_file_slice",
                context_chars=len("\n".join(selected)),
                truncated=len(selected) < len(lines),
                escalated=True,
                signals=["json_recovery"],
            )

        import_block = self._extract_import_block(lines)
        if proactive:
            selected, signals = self._extract_proactive_windows(lines)
            strategy = "proactive_risk_windows"
        else:
            selected, signals = self._extract_issue_windows(lines, issues)
            strategy = self.review_strategy

        merged = self._merge_sections(import_block, selected, self.line_budget)
        content = "\n".join(merged)
        return PromptBudget(
            content=content,
            strategy=strategy,
            context_chars=len(content),
            truncated=len(merged) < len(lines),
            escalated=False,
            signals=signals,
        )

    def build_fix_budget(
        self,
        issue_line: int,
        file_content: str,
        escalate: bool = False,
    ) -> PromptBudget:
        """Build prompt context for targeted fix generation."""
        if not file_content.strip():
            return PromptBudget(content="", strategy="empty", context_chars=0)

        lines = file_content.splitlines()
        if escalate or self.fix_strategy == "full_file_patch_context":
            content = "\n".join(lines[: min(len(lines), 320)])
            return PromptBudget(
                content=content,
                strategy="full_file_patch_context",
                context_chars=len(content),
                truncated=len(lines) > 320,
                escalated=escalate,
            )

        import_block = self._extract_import_block(lines)
        window = self._window(lines, issue_line, radius=10)
        selected = self._merge_sections(import_block, window, DEFAULT_FIX_LINE_BUDGET)
        content = "\n".join(selected)
        return PromptBudget(
            content=content,
            strategy=self.fix_strategy,
            context_chars=len(content),
            truncated=len(selected) < len(lines),
        )

    def trim_strategy_text(self, text: str | None, max_chars: int = DEFAULT_TEXT_BUDGET) -> str:
        """Keep only the most actionable strategy guidance."""
        if not text:
            return ""
        parts = [chunk.strip() for chunk in text.split("\n") if chunk.strip()]
        joined = "\n".join(parts[:8])
        if len(joined) <= max_chars:
            return joined
        return joined[:max_chars].rstrip() + "... [trimmed]"

    def trim_project_structure(self, text: str | None, max_lines: int = 80) -> str:
        """Limit project structure context to a compact top slice."""
        if not text:
            return ""
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) <= max_lines:
            return "\n".join(lines)
        return "\n".join(lines[:max_lines]) + "\n... [structure trimmed]"

    def trim_errors(self, errors: list[str], max_items: int = 6) -> list[str]:
        """Keep a bounded set of recent errors for the evolver."""
        trimmed: list[str] = []
        for error in errors[:max_items]:
            compact = error.strip()
            if len(compact) > 500:
                compact = compact[:500].rstrip() + "... [trimmed]"
            if compact:
                trimmed.append(compact)
        return trimmed

    @staticmethod
    def _take_head(lines: list[str], count: int) -> list[str]:
        return lines[:count]

    @staticmethod
    def _window(lines: list[str], line_number: int, radius: int) -> list[str]:
        if not lines:
            return []
        center = max(1, line_number)
        start = max(1, center - radius)
        end = min(len(lines), center + radius)
        return [f"{idx:04d}: {lines[idx - 1]}" for idx in range(start, end + 1)]

    @staticmethod
    def _extract_import_block(lines: list[str]) -> list[str]:
        selected: list[str] = []
        for idx, line in enumerate(lines[:DEFAULT_IMPORT_SCAN], start=1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "#!", '"""', "'''")) or not stripped:
                selected.append(f"{idx:04d}: {line}")
            elif selected:
                break
        return selected

    def _extract_issue_windows(
        self,
        lines: list[str],
        issues: list[dict],
    ) -> tuple[list[str], list[str]]:
        windows: list[_LineWindow] = []
        signals: list[str] = []
        for issue in issues[:10]:
            try:
                line_number = int(issue.get("line_number", 0) or 0)
            except (TypeError, ValueError):
                line_number = 0
            if line_number <= 0:
                continue
            windows.append(
                _LineWindow(
                    start=max(1, line_number - DEFAULT_WINDOW_RADIUS),
                    end=min(len(lines), line_number + DEFAULT_WINDOW_RADIUS),
                )
            )
            signals.append(issue.get("rule_id", "issue"))

        merged = self._render_windows(lines, windows, self.line_budget)
        return merged, signals

    def _extract_proactive_windows(self, lines: list[str]) -> tuple[list[str], list[str]]:
        cues = (
            "auth",
            "token",
            "permission",
            "subprocess",
            "requests.",
            "open(",
            "write(",
            "delete",
            "except Exception",
            "eval(",
            "exec(",
            "secret",
            "password",
        )
        windows: list[_LineWindow] = []
        signals: list[str] = []
        for idx, line in enumerate(lines, start=1):
            lowered = line.lower()
            matched = next((cue for cue in cues if cue.lower() in lowered), None)
            if matched is None:
                continue
            windows.append(
                _LineWindow(
                    start=max(1, idx - 6),
                    end=min(len(lines), idx + 8),
                )
            )
            signals.append(matched)
            if len(windows) >= 8:
                break

        if not windows:
            fallback = self._take_head(lines, min(len(lines), 140))
            return [f"{idx:04d}: {line}" for idx, line in enumerate(fallback, start=1)], ["head"]

        merged = self._render_windows(lines, windows, self.line_budget)
        return merged, signals

    @staticmethod
    def _merge_sections(import_block: list[str], body: list[str], line_budget: int) -> list[str]:
        if not import_block:
            return body[:line_budget]
        remaining = max(0, line_budget - len(import_block) - 1)
        merged = list(import_block)
        merged.append("----")
        merged.extend(body[:remaining])
        return merged

    @staticmethod
    def _render_windows(
        lines: list[str], windows: list[_LineWindow], line_budget: int
    ) -> list[str]:
        if not windows:
            return []

        normalized: list[_LineWindow] = []
        for window in sorted(windows, key=lambda item: item.start):
            if not normalized or window.start > normalized[-1].end + 3:
                normalized.append(window)
                continue
            last = normalized[-1]
            normalized[-1] = _LineWindow(start=last.start, end=max(last.end, window.end))

        rendered: list[str] = []
        for window in normalized:
            if rendered:
                rendered.append("...")
            for idx in range(window.start, window.end + 1):
                rendered.append(f"{idx:04d}: {lines[idx - 1]}")
                if len(rendered) >= line_budget:
                    return rendered[:line_budget]
        return rendered[:line_budget]

    def infer_target_type(self, target_path: str) -> str:
        """Infer whether the target is a file or directory."""
        try:
            target = Path(target_path)
            if target.is_file():
                return "file"
            if target.is_dir():
                return "directory"
        except OSError as exc:
            logger.debug("Failed to infer target type for %s: %s", target_path, exc)
        return "unknown"
