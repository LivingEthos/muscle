"""Tests for the lazy-import facade of ``muscle.code_review``.

The package exposes every public name via a uniform lazy ``__getattr__`` so a
single broken submodule import never takes down the whole package. These tests
pin that contract: the package imports cleanly, every ``__all__`` name resolves,
``__dir__`` mirrors ``__all__``, and unknown attributes raise ``AttributeError``.
"""

from __future__ import annotations

import importlib

import pytest


def test_package_imports_cleanly() -> None:
    module = importlib.import_module("muscle.code_review")
    assert module.__all__  # non-empty, single source of truth


def test_every_all_name_resolves() -> None:
    module = importlib.import_module("muscle.code_review")
    for name in module.__all__:
        resolved = getattr(module, name)
        assert resolved is not None


def test_review_benchmark_runner_is_exposed() -> None:
    module = importlib.import_module("muscle.code_review")
    assert "ReviewBenchmarkRunner" in module.__all__
    assert module.ReviewBenchmarkRunner is not None


def test_dir_matches_all() -> None:
    module = importlib.import_module("muscle.code_review")
    assert dir(module) == sorted(module.__all__)


def test_unknown_attribute_raises() -> None:
    module = importlib.import_module("muscle.code_review")
    with pytest.raises(AttributeError):
        _ = module.DefinitelyNotARealExport


def test_resolved_name_is_cached_in_globals() -> None:
    module = importlib.import_module("muscle.code_review")
    name = module.__all__[0]
    getattr(module, name)
    # After first access the name is cached as a real module global, so a plain
    # vars() lookup (which bypasses __getattr__) now finds it.
    assert name in vars(module)
