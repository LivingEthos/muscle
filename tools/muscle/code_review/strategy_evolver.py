"""
Strategy Evolver - Evolves review strategies based on validation results.

Analyzes which strategies work best and updates strategy_kb.json.

Architecture Decision Record (ADR):
- Tracks strategy effectiveness over time
- Evolves when a strategy achieves >80% success rate
- Maintains strategy_kb.json with ranked strategies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..strategy_kb import StrategyKB

logger = logging.getLogger(__name__)


@dataclass
class StrategyResult:
    strategy_id: str
    strategy_name: str
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    avg_issues_found: float = 0.0
    avg_fix_success_rate: float = 0.0
    last_run: str | None = None
    effectiveness_score: float = 0.0


class StrategyEvolver:
    def __init__(self, project_path: str, strategy_kb: StrategyKB | None = None):
        self.project_path = Path(project_path)
        self.strategy_kb = strategy_kb or StrategyKB()
        self._strategy_results: dict[str, StrategyResult] = {}

    def record_strategy_run(
        self,
        strategy_id: str,
        strategy_name: str,
        issues_found: int,
        fixes_succeeded: int,
        fixes_failed: int,
    ) -> None:
        if strategy_id not in self._strategy_results:
            self._strategy_results[strategy_id] = StrategyResult(
                strategy_id=strategy_id,
                strategy_name=strategy_name,
            )

        result = self._strategy_results[strategy_id]
        result.total_runs += 1

        if fixes_succeeded > 0 or fixes_failed > 0:
            result.avg_fix_success_rate = (
                result.avg_fix_success_rate * (result.total_runs - 1)
                + fixes_succeeded / (fixes_succeeded + fixes_failed)
            ) / result.total_runs

        result.avg_issues_found = (
            result.avg_issues_found * (result.total_runs - 1) + issues_found
        ) / result.total_runs

        if fixes_succeeded > fixes_failed:
            result.successful_runs += 1
        elif fixes_failed > fixes_succeeded:
            result.failed_runs += 1

        result.last_run = datetime.now().isoformat()
        result.effectiveness_score = self._calculate_effectiveness(result)

    def _calculate_effectiveness(self, result: StrategyResult) -> float:
        if result.total_runs == 0:
            return 0.0

        success_rate = result.successful_runs / result.total_runs
        fix_rate = result.avg_fix_success_rate
        consistency = 1.0 - (result.failed_runs / result.total_runs)

        return success_rate * 0.4 + fix_rate * 0.4 + consistency * 0.2

    def should_evolve(self, strategy_id: str) -> bool:
        """Check if strategy should evolve based on performance."""
        if strategy_id not in self._strategy_results:
            return False

        result = self._strategy_results[strategy_id]
        return result.effectiveness_score >= 0.8 and result.total_runs >= 5

    def evolve_strategy(self, strategy_id: str) -> dict | None:
        """Generate evolved version of a strategy."""
        if strategy_id not in self._strategy_results:
            return None

        result = self._strategy_results[strategy_id]

        evolved_prompt = self._generate_evolved_prompt(strategy_id, result)

        evolved_strategy = {
            "id": f"{strategy_id}_evolved_{datetime.now().strftime('%Y%m%d')}",
            "parent_id": strategy_id,
            "name": f"{result.strategy_name} (Evolved)",
            "prompt": evolved_prompt,
            "effectiveness_score": result.effectiveness_score,
            "created_at": datetime.now().isoformat(),
            "based_on_runs": result.total_runs,
        }

        self.strategy_kb.add_strategy(
            error_pattern=str(evolved_strategy["id"]),
            root_cause=f"Evolved from {strategy_id}",
            solution_strategy=evolved_prompt,
            language=None,
        )

        logger.info(f"Evolved strategy: {strategy_id} -> {evolved_strategy['id']}")
        return evolved_strategy

    def _generate_evolved_prompt(self, strategy_id: str, result: StrategyResult) -> str:
        strategies = self.strategy_kb.find_by_pattern(strategy_id)
        base_prompt = strategies[0].solution_strategy if strategies else ""

        improvements = []
        if result.avg_fix_success_rate < 0.7:
            improvements.append("- Focus on more conservative, lower-risk fixes")
        if result.failed_runs > result.successful_runs:
            improvements.append("- Reduce aggression; prefer 'ask' mode over 'auto-fix'")

        improvement_text = (
            "\n".join(improvements) if improvements else "- Maintain current approach"
        )

        return f"""{base_prompt}

## Evolved Improvements (based on {result.total_runs} runs)

{improvement_text}

## Performance Metrics
- Success rate: {result.successful_runs / max(result.total_runs, 1):.1%}
- Avg fix success: {result.avg_fix_success_rate:.1%}
- Avg issues found: {result.avg_issues_found:.1f}
"""

    def get_top_strategies(self, limit: int = 5) -> list[StrategyResult]:
        """Return top strategies sorted by effectiveness score."""
        sorted_results = sorted(
            self._strategy_results.values(),
            key=lambda r: r.effectiveness_score,
            reverse=True,
        )
        return sorted_results[:limit]

    def get_strategy_recommendation(self, issue_category: str) -> str | None:
        """Recommend best strategy for given category."""
        category_strategies = [
            r
            for r in self._strategy_results.values()
            if r.strategy_name.lower().replace(" ", "_").find(issue_category.lower()) >= 0
        ]

        if not category_strategies:
            category_strategies = list(self._strategy_results.values())

        if not category_strategies:
            return None

        best = max(category_strategies, key=lambda r: r.effectiveness_score)
        return best.strategy_id if best.effectiveness_score > 0.3 else None

    def export_results(self) -> dict:
        """Export all strategy results for analysis."""
        return {
            "strategies": [
                {
                    "id": r.strategy_id,
                    "name": r.strategy_name,
                    "total_runs": r.total_runs,
                    "successful_runs": r.successful_runs,
                    "failed_runs": r.failed_runs,
                    "effectiveness_score": r.effectiveness_score,
                    "last_run": r.last_run,
                }
                for r in self._strategy_results.values()
            ],
            "exported_at": datetime.now().isoformat(),
        }
