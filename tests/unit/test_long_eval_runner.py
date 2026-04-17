"""
Unit tests for code_review/long_eval_runner.py
"""

import json
import os
import subprocess
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tools.muscle.code_review.long_eval_runner import LongEvalConfig, LongEvalRunner


class TestLongEvalConfig:
    def test_defaults(self):
        config = LongEvalConfig()
        assert config.intensity == "moderate"
        assert config.target_paths is None
        assert config.report_format == "markdown"


class TestLongEvalRunner:
    @pytest.fixture
    def runner(self, tmp_path):
        return LongEvalRunner(project_path=str(tmp_path))

    def test_init_creates_reports_dir(self, tmp_path):
        LongEvalRunner(project_path=str(tmp_path))
        assert (tmp_path / ".muscle" / "reports").exists()

    def test_run_long_eval_generates_results(self, tmp_path):
        config = LongEvalConfig(target_paths=[str(tmp_path)])
        runner = LongEvalRunner(str(tmp_path), config)

        with patch.object(runner, "_run_review_on_path") as mock_review:
            mock_review.return_value = {
                "path": str(tmp_path),
                "issues": [],
                "critical_issues": [],
                "high_issues": [],
                "total_issues": 0,
            }
            with patch("tools.muscle.code_review.long_eval_runner.LearningPipeline") as mock_pl:
                mock_pipeline = MagicMock()
                mock_pipeline.learn_from_review.return_value = {}
                mock_pl.return_value = mock_pipeline
                result = runner.run_long_eval()
                assert result is not None
                assert "started_at" in result
                assert "completed_at" in result
                mock_pl.assert_called_once()

    def test_run_review_on_path_timeout(self, runner):
        runner.config.intensity = "moderate"
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 3600)):
            result = runner._run_review_on_path("/fake/path")
        assert result is not None
        assert "error" in result
        assert "timed out" in result["error"]

    def test_run_review_on_path_error(self, runner):
        with patch("subprocess.run", side_effect=Exception("Boom")):
            result = runner._run_review_on_path("/fake/path")
        assert result is not None
        assert "error" in result
        assert "Boom" in result["error"]

    def test_parse_review_output_empty(self, runner):
        result = runner._parse_review_output("", "/fake")
        assert result["total_issues"] == 0

    def test_parse_review_output_json(self, runner):
        json_output = json.dumps(
            {
                "session_id": "long_eval-20260402",
                "target_path": "/fake",
                "issues": [
                    {
                        "severity": "CRITICAL",
                        "title": "SQL injection in query",
                        "auto_fixable": False,
                    },
                    {"severity": "HIGH", "title": "Missing null check", "auto_fixable": False},
                    {"severity": "MEDIUM", "title": "Unused variable", "auto_fixable": True},
                ],
                "summary": {"critical": 1, "high": 1, "medium": 1, "low": 0, "info": 0},
            }
        )
        result = runner._parse_review_output(json_output, "/fake")
        assert result["total_issues"] == 3  # Sum of all summary values
        assert len(result["critical_issues"]) == 1
        assert len(result["high_issues"]) == 1
        assert result["critical_issues"][0]["description"] == "SQL injection in query"

    def test_parse_review_output_critical(self, runner):
        output = "Some code here\nCRITICAL: SQL injection vulnerability in query\nMore code"
        result = runner._parse_review_output(output, "/fake")
        assert result["total_issues"] >= 1
        assert result["critical_issues"][0]["severity"] == "critical"

    def test_parse_review_output_high(self, runner):
        output = "Code review findings:\nHIGH: Missing null check\nMore content"
        result = runner._parse_review_output(output, "/fake")
        assert result["high_issues"][0]["severity"] == "high"

    def test_save_report_creates_json(self, runner, tmp_path):
        results = {
            "started_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat(),
            "duration_seconds": 10.5,
            "total_issues": 5,
            "critical_issues": [{"description": "Bug"}],
            "high_issues": [{"description": "Warning"}],
            "failures": [],
            "targets": [],
            "success": True,
        }
        path = runner._save_report(results)
        assert path.suffix == ".json"
        assert path.exists()

    def test_generate_markdown_summary(self, runner, tmp_path):
        results = {
            "started_at": datetime.now().isoformat(),
            "duration_seconds": 10.0,
            "total_issues": 3,
            "critical_issues": [{"description": "C1"}],
            "high_issues": [{"description": "H1"}],
            "targets": [{"path": "/src"}],
            "success": True,
        }
        path = runner._generate_markdown_summary(results)
        assert path.suffix == ".md"
        content = path.read_text()
        assert "MUSCLE Long Evaluation Report" in content
        assert "3" in content

    def test_get_latest_report_no_report(self, runner):
        runner._last_run = None
        result = runner.get_latest_report()
        assert result is None

    def test_list_reports_empty(self, runner):
        reports = runner.list_reports()
        assert reports == []

    def test_list_reports_with_files(self, runner, tmp_path):
        reports_dir = tmp_path / ".muscle" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        yesterday = datetime.now() - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")
        report_file = reports_dir / f"long_eval_{date_str}.json"
        report_file.write_text(
            json.dumps({"total_issues": 5, "critical_issues": [], "high_issues": []})
        )
        runner._last_run = yesterday
        reports = runner.list_reports(limit=7)
        assert len(reports) == 1
        assert reports[0]["total_issues"] == 5

    def test_cleanup_old_reports(self, runner, tmp_path):
        reports_dir = tmp_path / ".muscle" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        old_file = reports_dir / "long_eval_2020-01-01.json"
        old_file.write_text("{}")
        old_mtime = (datetime.now() - timedelta(days=60)).timestamp()
        os.utime(old_file, (old_mtime, old_mtime))
        recent_file = reports_dir / f"long_eval_{datetime.now().strftime('%Y-%m-%d')}.json"
        recent_file.write_text("{}")
        removed = runner.cleanup_old_reports(days_to_keep=30)
        assert removed == 1
        assert recent_file.exists()


class TestLongEvalLearningIntegration:
    def test_long_eval_run_calls_learning_pipeline(self, tmp_path):
        config = LongEvalConfig(target_paths=[str(tmp_path)])
        runner = LongEvalRunner(str(tmp_path), config)

        with patch.object(runner, "_run_review_on_path") as mock_review:
            mock_review.return_value = {
                "path": str(tmp_path),
                "issues": [],
                "critical_issues": [],
                "high_issues": [],
                "total_issues": 0,
            }
            with patch("tools.muscle.code_review.long_eval_runner.LearningPipeline") as mock_pl:
                mock_pipeline = MagicMock()
                mock_pipeline.learn_from_review.return_value = {}
                mock_pl.return_value = mock_pipeline
                runner.run_long_eval()
                mock_pl.assert_called_once()

    def test_long_eval_learning_failure_does_not_break_run(self, tmp_path):
        config = LongEvalConfig(target_paths=[str(tmp_path)])
        runner = LongEvalRunner(str(tmp_path), config)

        with patch.object(runner, "_run_review_on_path") as mock_review:
            mock_review.return_value = {
                "path": str(tmp_path),
                "issues": [],
                "critical_issues": [],
                "high_issues": [],
                "total_issues": 0,
            }
            with patch("tools.muscle.code_review.long_eval_runner.LearningPipeline") as mock_pl:
                mock_pl.side_effect = Exception("Pipeline init failed")
                result = runner.run_long_eval()
                # Should still return results despite learning failure
                assert result is not None
                assert result["success"] is True
