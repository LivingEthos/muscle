"""
Self-Improver - SCLE analyzes its own performance and improves.

Architecture Decision Record (ADR):
- Tracks all session outcomes
- Analyzes what worked / what didn't
- Generates improved prompts based on history
- Weekly auto-review capability
"""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SessionOutcome:
    session_id: str
    task: str
    status: str
    iterations: int
    tokens: int
    duration_seconds: float
    errors: list[str]
    strategy_used: str | None
    success: bool
    timestamp: str


class SelfImprover:
    IMPROVEMENT_LOG = Path.home() / ".scle" / "improvement_log.json"
    SYSTEM_PROMPTS_DIR = Path.home() / ".scle" / "prompts"

    def __init__(self) -> None:
        self.IMPROVEMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        self.SYSTEM_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_log()

    def _load_log(self) -> None:
        if self.IMPROVEMENT_LOG.exists():
            try:
                data = json.loads(self.IMPROVEMENT_LOG.read_text())
                self.outcomes = [SessionOutcome(**o) for o in data.get("outcomes", [])]
            except Exception:
                self.outcomes = []
        else:
            self.outcomes = []

    def _save_log(self) -> None:
        data = {
            "outcomes": [asdict(o) for o in self.outcomes],
            "last_updated": datetime.now().isoformat(),
        }
        self.IMPROVEMENT_LOG.write_text(json.dumps(data, indent=2))

    def log_session(
        self,
        session_id: str,
        task: str,
        status: str,
        iterations: int,
        tokens: int,
        duration: float,
        errors: list[str],
        strategy: str | None = None,
    ) -> None:
        """Log a session outcome for later analysis."""
        outcome = SessionOutcome(
            session_id=session_id,
            task=task,
            status=status,
            iterations=iterations,
            tokens=tokens,
            duration_seconds=duration,
            errors=errors,
            strategy_used=strategy,
            success=status == "success",
            timestamp=datetime.now().isoformat(),
        )
        self.outcomes.append(outcome)
        self._save_log()

    def analyze_patterns(self) -> dict:
        """Analyze past sessions to find patterns."""
        if not self.outcomes:
            return {"error": "No sessions logged yet"}

        total = len(self.outcomes)
        successful = sum(1 for o in self.outcomes if o.success)

        # Analyze by iteration count
        iteration_counts: dict[int, int] = defaultdict(int)
        for o in self.outcomes:
            iteration_counts[o.iterations] += 1

        # Find common errors
        error_counts: dict[str, int] = defaultdict(int)
        for o in self.outcomes:
            for err in o.errors:
                error_counts[err] += 1

        # Find best strategies
        strategy_success: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "total": 0}
        )
        for o in self.outcomes:
            if o.strategy_used:
                strategy_success[o.strategy_used]["total"] += 1
                if o.success:
                    strategy_success[o.strategy_used]["success"] += 1

        best_strategies = []
        for strategy, stats in strategy_success.items():
            if stats["total"] >= 2:  # At least 2 uses
                rate = stats["success"] / stats["total"]
                best_strategies.append((strategy, rate, stats["total"]))
        best_strategies.sort(key=lambda x: (-x[1], -x[2]))

        return {
            "total_sessions": total,
            "success_rate": round(successful / total * 100, 1),
            "average_iterations": round(sum(o.iterations for o in self.outcomes) / total, 1),
            "average_tokens": round(sum(o.tokens for o in self.outcomes) / total),
            "most_common_iterations": max(iteration_counts.items(), key=lambda x: x[1])[0],
            "common_errors": dict(sorted(error_counts.items(), key=lambda x: -x[1])[:5]),
            "best_strategies": [
                {"strategy": s, "success_rate": round(r * 100, 1), "uses": t}
                for s, r, t in best_strategies[:5]
            ],
            "recommendations": self._generate_recommendations(successful, total, best_strategies),
        }

    def _generate_recommendations(
        self, successful: int, total: int, best_strategies: list
    ) -> list[str]:
        recommendations = []

        success_rate = successful / total * 100 if total > 0 else 0

        if success_rate < 50:
            recommendations.append(
                "Success rate is low. Consider simpler tasks or breaking into smaller steps."
            )

        if not best_strategies:
            recommendations.append(
                "No strategies have been used multiple times. Give each approach a few tries."
            )
        else:
            recommendations.append(
                f"Best strategy: '{best_strategies[0][0]}' with {best_strategies[0][1] * 100:.0f}% success rate"
            )

        return recommendations

    def generate_improved_system_prompt(self) -> str:
        """Generate an improved system prompt based on analysis."""
        analysis = self.analyze_patterns()

        prompt_parts = [
            "You are SCLE, a Self-Correcting Loop Engine.",
            "You generate code and improve based on errors.",
            "",
        ]

        if analysis.get("recommendations"):
            prompt_parts.append("# Recent Learnings")
            for rec in analysis["recommendations"][:3]:
                prompt_parts.append(f"- {rec}")

        if analysis.get("best_strategies"):
            prompt_parts.append("")
            prompt_parts.append("# Effective Strategies")
            for strat in analysis["best_strategies"][:3]:
                prompt_parts.append(
                    f"- {strat['strategy']} (success rate: {strat['success_rate']}%)"
                )

        return "\n".join(prompt_parts)

    def run_self_review(self) -> str:
        """Run a self-review and return report."""
        analysis = self.analyze_patterns()

        lines = [
            "=" * 60,
            "SCLE Self-Improvement Report",
            "=" * 60,
            f"Generated: {datetime.now().isoformat()}",
            "",
            "## Statistics",
            f"  Total Sessions: {analysis.get('total_sessions', 0)}",
            f"  Success Rate: {analysis.get('success_rate', 0)}%",
            f"  Avg Iterations: {analysis.get('average_iterations', 0)}",
            f"  Avg Tokens: {analysis.get('average_tokens', 0)}",
            "",
            "## Common Errors",
        ]

        for err, count in analysis.get("common_errors", {}).items():
            lines.append(f"  - {err}: {count} occurrences")

        lines.extend(["", "## Recommendations"])
        for rec in analysis.get("recommendations", []):
            lines.append(f"  - {rec}")

        return "\n".join(lines)

    def export_data(self, filepath: str) -> None:
        """Export improvement data to JSON file."""
        with open(filepath, "w") as f:
            json.dump(
                {
                    "outcomes": [asdict(o) for o in self.outcomes],
                    "analysis": self.analyze_patterns(),
                    "improved_prompt": self.generate_improved_system_prompt(),
                },
                f,
                indent=2,
            )

    def import_data(self, filepath: str) -> int:
        """Import improvement data. Returns count of imported outcomes."""
        with open(filepath) as f:
            data = json.load(f)

        imported = len(data.get("outcomes", []))
        self.outcomes.extend([SessionOutcome(**o) for o in data.get("outcomes", [])])
        self._save_log()
        return imported

    def clear_log(self) -> None:
        """Clear all logged outcomes."""
        self.outcomes = []
        self._save_log()
