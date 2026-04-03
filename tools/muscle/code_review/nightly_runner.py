"""
Nightly Runner - Scheduled background review jobs.

Provides:
- Nightly cron for automated code analysis
- Morning reports summarizing overnight findings
- Configurable schedule and report delivery

Architecture Decision Record (ADR):
- Uses schedule library for cron-like functionality
- Reports stored in .muscle/reports/
- Integrates with ShadowBroker for job tracking
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .learning_pipeline import LearningPipeline
from .types import ReviewResult

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(".muscle/reports")


@dataclass
class NightlyConfig:
    enabled: bool = False
    run_time: str = "03:00"
    target_paths: list[str] | None = None
    modes: list[str] | None = None
    intensity: str = "moderate"
    report_recipients: list[str] | None = None
    report_format: str = "markdown"


class NightlyRunner:
    def __init__(self, project_path: str, config: NightlyConfig | None = None):
        self.project_path = Path(project_path)
        self.reports_dir = self.project_path / REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or NightlyConfig()
        self._last_run: datetime | None = None

    def run_nightly(self) -> dict | None:
        """Run nightly review on configured paths."""
        if not self.config.enabled:
            logger.info("Nightly runner is disabled")
            return None

        logger.info("Starting nightly review run")
        start_time = datetime.now()

        results: dict[str, Any] = {
            "started_at": start_time.isoformat(),
            "targets": [],
            "total_issues": 0,
            "critical_issues": [],
            "high_issues": [],
            "failures": [],
            "success": True,
        }

        target_paths = self.config.target_paths or [str(self.project_path)]

        for target in target_paths:
            try:
                result = self._run_review_on_path(target)
                if result:
                    results["targets"].append(result)
                    results["total_issues"] += result.get("total_issues", 0)
                    results["critical_issues"].extend(result.get("critical_issues", []))
                    results["high_issues"].extend(result.get("high_issues", []))
                    if "error" in result:
                        results["failures"].append(
                            {
                                "path": target,
                                "error": result["error"],
                            }
                        )
                        results["success"] = False
            except Exception as e:
                logger.error(f"Failed to review {target}: {e}")
                results["failures"].append(
                    {
                        "path": target,
                        "error": str(e),
                    }
                )
                results["success"] = False

        results["completed_at"] = datetime.now().isoformat()
        results["duration_seconds"] = (datetime.now() - start_time).total_seconds()

        self._save_report(results)

        # Self-learning from nightly review
        try:
            pipeline = LearningPipeline(str(self.project_path))
            review_result = ReviewResult(
                session_id=f"nightly-{start_time.strftime('%Y%m%d')}",
                target_path=str(self.project_path),
                critical_count=len(results.get("critical_issues", [])),
                high_count=len(results.get("high_issues", [])),
                medium_count=results.get("total_issues", 0)
                - len(results.get("critical_issues", []))
                - len(results.get("high_issues", [])),
                low_count=0,
            )
            pipeline.learn_from_review(review_result)
        except Exception as e:
            logger.warning(f"Nightly learning pipeline failed: {e}")

        self._last_run = start_time

        logger.info(f"Nightly run complete: {results['total_issues']} issues found")
        return results

    def _run_review_on_path(self, target_path: str) -> dict | None:
        """Run muscle review on a single path."""
        try:
            cmd = [
                "muscle",
                "review",
                "--target",
                target_path,
                "--mode",
                "review",
                "--format",
                "json",
                "--intensity",
                self.config.intensity,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            if result.returncode == 0:
                return self._parse_review_output(result.stdout, target_path)
            else:
                logger.warning(f"Review command failed for {target_path}: {result.stderr}")
                return {
                    "path": target_path,
                    "total_issues": 0,
                    "critical_issues": [],
                    "high_issues": [],
                    "error": result.stderr.strip() or "Review command returned non-zero exit",
                }

        except subprocess.TimeoutExpired:
            logger.error(f"Review timed out for {target_path}")
            return {
                "path": target_path,
                "total_issues": 0,
                "critical_issues": [],
                "high_issues": [],
                "error": "Review timed out after 1 hour",
            }
        except Exception as e:
            logger.error(f"Failed to run review for {target_path}: {e}")
            return {
                "path": target_path,
                "total_issues": 0,
                "critical_issues": [],
                "high_issues": [],
                "error": str(e),
            }

    def _parse_review_output(self, output: str, target_path: str) -> dict[str, Any]:
        """Parse review output (JSON preferred) to extract issues."""
        issues: list[dict[str, Any]] = []
        # Try JSON first (machine-readable, preferred for nightly)
        try:
            data = json.loads(output)
            issues = data.get("issues", [])
            summary = data.get("summary", {})

            critical_issues = [
                {"severity": "critical", "description": i.get("title", "")}
                for i in issues
                if i.get("severity", "").upper() == "CRITICAL"
            ]
            high_issues = [
                {"severity": "high", "description": i.get("title", "")}
                for i in issues
                if i.get("severity", "").upper() == "HIGH"
            ]

            return {
                "path": target_path,
                "total_issues": sum(summary.values()) if isinstance(summary, dict) else len(issues),
                "critical_issues": critical_issues,
                "high_issues": high_issues,
            }
        except (json.JSONDecodeError, KeyError):
            pass

        # Fall back to text parsing
        text_issues: list[dict[str, Any]] = []
        try:
            import re

            critical_matches = re.findall(r"CRITICAL:\s*(.+)", output, re.IGNORECASE)
            high_matches = re.findall(r"HIGH:\s*(.+)", output, re.IGNORECASE)

            for match in critical_matches:
                text_issues.append({"severity": "critical", "description": match.strip()})
            for match in high_matches:
                text_issues.append({"severity": "high", "description": match.strip()})

        except Exception as e:
            logger.warning(f"Failed to parse review output: {e}")

        return {
            "path": target_path,
            "total_issues": len(text_issues),
            "critical_issues": [i for i in text_issues if i["severity"] == "critical"],
            "high_issues": [i for i in text_issues if i["severity"] == "high"],
        }

    def _save_report(self, results: dict) -> Path:
        """Save nightly report to disk."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = self.reports_dir / f"nightly_{date_str}.json"

        report_path.write_text(json.dumps(results, indent=2))
        logger.info(f"Saved nightly report to {report_path}")

        self._generate_markdown_summary(results)

        return report_path

    def _generate_markdown_summary(self, results: dict) -> Path:
        """Generate human-readable markdown summary."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        summary_path = self.reports_dir / f"nightly_{date_str}.md"

        lines = [
            "# MUSCLE Nightly Review Report",
            "",
            f"**Date:** {date_str}",
            f"**Duration:** {results.get('duration_seconds', 0):.1f} seconds",
            "",
            "## Summary",
            "",
            "| Metric | Count |",
            "|--------|-------|",
            f"| Total Issues | {results.get('total_issues', 0)} |",
            f"| Critical | {len(results.get('critical_issues', []))} |",
            f"| High | {len(results.get('high_issues', []))} |",
            f"| Targets Scanned | {len(results.get('targets', []))} |",
            "",
        ]

        if results.get("critical_issues"):
            lines.append("## Critical Issues")
            lines.append("")
            for issue in results["critical_issues"][:10]:
                lines.append(f"- {issue.get('description', 'N/A')}")
            lines.append("")

        if results.get("high_issues"):
            lines.append("## High Priority Issues")
            lines.append("")
            for issue in results["high_issues"][:10]:
                lines.append(f"- {issue.get('description', 'N/A')}")
            lines.append("")

        if results.get("failures"):
            lines.append("## Failures")
            lines.append("")
            for failure in results["failures"]:
                lines.append(
                    f"- **{failure.get('path', 'unknown')}**: {failure.get('error', 'Unknown error')}"
                )
            lines.append("")

        lines.append("---")
        lines.append(f"*Generated at {datetime.now().isoformat()}*")

        summary_path.write_text("\n".join(lines))
        logger.info(f"Saved markdown summary to {summary_path}")

        return summary_path

    def get_morning_report(self) -> dict | None:
        """Get the morning report for today."""
        if not self._last_run:
            yesterday = datetime.now() - timedelta(days=1)
            date_str = yesterday.strftime("%Y-%m-%d")
        else:
            date_str = self._last_run.strftime("%Y-%m-%d")

        report_path = self.reports_dir / f"nightly_{date_str}.json"

        if not report_path.exists():
            logger.info(f"No report found for {date_str}")
            return None

        try:
            data: Any = json.loads(report_path.read_text())
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error(f"Failed to load morning report: {e}")
            return None

    def list_reports(self, limit: int = 7) -> list[dict]:
        """List recent nightly reports."""
        if not self.reports_dir.exists():
            return []

        reports = []
        for report_file in sorted(self.reports_dir.glob("nightly_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(report_file.read_text())
                reports.append(
                    {
                        "date": report_file.stem.replace("nightly_", ""),
                        "path": str(report_file),
                        "total_issues": data.get("total_issues", 0),
                        "critical_count": len(data.get("critical_issues", [])),
                        "high_count": len(data.get("high_issues", [])),
                    }
                )
            except Exception:
                continue

        return reports

    def cleanup_old_reports(self, days_to_keep: int = 30) -> int:
        """Remove reports older than specified days."""
        if not self.reports_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=days_to_keep)
        removed = 0

        for report_file in self.reports_dir.glob("nightly_*"):
            try:
                mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                if mtime < cutoff:
                    report_file.unlink()
                    removed += 1
            except Exception:
                continue

        logger.info(f"Cleaned up {removed} old reports")
        return removed


class ScheduleManager:
    """Manages scheduled tasks for MUSCLE."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self._schedule_file = self.project_path / ".muscle" / "schedule.json"
        self._schedule: dict[str, Any] = self._load_schedule()

    def _load_schedule(self) -> dict[str, Any]:
        if self._schedule_file.exists():
            try:
                data: Any = json.loads(self._schedule_file.read_text())
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}

    def _save_schedule(self) -> None:
        self._schedule_file.parent.mkdir(parents=True, exist_ok=True)
        self._schedule_file.write_text(json.dumps(self._schedule, indent=2))

    def enable_nightly(self, run_time: str = "03:00") -> None:
        self._schedule["nightly"] = {
            "enabled": True,
            "run_time": run_time,
            "last_run": None,
            "next_run": self._calculate_next_run(run_time),
        }
        self._save_schedule()

    def disable_nightly(self) -> None:
        self._schedule["nightly"] = {"enabled": False}
        self._save_schedule()

    def _calculate_next_run(self, run_time: str) -> str:
        try:
            hour, minute = map(int, run_time.split(":"))
            now = datetime.now()
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if next_run <= now:
                next_run += timedelta(days=1)

            return next_run.isoformat()
        except Exception:
            return (datetime.now() + timedelta(days=1)).isoformat()

    def get_schedule(self) -> dict:
        return self._schedule.copy()
