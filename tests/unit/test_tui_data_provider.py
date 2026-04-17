"""
Unit tests for tui/data_provider.py.
"""

from __future__ import annotations

import json

from tools.muscle.tui.data_provider import TUIDataProvider


def test_load_config_reads_json_from_config_yaml(tmp_path):
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    config_path = muscle_dir / "config.yaml"
    config_path.write_text(
        json.dumps(
            {
                "project": {
                    "automation_level": "review-only",
                    "review_gate": "warn",
                }
            }
        ),
        encoding="utf-8",
    )

    provider = TUIDataProvider(str(tmp_path))

    assert provider._load_config()["automation_level"] == "review-only"


def test_load_config_returns_empty_for_missing_file(tmp_path):
    provider = TUIDataProvider(str(tmp_path))
    assert provider._load_config() == {}


def test_load_config_returns_empty_for_invalid_json(tmp_path):
    muscle_dir = tmp_path / ".muscle"
    muscle_dir.mkdir()
    (muscle_dir / "config.yaml").write_text("not valid json", encoding="utf-8")

    provider = TUIDataProvider(str(tmp_path))

    assert provider._load_config() == {}
