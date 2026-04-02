"""
Strategy Evolver - Evolves review strategies based on M2.7-powered validation results.

Analyzes which strategies work best and why, using M2.7 for root cause analysis.

Architecture Decision Record (ADR):
- M2.7-powered root cause analysis of failures
- Evolves when a strategy achieves >80% success rate
- Stores evolved strategies with failure analysis context
- Uses M2.7 to generate improved strategy prompts
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..strategy_kb import StrategyKB

logger = logging.getLogger(__name__)


@dataclass
class StrategyFailure:
    strategy_id: str
    failure_reason: str
    what_was_overlooked: str
    suggested_improvement: str
    related_issues: list[dict] = field(default_factory=list)


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
    failures: list[StrategyFailure] = field(default_factory=list)


class StrategyEvolver:
    def __init__(
        self,
        project_path: str,
        strategy_kb: StrategyKB | None = None,
        m27_client: Any | None = None,
    ):
        self.project_path = Path(project_path)
        self.strategy_kb = strategy_kb or StrategyKB()
        self.m27 = m27_client
        self._strategy_results: dict[str, StrategyResult] = {}

    def record_strategy_run(
        self,
        strategy_id: str,
        strategy_name: str,
        issues_found: int,
        fixes_succeeded: int,
        fixes_failed: int,
        failure_details: list[dict[str, Any]] | None = None,
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
            if failure_details and self.m27:
                analysis = self._m27_analyze_failures(strategy_id, failure_details)
                if analysis:
                    result.failures.append(analysis)

        result.last_run = datetime.now().isoformat()
        result.effectiveness_score = self._calculate_effectiveness(result)

    def _m27_analyze_failures(
        self, strategy_id: str, failures: list[dict[str, Any]]
    ) -> StrategyFailure | None:
        """Use M2.7 to analyze why a strategy failed."""
        if not self.m27 or not failures:
            return None

        failures_text = json.dumps(failures[:5], indent=2)

        prompt = f"""Analyze why a code review strategy keeps failing.

Strategy ID: {strategy_id}
Failed fix attempts:
{failures_text}

For each failure, identify:
1. Why the fix didn't work
2. What was overlooked in the approach
3. A suggested improvement

Return a JSON object with your analysis:
```json
{{
  "failure_reason": "Root cause of why fixes keep failing",
  "what_was_overlooked": ["factor 1", "factor 2"],
  "suggested_improvement": "How to approach this pattern correctly"
}}
```"""

        try:
            response_text, _ = self.m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a code debugging expert. Return valid JSON only.",
                max_tokens=2048,
                temperature=0.3,
            )

            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()

            data = json.loads(response_text)
            return StrategyFailure(
                strategy_id=strategy_id,
                failure_reason=data.get("failure_reason", "Unknown failure"),
                what_was_overlooked=", ".join(data.get("what_was_overlooked", [])),
                suggested_improvement=data.get("suggested_improvement", ""),
                related_issues=failures[:5],
            )

        except Exception as e:
            logger.warning(f"Failed to analyze strategy failure with M2.7: {e}")
            return StrategyFailure(
                strategy_id=strategy_id,
                failure_reason=str(e),
                what_was_overlooked="Analysis failed",
                suggested_improvement="Review manually",
            )

    def _calculate_effectiveness(self, result: StrategyResult) -> float:
        if result.total_runs == 0:
            return 0.0

        success_rate = result.successful_runs / result.total_runs
        fix_rate = result.avg_fix_success_rate
        consistency = 1.0 - (result.failed_runs / result.total_runs)

        failure_penalty = min(len(result.failures) * 0.05, 0.3)

        base_score = success_rate * 0.4 + fix_rate * 0.4 + consistency * 0.2
        return max(0.0, base_score - failure_penalty)

    def should_evolve(self, strategy_id: str) -> bool:
        """Check if strategy should evolve based on performance."""
        if strategy_id not in self._strategy_results:
            return False

        result = self._strategy_results[strategy_id]
        return result.effectiveness_score >= 0.8 and result.total_runs >= 5

    def evolve_strategy(self, strategy_id: str) -> dict | None:
        """Generate evolved version of a strategy using M2.7 analysis."""
        if strategy_id not in self._strategy_results:
            return None

        result = self._strategy_results[strategy_id]

        evolved_prompt = self._generate_m27_evolved_prompt(strategy_id, result)

        evolved_strategy = {
            "id": f"{strategy_id}_evolved_{datetime.now().strftime('%Y%m%d')}",
            "parent_id": strategy_id,
            "name": f"{result.strategy_name} (Evolved)",
            "prompt": evolved_prompt,
            "effectiveness_score": result.effectiveness_score,
            "created_at": datetime.now().isoformat(),
            "based_on_runs": result.total_runs,
            "failure_analysis": [
                {
                    "reason": f.failure_reason,
                    "overlooked": f.what_was_overlooked,
                    "improvement": f.suggested_improvement,
                }
                for f in result.failures[-3:]
            ],
        }

        self.strategy_kb.add_strategy(
            error_pattern=str(evolved_strategy["id"]),
            root_cause=f"Evolved from {strategy_id} with M2.7 analysis",
            solution_strategy=evolved_prompt,
            language=None,
        )

        logger.info(f"Evolved strategy: {strategy_id} -> {evolved_strategy['id']}")
        return evolved_strategy

    def _generate_m27_evolved_prompt(self, strategy_id: str, result: StrategyResult) -> str:
        """Use M2.7 to generate an improved strategy prompt based on failure analysis."""
        strategies = self.strategy_kb.find_by_pattern(strategy_id)
        base_prompt = strategies[0].solution_strategy if strategies else ""

        prompt = f"""Generate an improved code review strategy based on performance analysis.

Original Strategy:
{base_prompt[:2000] if base_prompt else "No original strategy available"}

Performance Analysis:
- Total runs: {result.total_runs}
- Successful runs: {result.successful_runs}
- Failed runs: {result.failed_runs}
- Avg fix success rate: {result.avg_fix_success_rate:.1%}
- Effectiveness score: {result.effectiveness_score:.2f}

"""

        if result.failures:
            prompt += "Failure Analysis:\n"
            for i, failure in enumerate(result.failures[-3:], 1):
                prompt += f"\n{i}. Why it failed: {failure.failure_reason}\n"
                prompt += f"   What was overlooked: {failure.what_was_overlooked}\n"
                prompt += f"   Suggested improvement: {failure.suggested_improvement}\n"

        prompt += """

Based on this analysis, generate an improved strategy that:
1. Addresses the specific failure modes identified
2. Incorporates the lessons learned
3. Is more conservative where failures occurred
4. Maintains what worked well

Return the evolved strategy as a complete prompt that can be used for future reviews."""

        if not self.m27:
            return self._generate_fallback_evolved_prompt(strategy_id, result, base_prompt)

        try:
            response_text, _ = self.m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are an expert code reviewer. Return the improved strategy prompt only.",
                max_tokens=4096,
                temperature=0.5,
            )
            return response_text.strip()  # type: ignore[no-any-return]

        except Exception as e:
            logger.warning(f"M2.7 evolved prompt generation failed: {e}")
            return self._generate_fallback_evolved_prompt(strategy_id, result, base_prompt)

    def _generate_fallback_evolved_prompt(
        self, strategy_id: str, result: StrategyResult, base_prompt: str
    ) -> str:
        """Fallback: generate evolved prompt without M2.7."""
        improvements = []
        if result.avg_fix_success_rate < 0.7:
            improvements.append("- Focus on more conservative, lower-risk fixes")
        if result.failed_runs > result.successful_runs:
            improvements.append("- Reduce aggression; prefer 'ask' mode over 'auto-fix'")
        if result.failures:
            for f in result.failures[-2:]:
                improvements.append(f"- Avoid: {f.failure_reason[:100]}")

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
        """Recommend best strategy for given category using M2.7 analysis."""
        if self.m27:
            return self._m27_recommend_strategy(issue_category)

        return self._fallback_recommend_strategy(issue_category)

    def _m27_recommend_strategy(self, issue_category: str) -> str | None:
        """Use M2.7 to recommend the best strategy for an issue category."""
        assert self.m27 is not None, "M27 client should be set when calling this method"
        m27 = self.m27
        strategies = list(self._strategy_results.values())

        if not strategies:
            return None

        strategies_text = json.dumps(
            [
                {
                    "id": s.strategy_id,
                    "name": s.strategy_name,
                    "effectiveness": s.effectiveness_score,
                    "runs": s.total_runs,
                    "success_rate": s.successful_runs / max(s.total_runs, 1),
                }
                for s in strategies
            ],
            indent=2,
        )

        prompt = f"""Given this issue category: "{issue_category}"

And these available strategies:
{strategies_text}

Which strategy would be MOST effective for this issue category and WHY?

Consider:
1. Past effectiveness on similar issues
2. Success rate and consistency
3. Whether the strategy's focus matches the issue category

Return a JSON object:
```json
{{
  "recommended_strategy_id": "strategy_id",
  "reasoning": "Why this strategy is best for this category"
}}
```"""

        try:
            response_text, _ = m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a code review strategy expert. Return valid JSON only.",
                max_tokens=1024,
                temperature=0.3,
            )

            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    response_text = response_text[start:end].strip()

            data = json.loads(response_text)
            return data.get("recommended_strategy_id")  # type: ignore[no-any-return]

        except Exception as e:
            logger.warning(f"M2.7 strategy recommendation failed: {e}")
            return self._fallback_recommend_strategy(issue_category)

    def _fallback_recommend_strategy(self, issue_category: str) -> str | None:
        """Fallback: recommend based on metrics only."""
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
                    "failures": [
                        {"reason": f.failure_reason, "improvement": f.suggested_improvement}
                        for f in r.failures
                    ],
                }
                for r in self._strategy_results.values()
            ],
            "exported_at": datetime.now().isoformat(),
        }
