# DEPRECATED: Tests for the nightly_runner backwards-compatibility shim.
# The real tests are in test_long_eval_runner.py.

from tools.muscle.code_review.long_eval_runner import LongEvalConfig, LongEvalRunner
from tools.muscle.code_review.nightly_runner import NightlyConfig, NightlyRunner


def test_nightly_config_is_long_eval_config() -> None:
    """NightlyConfig should be an alias for LongEvalConfig."""
    assert NightlyConfig is LongEvalConfig


def test_nightly_runner_is_long_eval_runner() -> None:
    """NightlyRunner should be an alias for LongEvalRunner."""
    assert NightlyRunner is LongEvalRunner
