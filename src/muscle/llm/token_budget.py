"""Token budget management for API calls.

Architecture Decision Record (ADR):
- Reserve/commit pattern: lock only during check+reserve and commit/release,
  NOT during the actual LLM call. This allows parallel requests.
- Thread-safety is self-contained: a re-entrant threading.RLock guards all
  mutations and reads of shared state (usage_history, _reservations). Public
  methods acquire it themselves, so callers do NOT need an external lock; the
  RLock makes nested public calls (reserve_tokens -> check_budget) safe.
- _cleanup_old_history() prevents memory bloat by pruning entries >30 days old
  and enforcing a max_history_entries cap.
- COST_RATES are approximate and should be updated as provider pricing changes.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


class BudgetPeriod(str, Enum):
    """Time period for budget tracking."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


@dataclass
class TokenUsage:
    """Record of token usage for a single API call."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provider: str = ""
    model: str = ""
    operation: str = ""


@dataclass
class BudgetConfig:
    """Configuration for token budget management."""

    max_tokens_per_minute: int = 100_000
    max_tokens_per_hour: int = 1_000_000
    max_tokens_per_day: int = 10_000_000
    max_cost_per_day: float = 50.0
    warning_threshold: float = 0.8
    hard_limit: bool = True


class TokenBudget:
    """Manages token usage budgets and tracks spending."""

    # Cost per 1K tokens by provider/model (approximate)
    COST_RATES: dict[str, dict[str, tuple[float, float]]] = {
        "openai": {
            "gpt-4": (0.03, 0.06),
            "gpt-4-turbo": (0.01, 0.03),
            "gpt-3.5-turbo": (0.0005, 0.0015),
        },
        "anthropic": {
            "claude-3-opus": (0.015, 0.075),
            "claude-3-sonnet": (0.003, 0.015),
            "claude-3-haiku": (0.00025, 0.00125),
        },
        "minimax": {
            "default": (0.0005, 0.0005),
        },
        "kimi": {
            "default": (0.001, 0.001),
        },
        "zai": {
            "default": (0.001, 0.001),
        },
    }

    def __init__(
        self,
        config: BudgetConfig | None = None,
        max_history_entries: int = 10_000,
    ) -> None:
        self.config = config or BudgetConfig()
        self.max_history_entries = max_history_entries
        self.usage_history: list[TokenUsage] = []
        self._reservations: dict[str, int] = {}
        self._current_period_start: dict[BudgetPeriod, datetime] = {
            p: datetime.now(timezone.utc) for p in BudgetPeriod
        }
        # Re-entrant so public methods can self-lock yet still call one another
        # (e.g. reserve_tokens -> check_budget -> get_usage_for_period) without
        # self-deadlock. Callers no longer need to hold an external lock.
        self._lock = threading.RLock()

    def estimate_cost(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float:
        """Estimate cost for a given token usage."""
        provider_rates = self.COST_RATES.get(provider.lower(), {})
        input_rate, output_rate = provider_rates.get(
            model, provider_rates.get("default", (0.001, 0.001))
        )
        input_cost = (prompt_tokens / 1000) * input_rate
        output_cost = (completion_tokens / 1000) * output_rate
        return input_cost + output_cost

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        provider: str = "",
        model: str = "",
        operation: str = "",
    ) -> TokenUsage:
        """Record token usage and return the record. Self-locking."""
        total = prompt_tokens + completion_tokens
        cost = self.estimate_cost(provider, model, prompt_tokens, completion_tokens)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            cost_usd=cost,
            provider=provider,
            model=model,
            operation=operation,
        )
        with self._lock:
            self.usage_history.append(usage)
            self._cleanup_old_history_locked()
        return usage

    def _cleanup_old_history_locked(self) -> None:
        """Remove history older than 30 days to prevent memory bloat.

        Private: mutates shared state and MUST be called with self._lock held.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        self.usage_history = [u for u in self.usage_history if u.timestamp > cutoff]
        if len(self.usage_history) > self.max_history_entries:
            self.usage_history = self.usage_history[-self.max_history_entries :]

    def prune_history(self) -> None:
        """Public method for explicit history cleanup. Self-locking."""
        with self._lock:
            self._cleanup_old_history_locked()

    def get_usage_for_period(self, period: BudgetPeriod) -> tuple[int, float]:
        """Get total tokens and cost for the current period. Self-locking."""
        now = datetime.now(timezone.utc)
        period_start = self._get_period_start(now, period)
        with self._lock:
            relevant = [u for u in self.usage_history if u.timestamp >= period_start]
        total_tokens = sum(u.total_tokens for u in relevant)
        total_cost = sum(u.cost_usd for u in relevant)
        return total_tokens, total_cost

    def _get_period_start(self, now: datetime, period: BudgetPeriod) -> datetime:
        """Calculate the start of the current period."""
        if period == BudgetPeriod.MINUTE:
            return now.replace(second=0, microsecond=0)
        elif period == BudgetPeriod.HOUR:
            return now.replace(minute=0, second=0, microsecond=0)
        elif period == BudgetPeriod.DAY:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == BudgetPeriod.MONTH:
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return now

    def check_budget(self, estimated_tokens: int = 0) -> dict[str, Any]:
        """Check current budget status and return warnings if near limits.

        Self-locking: snapshots reservations and period usage atomically.
        """
        status: dict[str, Any] = {
            "can_proceed": True,
            "warnings": [],
            "limits_hit": [],
        }

        with self._lock:
            minute_tokens, _ = self.get_usage_for_period(BudgetPeriod.MINUTE)
            reserved_total = sum(self._reservations.values())
            hour_tokens, _ = self.get_usage_for_period(BudgetPeriod.HOUR)
            day_tokens, day_cost = self.get_usage_for_period(BudgetPeriod.DAY)

        if minute_tokens + reserved_total + estimated_tokens > self.config.max_tokens_per_minute:
            status["limits_hit"].append("minute_tokens")
            if self.config.hard_limit:
                status["can_proceed"] = False

        if hour_tokens + estimated_tokens > self.config.max_tokens_per_hour:
            status["limits_hit"].append("hour_tokens")
            if self.config.hard_limit:
                status["can_proceed"] = False

        if day_tokens + estimated_tokens > self.config.max_tokens_per_day:
            status["limits_hit"].append("day_tokens")
            if self.config.hard_limit:
                status["can_proceed"] = False

        if (
            day_cost + self.estimate_cost("", "", estimated_tokens, 0)
            > self.config.max_cost_per_day
        ):
            status["limits_hit"].append("day_cost")
            if self.config.hard_limit:
                status["can_proceed"] = False

        # Warning thresholds
        if (
            self.config.max_tokens_per_minute > 0
            and minute_tokens / self.config.max_tokens_per_minute > self.config.warning_threshold
        ):
            status["warnings"].append(
                f"Minute token usage at {minute_tokens / self.config.max_tokens_per_minute:.0%}"
            )
        if (
            self.config.max_tokens_per_hour > 0
            and hour_tokens / self.config.max_tokens_per_hour > self.config.warning_threshold
        ):
            status["warnings"].append(
                f"Hour token usage at {hour_tokens / self.config.max_tokens_per_hour:.0%}"
            )
        if (
            self.config.max_tokens_per_day > 0
            and day_tokens / self.config.max_tokens_per_day > self.config.warning_threshold
        ):
            status["warnings"].append(
                f"Day token usage at {day_tokens / self.config.max_tokens_per_day:.0%}"
            )
        if (
            self.config.max_cost_per_day > 0
            and day_cost / self.config.max_cost_per_day > self.config.warning_threshold
        ):
            status["warnings"].append(
                f"Day cost at ${day_cost:.2f} / ${self.config.max_cost_per_day:.2f}"
            )

        return status

    def reserve_tokens(self, estimated_tokens: int) -> str:
        """Reserve tokens from the budget. Returns reservation ID.

        Raises BudgetExceededError if insufficient budget. Self-locking: the
        check + reserve is atomic so concurrent reservers cannot both pass the
        same budget gate. The RLock makes the nested check_budget call safe.
        """
        from muscle.exceptions import BudgetExceededError

        with self._lock:
            status = self.check_budget(estimated_tokens)
            if not status["can_proceed"]:
                raise BudgetExceededError(f"Budget exceeded: limits hit = {status['limits_hit']}")
            rid = uuid.uuid4().hex[:12]
            self._reservations[rid] = estimated_tokens
            return rid

    def commit_reservation(
        self,
        rid: str,
        prompt_tokens: int,
        completion_tokens: int,
        provider: str = "",
        model: str = "",
        operation: str = "",
    ) -> TokenUsage:
        """Commit a reservation with actual token counts.

        Removes the reservation and records actual usage. Self-locking.
        """
        with self._lock:
            self._reservations.pop(rid, None)
            return self.record_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                provider=provider,
                model=model,
                operation=operation,
            )

    def release_reservation(self, rid: str) -> None:
        """Release a reservation without recording usage (e.g., on failure).

        Self-locking.
        """
        with self._lock:
            self._reservations.pop(rid, None)

    def get_summary(self) -> dict[str, Any]:
        """Get comprehensive usage summary."""
        minute_tokens, _ = self.get_usage_for_period(BudgetPeriod.MINUTE)
        hour_tokens, hour_cost = self.get_usage_for_period(BudgetPeriod.HOUR)
        day_tokens, day_cost = self.get_usage_for_period(BudgetPeriod.DAY)

        with self._lock:
            history_snapshot = list(self.usage_history)

        total_calls = len(history_snapshot)
        total_tokens = sum(u.total_tokens for u in history_snapshot)
        total_cost = sum(u.cost_usd for u in history_snapshot)

        by_provider: dict[str, dict[str, Any]] = {}
        for u in history_snapshot:
            provider = u.provider or "unknown"
            if provider not in by_provider:
                by_provider[provider] = {"tokens": 0, "cost": 0.0, "calls": 0}
            by_provider[provider]["tokens"] += u.total_tokens
            by_provider[provider]["cost"] += u.cost_usd
            by_provider[provider]["calls"] += 1

        return {
            "current_period": {
                "minute": {"tokens": minute_tokens, "limit": self.config.max_tokens_per_minute},
                "hour": {
                    "tokens": hour_tokens,
                    "cost": hour_cost,
                    "token_limit": self.config.max_tokens_per_hour,
                },
                "day": {
                    "tokens": day_tokens,
                    "cost": day_cost,
                    "token_limit": self.config.max_tokens_per_day,
                    "cost_limit": self.config.max_cost_per_day,
                },
            },
            "totals": {
                "total_calls": total_calls,
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost,
            },
            "by_provider": by_provider,
        }

    def estimate_remaining(self, period: BudgetPeriod = BudgetPeriod.DAY) -> dict[str, Any]:
        """Estimate remaining budget for a period."""
        tokens_used, cost_used = self.get_usage_for_period(period)

        if period == BudgetPeriod.DAY:
            token_limit = self.config.max_tokens_per_day
            cost_limit = self.config.max_cost_per_day
        elif period == BudgetPeriod.HOUR:
            token_limit = self.config.max_tokens_per_hour
            cost_limit = None
        elif period == BudgetPeriod.MINUTE:
            token_limit = self.config.max_tokens_per_minute
            cost_limit = None
        else:
            token_limit = self.config.max_tokens_per_day
            cost_limit = None

        remaining_tokens = max(0, token_limit - tokens_used)
        remaining_cost = max(0.0, cost_limit - cost_used) if cost_limit else None

        return {
            "period": period.value,
            "tokens_remaining": remaining_tokens,
            "cost_remaining_usd": remaining_cost,
            "token_usage_percent": tokens_used / token_limit if token_limit > 0 else 0,
        }
