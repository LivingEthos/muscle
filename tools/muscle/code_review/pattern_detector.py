"""
Pattern Detector - Identifies recurring issues from review history using M2.7 semantic analysis.

Detects patterns that occur 3+ times and triggers skill generation.

Architecture Decision Record (ADR):
- M2.7-powered semantic clustering (not just SQL grouping)
- Groups semantically similar issues even with different wording
- Generates cluster summaries for skill/agent creation
- Confidence scoring includes semantic analysis
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PatternCluster:
    pattern_id: str
    pattern: str
    category: str
    summary: str
    root_cause: str
    occurrences: int
    files: list[str]
    severity_counts: dict[str, int]
    confidence: float
    evidence_count: int = 0
    semantically_related_issues: list[dict] = field(default_factory=list)


@dataclass
class PatternInfo:
    pattern: str
    category: str
    occurrences: int
    files: list[str]
    severity_counts: dict[str, int]
    confidence: float


class PatternDetector:
    def __init__(
        self,
        kb_path: str | None = None,
        m27_client: Any | None = None,
        project_memory: Any | None = None,
    ):
        from .review_kb import ReviewKB

        self.kb = ReviewKB(kb_path) if kb_path else ReviewKB()
        self.m27 = m27_client
        self._pm = project_memory
        self.min_occurrences = 3
        self._patterns: dict[str, PatternCluster] = {}
        self._cluster_cache: dict[str, list[dict]] = {}

    def _get_evidence_from_decisions(self, pattern: str) -> int:
        """Query memory_decisions for evidence count supporting a pattern (DB-first evidence sourcing)."""
        if not self._pm:
            return 0

        try:
            decisions = self._pm.list_decisions(decision_type="create_skill", limit=100)
            # Count decisions whose reasoning mentions the pattern
            count = sum(1 for d in decisions if pattern.lower() in d.get("reasoning", "").lower())
            return count
        except Exception as e:
            logger.debug(f"Could not query memory_decisions for evidence: {e}")
            return 0

    def detect_patterns(self) -> list[PatternCluster]:
        """Scan review history and identify recurring patterns using M2.7 semantic analysis."""
        self._patterns.clear()

        if self.m27:
            return self._detect_patterns_with_m27()
        else:
            return self._detect_patterns_fallback()

    def _detect_patterns_with_m27(self) -> list[PatternCluster]:
        """Detect patterns using M2.7 semantic clustering."""
        raw_issues = self._get_all_issues()

        if not raw_issues:
            logger.info("No issues found in review history")
            return []

        clustered = self._m27_semantic_clustering(raw_issues)

        for cluster in clustered:
            cluster_id = cluster["cluster_id"]
            issues = cluster["issues"]

            if len(issues) >= self.min_occurrences:
                canonical = cluster.get("canonical_pattern", issues[0].get("code_pattern", ""))
                evidence_count = self._get_evidence_from_decisions(canonical)
                self._patterns[cluster_id] = PatternCluster(
                    pattern_id=cluster_id,
                    pattern=canonical,
                    category=cluster.get("category", issues[0].get("category", "unknown")),
                    summary=cluster.get("summary", ""),
                    root_cause=cluster.get("root_cause", ""),
                    occurrences=len(issues),
                    files=list({i.get("file_path", "") for i in issues}),
                    severity_counts=self._count_severities(issues),
                    confidence=cluster.get("confidence", 0.5),
                    evidence_count=evidence_count,
                    semantically_related_issues=issues,
                )

        logger.info(f"Detected {len(self._patterns)} patterns from {len(raw_issues)} issues (M2.7)")
        return list(self._patterns.values())

    def _detect_patterns_fallback(self) -> list[PatternCluster]:
        """Fallback pattern detection using SQL aggregation (no M2.7)."""
        pattern_data = self._aggregate_patterns()

        for pattern, data in pattern_data.items():
            if data["occurrences"] >= self.min_occurrences:
                evidence_count = self._get_evidence_from_decisions(pattern)
                self._patterns[pattern] = PatternCluster(
                    pattern_id=pattern,
                    pattern=pattern,
                    category=data["category"],
                    summary=f"Issues matching pattern: {pattern[:50]}",
                    root_cause="Pattern detected via code analysis",
                    occurrences=data["occurrences"],
                    files=list(data["files"]),
                    severity_counts=data["severity_counts"],
                    confidence=self._calculate_confidence(data),
                    evidence_count=evidence_count,
                    semantically_related_issues=[],
                )

        logger.info(f"Detected {len(self._patterns)} patterns (fallback mode)")
        return list(self._patterns.values())

    def _aggregate_patterns(self) -> dict[str, dict[str, Any]]:
        """Aggregate patterns from database using SQL (fallback when no M2.7)."""
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
        """Calculate confidence score for a pattern (fallback when no M2.7)."""
        files_count = int(len(data["files"]))
        total_occurrences = int(data["occurrences"])
        severity_dist: dict[str, int] = data["severity_counts"]

        file_diversity = float(min(files_count / max(total_occurrences, 1), 1.0))
        consistency = float(sum(1 for v in severity_dist.values() if v > 0)) / float(
            max(len(severity_dist), 1)
        )
        frequency_score = float(min(total_occurrences / 10, 1.0))

        return float(file_diversity * 0.4 + consistency * 0.3 + frequency_score * 0.3)

    def _get_all_issues(self) -> list[dict[str, Any]]:
        conn = self.kb._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, file_path, line_number, severity, category, title, code_pattern
            FROM reviewed_issues
            ORDER BY created_at DESC
            LIMIT 500
        """)

        issues = []
        for row in cursor.fetchall():
            issues.append(
                {
                    "id": row["id"],
                    "file_path": row["file_path"],
                    "line_number": row["line_number"],
                    "severity": row["severity"],
                    "category": row["category"],
                    "title": row["title"],
                    "code_pattern": row["code_pattern"] or "",
                }
            )

        conn.close()
        return issues

    def _m27_semantic_clustering(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Use M2.7 to semantically cluster related issues."""
        if not self.m27:
            return self._fallback_clustering(issues)

        if len(issues) < 3:
            return self._fallback_clustering(issues)

        issues_text = json.dumps(issues[:50], indent=2)

        prompt = f"""Analyze these code review issues and cluster semantically similar ones.

Each issue has: file_path, line_number, severity, category, title, code_pattern

Issues to cluster:
{issues_text}

Your task:
1. Group issues that have the same ROOT CAUSE even if worded differently
2. For each cluster, identify:
   - A canonical_pattern: The underlying code pattern that causes this issue
   - A category: The type of issue (e.g., "null-safety", "resource-leak", "concurrency")
   - A summary: 1-2 sentence description of the pattern
   - A root_cause: Why this pattern is problematic
   - confidence: How confident you are (0.0-1.0)

Return a JSON array of clusters:
```json
[
  {{
    "cluster_id": "null_check_1",
    "canonical_pattern": "Missing null check before method call on object from external source",
    "category": "null-safety",
    "summary": "Objects from external sources (API, user input, file read) need null validation",
    "root_cause": "Assumption that external data is always valid",
    "confidence": 0.85,
    "issue_indices": [0, 3, 7]
  }}
]
```

Only cluster issues with clear semantic similarity. Return at most 20 clusters."""

        try:
            response_text, usage = self.m27.chat(
                messages=[{"role": "user", "content": prompt}],
                system="You are a code pattern analysis expert. Return valid JSON only.",
                max_tokens=4096,
                temperature=0.3,
            )

            clusters = self._parse_clusters_response(response_text)

            if not clusters:
                return self._fallback_clustering(issues)

            result = []
            for cluster in clusters:
                indices = cluster.get("issue_indices", [])
                cluster_issues = [issues[i] for i in indices if i < len(issues)]
                if cluster_issues:
                    cluster["issues"] = cluster_issues
                    result.append(cluster)

            return result

        except Exception as e:
            logger.warning(f"M2.7 clustering failed: {e}, using fallback")
            return self._fallback_clustering(issues)

    def _fallback_clustering(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Fallback: Group by exact code_pattern + category match (old behavior)."""
        clusters: dict[str, dict[str, Any]] = {}

        for i, issue in enumerate(issues):
            pattern = issue.get("code_pattern", "")
            category = issue.get("category", "unknown")

            if not pattern:
                continue

            key = f"{pattern}|{category}"
            if key not in clusters:
                clusters[key] = {
                    "cluster_id": key,
                    "canonical_pattern": pattern,
                    "category": category,
                    "summary": f"Issues matching pattern: {pattern[:50]}",
                    "root_cause": "Pattern detected via code analysis",
                    "confidence": 0.5,
                    "issue_indices": [],
                }

            clusters[key]["issue_indices"].append(i)

        return list(clusters.values())

    def _parse_clusters_response(self, response: str) -> list[dict[str, Any]]:
        """Parse M2.7 JSON response, handling truncation."""
        try:
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                if end > start:
                    response = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                if end > start:
                    response = response[start:end].strip()

            data = json.loads(response)
            if isinstance(data, list):
                return data
            return []
        except json.JSONDecodeError as e:
            truncated = response[:500] if len(response) > 500 else response
            logger.warning(f"Failed to parse clusters JSON: {e}. Response: {truncated}...")
            return []

    def _count_severities(self, issues: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in issues:
            sev = issue.get("severity", "MEDIUM")
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    def get_skill_candidates(self) -> list[PatternCluster]:
        """Return patterns that should become skills."""
        return [p for p in self._patterns.values() if p.confidence >= 0.5]

    def get_agent_candidates(self) -> list[PatternCluster]:
        """Return patterns complex enough for dedicated agents."""
        complex_categories = {"security", "performance", "concurrency", "architecture"}
        return [
            p
            for p in self._patterns.values()
            if p.category.lower() in complex_categories and p.confidence >= 0.6
        ]

    def should_create_skill(self, pattern: PatternCluster) -> bool:
        """Determine if a pattern warrants a dedicated skill."""
        return pattern.occurrences >= self.min_occurrences and pattern.confidence >= 0.5

    def should_create_agent(self, pattern: PatternCluster) -> bool:
        """Determine if a pattern warrants a dedicated agent."""
        complex_categories = {"security", "performance", "concurrency", "architecture"}
        return (
            pattern.category.lower() in complex_categories
            and pattern.occurrences >= 5
            and pattern.confidence >= 0.6
        )

    def analyze_failure_root_cause(self, pattern: PatternCluster, failed_fixes: list[dict]) -> str:
        """Use M2.7 to analyze why fixes failed and suggest improvements."""
        if not self.m27 or not failed_fixes:
            return pattern.root_cause

        fixes_text = json.dumps(failed_fixes[:5], indent=2)

        prompt = f"""Analyze why fixes for this code pattern keep failing:

Pattern: {pattern.pattern}
Category: {pattern.category}
Root Cause: {pattern.root_cause}

Failed fix attempts:
{fixes_text}

For each failure, identify:
1. Why the fix didn't work
2. What was overlooked
3. A suggested improved approach

Return a JSON object:
```json
{{
  "common_failure_reason": "Root cause of why fixes keep failing",
  "overlooked_factors": ["factor 1", "factor 2"],
  "improved_approach": "How to fix this pattern correctly"
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
            return data.get("common_failure_reason", pattern.root_cause)  # type: ignore[no-any-return]

        except Exception as e:
            logger.warning(f"Failed to analyze root cause: {e}")
            return pattern.root_cause
