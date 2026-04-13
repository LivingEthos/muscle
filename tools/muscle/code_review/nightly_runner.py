# DEPRECATED: This module has been replaced by long_eval_runner.py.
# The nightly scheduling feature has been removed in favor of manual long evaluations.
# See: tools/muscle/code_review/long_eval_runner.py
#
# This file is kept only for backwards compatibility of any external imports.
# All classes re-export from the new module with compatibility shims.

from __future__ import annotations

from .long_eval_runner import LongEvalConfig, LongEvalRunner

# Backwards-compatible aliases
NightlyConfig = LongEvalConfig
NightlyRunner = LongEvalRunner

__all__ = ["NightlyConfig", "NightlyRunner", "LongEvalConfig", "LongEvalRunner"]
