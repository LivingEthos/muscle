"""
Budget Manager - Token tracking and Token Plan integration.

Architecture Decision Record (ADR):
- Three budget modes: unlimited, fixed (user-specified), auto (reads Token Plan)
- Auto mode checks ~/.minimax/budget.json or .muscle/budget.json
- Cost estimation per iteration before starting
- Warning at 80% and 95% thresholds
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .types import BudgetMode

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_PATHS = [
    ".muscle/budget.json",
    "~/.minimax/budget.json",
]


@dataclass
class BudgetInfo:
    total_tokens: int
    used_tokens: int
    remaining_tokens: int
    mode: BudgetMode

    @property
    def usage_percent(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return (self.used_tokens / self.total_tokens) * 100


class BudgetManager:
    def __init__(
        self,
        mode: BudgetMode = BudgetMode.UNLIMITED,
        fixed_limit: int = 0,
        auto_budget_path: str | None = None,
        warning_thresholds: tuple[float, float] = (80.0, 95.0),
    ):
        self.mode = mode
        self._original_limit = fixed_limit
        self.fixed_limit = fixed_limit
        self.auto_budget_path = auto_budget_path
        self.warning_thresholds = warning_thresholds
        self._warnings_issued: set[float] = set()

        if mode == BudgetMode.AUTO:
            self._load_auto_budget()

    def _load_auto_budget(self) -> None:
        if self.auto_budget_path:
            path = Path(self.auto_budget_path).expanduser()
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    self.fixed_limit = data.get("remaining_tokens", 0)
                    logger.info(f"Loaded auto budget from {path}: {self.fixed_limit} tokens")
                    return
                except json.JSONDecodeError:
                    logger.warning(f"Invalid budget JSON at {path}")

        for path_str in DEFAULT_BUDGET_PATHS:
            path = Path(path_str).expanduser()
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    self.fixed_limit = data.get("remaining_tokens", 0)
                    logger.info(f"Loaded auto budget from {path}: {self.fixed_limit} tokens")
                    return
                except json.JSONDecodeError:
                    logger.warning(f"Invalid budget JSON at {path}")

        api_key = os.environ.get("MINIMAX_API_KEY")
        if api_key:
            logger.info("No budget file found. Using API key for tracking (unlimited mode).")
            self.mode = BudgetMode.UNLIMITED
        else:
            logger.warning("No API key and no budget file. Running in unlimited mode.")

    def estimate_iteration_cost(self, avg_output_tokens: int = 2000) -> int:
        if self.mode == BudgetMode.UNLIMITED:
            return 0
        return avg_output_tokens

    def check_budget(self, iteration_cost: int) -> tuple[bool, str]:
        if self.mode == BudgetMode.UNLIMITED:
            return True, ""

        if self.fixed_limit <= 0:
            return True, ""

        if self.fixed_limit < iteration_cost:
            self.fixed_limit -= iteration_cost
            return False, "Budget exceeded"

        self.fixed_limit -= iteration_cost

        usage_percent = (
            ((self._original_limit - self.fixed_limit) / self._original_limit * 100)
            if self._original_limit > 0
            else 0
        )

        for threshold in self.warning_thresholds:
            if threshold not in self._warnings_issued and usage_percent >= threshold:
                self._warnings_issued.add(threshold)
                return True, f"WARNING: Budget {threshold}% threshold reached"

        return True, ""

    def get_budget_info(self) -> BudgetInfo:
        return BudgetInfo(
            total_tokens=self._original_limit if self.mode != BudgetMode.UNLIMITED else 0,
            used_tokens=self._original_limit - self.fixed_limit
            if self.mode != BudgetMode.UNLIMITED
            else 0,
            remaining_tokens=self.fixed_limit if self.mode != BudgetMode.UNLIMITED else 0,
            mode=self.mode,
        )

    def save_budget_state(self, path: str | None = None) -> None:
        if self.mode == BudgetMode.UNLIMITED:
            return

        save_path = Path(path) if path else Path(".muscle/budget.json")
        save_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"remaining_tokens": self.fixed_limit}
        save_path.write_text(json.dumps(data, indent=2))
        logger.info(f"Saved budget state to {save_path}")
