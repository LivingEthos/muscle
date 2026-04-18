"""
Unit tests for the mutation runner.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from tools.muscle.code_review.mutation_runner import MutationRunner
from tools.muscle.project_memory import ProjectMemory


def _write_project(project: Path, source: str, test_body: str) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    (project / "sample.py").write_text(source, encoding="utf-8")
    (project / "tests" / "test_sample.py").write_text(test_body, encoding="utf-8")


def test_mutation_runner_kills_detected_mutant(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        "def bump(values):\n    values.append(1)\n    return values\n",
        "from sample import bump\n\n\ndef test_bump():\n    assert bump([0]) == [0, 1]\n",
    )

    runner = MutationRunner(str(tmp_path))
    report = runner.run(
        str(tmp_path / "sample.py"),
        test_command=f"{sys.executable} -m pytest tests -q",
        limit=1,
        timeout_seconds=60,
    )

    assert report["killed"] == 1
    assert report["survived"] == 0
    assert Path(report["report_paths"]["json"]).exists()


def test_mutation_runner_records_survived_mutant_as_test_gap(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        "def is_positive(value=1):\n    return value > 0\n",
        "from sample import is_positive\n\n\ndef test_is_positive():\n    assert is_positive(2) is True\n",
    )

    runner = MutationRunner(str(tmp_path))
    report = runner.run(
        str(tmp_path / "sample.py"),
        test_command=f"{sys.executable} -m pytest tests -q",
        limit=1,
        timeout_seconds=60,
    )

    assert report["survived"] == 1
    pm = ProjectMemory(str(tmp_path))
    logs = pm.list_action_logs(project_path=str(tmp_path), action_type="mutation_survived")
    assert len(logs) == 1
    assert logs[0]["entity_type"] == "mutation_test"


def test_mutation_runner_cleans_up_disposable_workspaces(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        "def bump(values):\n    values.append(1)\n    return values\n",
        "from sample import bump\n\n\ndef test_bump():\n    assert bump([0]) == [0, 1]\n",
    )

    created_paths: list[str] = []
    real_temp_dir = tempfile.TemporaryDirectory

    class TrackingTempDir:
        def __init__(self, *args, **kwargs):
            self._inner = real_temp_dir(*args, **kwargs)
            created_paths.append(self._inner.name)

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._inner.__exit__(exc_type, exc, tb)

    runner = MutationRunner(str(tmp_path))
    with patch(
        "tools.muscle.code_review.mutation_runner.tempfile.TemporaryDirectory", TrackingTempDir
    ):
        runner.run(
            str(tmp_path / "sample.py"),
            test_command=f"{sys.executable} -m pytest tests -q",
            limit=1,
            timeout_seconds=60,
        )

    assert created_paths
    assert all(not Path(path).exists() for path in created_paths)
