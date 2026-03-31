"""
Pattern Detector - Identifies recurring issues from review history.

Detects patterns that occur 3+ times and triggers skill generation.

Architecture Decision Record (ADR):
- Threshold-based detection (3+ occurrences triggers skill candidate)
- Category clustering for grouping related patterns
- Confidence scoring based on consistency
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PatternInfo:
    pattern: str
    category: str
    occurrences: int
    files: list[str]
    severity_counts: dict[str, int]
    confidence: float


class PatternDetector:
    def __init__(self, kb_path: str | None = None):
        from .review_kb import ReviewKB

        self.kb = ReviewKB(kb_path) if kb_path else ReviewKB()
        self.min_occurrences = 3
        self._patterns: dict[str, PatternInfo] = {}

    def detect_patterns(self) -> list[PatternInfo]:
        """Scan review history and identify recurring patterns."""
        self._patterns.clear()
        pattern_data = self._aggregate_patterns()

        for pattern, data in pattern_data.items():
            if data["occurrences"] >= self.min_occurrences:
                self._patterns[pattern] = PatternInfo(
                    pattern=pattern,
                    category=data["category"],
                    occurrences=data["occurrences"],
                    files=list(data["files"]),
                    severity_counts=data["severity_counts"],
                    confidence=self._calculate_confidence(data),
                )

        return list(self._patterns.values())

    def _aggregate_patterns(self) -> dict[str, dict[str, Any]]:
        patterns: dict[str, dict[str, Any]] = {}

        conn = self.kb._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT code_pattern, category, file_path, severity, COUNT(*) as count
            FROM reviewed_issues
            WHERE code_pattern IS NOT NULL AND code_pattern != ''
            GROUP BY code_pattern, category
        """)

        for row in cursor.fetchall():
            pattern = row["code_pattern"]
            if pattern not in patterns:
                patterns[pattern] = {
                    "occurrences": 0,
                    "files": set(),
                    "severity_counts": {},
                    "category": "",
                }
            patterns[pattern]["occurrences"] += row["count"]
            patterns[pattern]["files"].add(row["file_path"])
            sev = patterns[pattern]["severity_counts"]
            sev[row["severity"]] = sev.get(row["severity"], 0) + row["count"]
            patterns[pattern]["category"] = row["category"]

        conn.close()
        return patterns

    def _calculate_confidence(self, data: dict[str, Any]) -> float:
        files_count = int(len(data["files"]))
        total_occurrences = int(data["occurrences"])
        severity_dist: dict[str, int] = data["severity_counts"]

        file_diversity = float(min(files_count / max(total_occurrences, 1), 1.0))
        consistency = float(sum(1 for v in severity_dist.values() if v > 0)) / float(
            max(len(severity_dist), 1)
        )
        frequency_score = float(min(total_occurrences / 10, 1.0))

        return float(file_diversity * 0.4 + consistency * 0.3 + frequency_score * 0.3)

    def get_skill_candidates(self) -> list[PatternInfo]:
        """Return patterns that should become skills."""
        return [p for p in self._patterns.values() if p.confidence >= 0.5]

    def get_agent_candidates(self) -> list[PatternInfo]:
        """Return patterns complex enough for dedicated agents."""
        complex_categories = {"security", "performance", "concurrency", "architecture"}
        return [
            p
            for p in self._patterns.values()
            if p.category.lower() in complex_categories and p.confidence >= 0.6
        ]

    def should_create_skill(self, pattern: PatternInfo) -> bool:
        """Determine if a pattern warrants a dedicated skill."""
        return pattern.occurrences >= self.min_occurrences and pattern.confidence >= 0.5

    def should_create_agent(self, pattern: PatternInfo) -> bool:
        """Determine if a pattern warrants a dedicated agent."""
        complex_categories = {"security", "performance", "concurrency", "architecture"}
        return (
            pattern.category.lower() in complex_categories
            and pattern.occurrences >= 5
            and pattern.confidence >= 0.6
        )
