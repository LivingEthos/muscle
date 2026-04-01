"""
Unit tests for interactive.py
"""

from unittest.mock import patch

from tools.muscle.interactive import InteractiveChoice, InteractiveHandler


class TestInteractiveHandler:
    def test_disabled_returns_continue(self):
        handler = InteractiveHandler(enabled=False)
        choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_success_disabled(self):
        handler = InteractiveHandler(enabled=False)
        choice = handler.pause_on_success(1, [])
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_failure_disabled(self):
        handler = InteractiveHandler(enabled=False)
        choice, hint = handler.pause_on_failure(1, ["error"])
        assert choice == InteractiveChoice.CONTINUE

    def test_keyboard_interrupt_returns_continue(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_eof_error_returns_continue(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=EOFError):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_add_to_history(self):
        handler = InteractiveHandler(enabled=True)
        handler.add_to_history("iteration 1 result")
        assert len(handler._history) == 1

    def test_view_history_empty(self):
        handler = InteractiveHandler(enabled=True)
        handler._view_history()
        assert len(handler._history) == 0
