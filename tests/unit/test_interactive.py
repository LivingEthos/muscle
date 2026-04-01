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

    def test_pause_before_iteration_continue(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="c"):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_before_iteration_modify(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="m"):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.MODIFY

    def test_pause_before_iteration_skip(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="s"):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.SKIP

    def test_pause_before_iteration_abort(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="a"):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.ABORT

    def test_pause_before_iteration_invalid_then_valid(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["x", "invalid", "c"]):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_before_iteration_with_continue_full_word(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="continue"):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_failure_continue(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="c"):
            choice, hint = handler.pause_on_failure(1, ["error1"])
        assert choice == InteractiveChoice.CONTINUE
        assert hint is None

    def test_pause_on_failure_modify_with_hint(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["m", "use a different approach"]):
            choice, hint = handler.pause_on_failure(1, ["error1"])
        assert choice == InteractiveChoice.MODIFY
        assert hint == "use a different approach"

    def test_pause_on_failure_modify_empty_hint(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["m", ""]):
            choice, hint = handler.pause_on_failure(1, ["error1"])
        assert choice == InteractiveChoice.MODIFY
        assert hint is None

    def test_pause_on_failure_abort(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="a"):
            choice, hint = handler.pause_on_failure(1, ["error"])
        assert choice == InteractiveChoice.ABORT

    def test_pause_on_failure_invalid_then_valid(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["x", "c"]):
            choice, hint = handler.pause_on_failure(1, ["error"])
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_success_continue(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="c"):
            choice = handler.pause_on_success(1, ["/path/to/file1.py"])
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_success_abort(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="a"):
            choice = handler.pause_on_success(1, ["/path/to/file1.py"])
        assert choice == InteractiveChoice.ABORT

    def test_pause_on_success_invalid_then_valid(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["x", "c"]):
            choice = handler.pause_on_success(1, ["/path/to/file1.py"])
        assert choice == InteractiveChoice.CONTINUE

    def test_view_history_with_items(self):
        handler = InteractiveHandler(enabled=True)
        handler.add_to_history("First iteration result")
        handler.add_to_history("Second iteration result")
        handler.add_to_history("Third iteration result")
        handler.add_to_history("Fourth iteration result")
        handler.add_to_history("Fifth iteration result")
        handler._view_history()
        assert len(handler._history) == 5

    def test_pause_before_iteration_with_strategy(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", return_value="c"):
            choice = handler.pause_before_iteration(1, "task", "evolved strategy text")
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_before_iteration_view_then_continue(self):
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["v", "c"]):
            choice = handler.pause_before_iteration(1, "task", None)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_failure_many_errors(self):
        handler = InteractiveHandler(enabled=True)
        errors = [f"error{i}" for i in range(10)]
        with patch("builtins.input", return_value="c"):
            choice, hint = handler.pause_on_failure(1, errors)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_success_many_files(self):
        handler = InteractiveHandler(enabled=True)
        files = [f"/path/to/file{i}.py" for i in range(15)]
        with patch("builtins.input", return_value="c"):
            choice = handler.pause_on_success(1, files)
        assert choice == InteractiveChoice.CONTINUE

    def test_pause_on_success_view_prints_file_content(self, tmp_path):
        test_file = tmp_path / "mycode.py"
        test_file.write_text("print('hello')")
        handler = InteractiveHandler(enabled=True)
        with patch("builtins.input", side_effect=["v", "c"]):
            choice = handler.pause_on_success(1, [str(test_file)])
        assert choice == InteractiveChoice.CONTINUE
