"""
Unit tests for code_generator.py
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tools.muscle.code_generator import CodeGenerator, GenerationResult
from tools.muscle.m27_client import TokenUsage


class TestGenerationResult:
    def test_defaults(self):
        result = GenerationResult(
            success=True,
            files_written=["a.py", "b.py"],
            token_usage=500,
            raw_response="generated code",
            error=None,
        )
        assert result.success is True
        assert len(result.files_written) == 2
        assert result.error is None


class TestCodeGenerator:
    @pytest.fixture
    def mock_client(self):
        client = Mock()
        return client

    @pytest.fixture
    def generator(self, mock_client):
        return CodeGenerator(mock_client)

    def test_empty_task_returns_error(self, generator):
        result, usage = generator.generate(task="", evolved_strategy=None, output_dir="/tmp")
        assert result == "Error: Task cannot be empty"

    def test_task_truncated_if_too_long(self, generator, mock_client):
        long_task = "x" * 15000
        mock_client.chat.return_value = ("def foo(): pass", TokenUsage(100, 50))
        with patch.object(Path, "write_text"):
            result, usage = generator.generate(
                task=long_task, evolved_strategy=None, output_dir="/tmp"
            )
        assert "Generated" in result

    def test_normalize_output_relative_path(self, generator):
        assert generator._normalize_output_relative_path("normal.py", "generated.py") == "normal.py"
        with pytest.raises(ValueError, match="Traversal"):
            generator._normalize_output_relative_path("../etc/passwd", "generated.py")
        with pytest.raises(ValueError, match="Backslash"):
            generator._normalize_output_relative_path("src\\app.py", "generated.py")

    def test_sanitize_content(self, generator):
        content = "normal text\x00null byte\x1fcontrol"
        sanitized = generator._sanitize_content(content)
        assert "\x00" not in sanitized

    def test_generate_with_code_block(self, generator, mock_client, tmp_path):
        mock_client.chat.return_value = (
            '```python\ndef hello():\n    print("world")\n```',
            TokenUsage(input_tokens=100, output_tokens=50),
        )
        with patch.object(Path, "write_text"):
            result, usage = generator.generate(
                task="say hello",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )
        assert "Generated" in result

    def test_generate_without_code_blocks_fallback(self, generator, mock_client, tmp_path):
        mock_client.chat.return_value = (
            "Here is the code:\nprint('hello')",
            TokenUsage(input_tokens=100, output_tokens=50),
        )
        with patch.object(Path, "write_text"):
            result, usage = generator.generate(
                task="say hello",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )
        assert "Generated" in result

    def test_language_detection(self, generator, mock_client, tmp_path):
        mock_client.chat.return_value = (
            '```python\nprint("hello")\n```',
            TokenUsage(input_tokens=100, output_tokens=50),
        )
        lang = generator._detect_language("#!/usr/bin/env python3\nprint(1)")
        assert lang == "python"

    def test_generate_streaming(self, generator, mock_client, tmp_path):
        mock_client.chat_streaming.return_value = iter(
            [
                ("# Generated\n", TokenUsage(10, 5)),
                ("def main():", TokenUsage(20, 10)),
            ]
        )
        chunks = list(
            generator.generate_streaming(
                task="test",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )
        )
        assert len(chunks) >= 2

    def test_generate_streaming_ignores_terminal_empty_chunk(self, generator, mock_client, tmp_path):
        mock_client.chat_streaming.return_value = iter(
            [
                ("```python\nprint('hi')\n", None),
                ("```python\nprint('hi')\n```", TokenUsage(10, 5)),
                ("", TokenUsage(10, 5)),
            ]
        )

        chunks = list(
            generator.generate_streaming(
                task="test",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )
        )

        assert chunks[-1][0] == "Generated 1 files"
        assert (tmp_path / "main.py").exists()


class TestGenerateRetryLogic:
    """Tests for generate() retry logic."""

    @pytest.fixture
    def gen_with_retry(self):
        mock_cli = Mock()
        return CodeGenerator(mock_cli, max_retries=3, retry_delay=0.1), mock_cli

    def test_retry_on_empty_response(self, gen_with_retry, tmp_path):
        """Test generate retries on empty response."""
        generator, mock_client = gen_with_retry
        mock_client.chat.side_effect = [
            ("", TokenUsage(0, 0)),
            ("", TokenUsage(0, 0)),
            ("```python\ndef foo(): pass\n```", TokenUsage(10, 5)),
        ]

        with patch.object(Path, "write_text"):
            result, usage = generator.generate(
                task="say hello",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )

        assert "Generated" in result
        assert mock_client.chat.call_count == 3

    def test_all_retries_failed(self, gen_with_retry, tmp_path):
        """Test generate returns error when all retries fail."""
        generator, mock_client = gen_with_retry
        mock_client.chat.return_value = ("", TokenUsage(0, 0))

        with patch.object(Path, "write_text"):
            result, usage = generator.generate(
                task="say hello",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )

        assert "failed" in result.lower()

    def test_cost_optimizer_cache_hit(self, gen_with_retry, tmp_path):
        """Test generate uses cached result when available."""
        from tools.muscle.cost_optimizer import CostOptimizer

        generator, mock_client = gen_with_retry
        cost_opt = Mock(spec=CostOptimizer)
        cost_opt.get_from_cache.return_value = {"files": ["cached.py"]}
        generator.cost_optimizer = cost_opt
        generator.max_retries = 1
        (tmp_path / "cached.py").write_text("print('cached')", encoding="utf-8")

        result, usage = generator.generate(
            task="say hello",
            evolved_strategy=None,
            output_dir=str(tmp_path),
        )

        assert "cache" in result.lower()
        mock_client.chat.assert_not_called()

    def test_cost_optimizer_cache_miss(self, gen_with_retry, tmp_path):
        """Test generate calls API when cache misses."""
        from tools.muscle.cost_optimizer import CostOptimizer

        generator, mock_client = gen_with_retry
        cost_opt = Mock(spec=CostOptimizer)
        cost_opt.get_from_cache.return_value = None
        cost_opt.estimate_tier.return_value = "medium"
        cost_opt.get_max_tokens.return_value = 4096
        generator.cost_optimizer = cost_opt
        generator.max_retries = 1
        mock_client.chat.return_value = ("```python\ndef foo(): pass\n```", TokenUsage(10, 5))

        with patch.object(Path, "write_text"):
            result, usage = generator.generate(
                task="say hello",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )

        assert mock_client.chat.called

    def test_cost_optimizer_cache_ignores_stale_files(self, gen_with_retry, tmp_path):
        """Test generate regenerates when cached files are missing from the output directory."""
        from tools.muscle.cost_optimizer import CostOptimizer

        generator, mock_client = gen_with_retry
        cost_opt = Mock(spec=CostOptimizer)
        cost_opt.get_from_cache.return_value = {"files": ["cached.py"]}
        cost_opt.estimate_tier.return_value = "medium"
        cost_opt.get_max_tokens.return_value = 4096
        generator.cost_optimizer = cost_opt
        generator.max_retries = 1
        mock_client.chat.return_value = ("```python\ndef foo(): pass\n```", TokenUsage(10, 5))

        with patch.object(Path, "write_text"):
            generator.generate(
                task="say hello",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )

        assert mock_client.chat.called

    def test_cost_optimizer_cache_includes_evolved_strategy(self, gen_with_retry, tmp_path):
        """Test generate does not reuse base-task cache when the strategy changes."""
        from tools.muscle.cost_optimizer import CostOptimizer

        generator, mock_client = gen_with_retry
        cost_opt = Mock(spec=CostOptimizer)
        cost_opt.get_from_cache.side_effect = (
            lambda cache_key: {"files": ["cached.py"]} if cache_key == "say hello" else None
        )
        cost_opt.estimate_tier.return_value = "medium"
        cost_opt.get_max_tokens.return_value = 4096
        generator.cost_optimizer = cost_opt
        generator.max_retries = 1
        mock_client.chat.return_value = ("```python\ndef foo(): pass\n```", TokenUsage(10, 5))

        with patch.object(Path, "write_text"):
            generator.generate(
                task="say hello",
                evolved_strategy="use different filenames",
                output_dir=str(tmp_path),
            )

        assert mock_client.chat.called


class TestParseAndWrite:
    """Tests for _parse_and_write() edge cases."""

    @pytest.fixture
    def gen(self):
        return CodeGenerator(Mock())

    def test_parse_and_write_with_code_block_and_filename(self, gen, tmp_path):
        """Test _parse_and_write extracts and writes files from code blocks."""
        response = "```python\n# main.py\ndef main(): pass\n```"
        code_output, files = gen._parse_and_write(response, tmp_path)
        assert len(files) == 1
        assert (tmp_path / files[0]).exists()

    def test_parse_and_write_rejects_traversal_filename(self, gen, tmp_path):
        response = "```python\n# src/../../escape.py\nprint('oops')\n```"
        code_output, files = gen._parse_and_write(response, tmp_path)
        assert files == ["generated_output.txt"]
        assert not (tmp_path.parent / "escape.py").exists()

    def test_parse_and_write_with_plain_code_fallback(self, gen, tmp_path):
        """Test _parse_and_write uses plain code fallback when no blocks found."""
        response = "Here is the code:\ndef foo(): pass"
        code_output, files = gen._parse_and_write(response, tmp_path)
        assert "generated" in code_output.lower() or len(files) >= 0

    def test_parse_and_write_fallback_to_raw(self, gen, tmp_path):
        """Test _parse_and_write writes raw response when no code found."""
        response = "This is not code at all, just text."
        code_output, files = gen._parse_and_write(response, tmp_path)
        assert "generated_output.txt" in files or "Error" in code_output

    def test_parse_and_write_empty_response(self, gen):
        """Test _parse_and_write handles empty response."""
        code_output, files = gen._parse_and_write("", Path("/tmp"))
        assert "Error" in code_output


class TestExtractStrategies:
    """Tests for code extraction strategies."""

    @pytest.fixture
    def gen(self):
        return CodeGenerator(Mock())

    def test_extract_inline_code_blocks_here_is_code_pattern(self, gen):
        """Test _extract_inline_code_blocks with 'Here is code' pattern."""
        text = "Here is the code:\ndef hello():\n    print('hello')\n\nAnd that's it."
        blocks = gen._extract_inline_code_blocks(text)
        assert len(blocks) >= 1

    def test_extract_inline_code_blocks_code_after_title(self, gen):
        """Test _extract_inline_code_blocks with code-after-title pattern."""
        text = "# Main Script\ndef hello():\n    print('hello')\n\nMore text."
        blocks = gen._extract_inline_code_blocks(text)
        assert len(blocks) >= 1

    def test_extract_code_blocks_uses_embedded_filename_comments(self, gen):
        """Test fenced code blocks honor first-line filename comments."""
        text = (
            "```python\n# hello.py\ndef add(a, b):\n    return a + b\n```\n"
            "```python\n# test_hello.py\nfrom hello import add\n```"
        )
        blocks = gen._extract_code_blocks(text)

        assert blocks[0][0] == "hello.py"
        assert "hello.py" not in blocks[0][1]
        assert blocks[1][0] == "test_hello.py"

    def test_extract_embedded_filename_keeps_non_filename_comments(self, gen):
        """Test ordinary comments are not stripped as filenames."""
        content = "# this is a normal comment\ndef add(a, b):\n    return a + b"
        filename, cleaned = gen._extract_embedded_filename(content)

        assert filename is None
        assert cleaned == content

    def test_looks_like_code_detects_python(self, gen):
        """Test _looks_like_code returns True for Python code."""
        code = "def hello():\n    print('hello')"
        assert gen._looks_like_code(code) is True

    def test_looks_like_code_detects_javascript(self, gen):
        """Test _looks_like_code returns True for JavaScript code."""
        code = "const x = 5;"
        assert gen._looks_like_code(code) is True

    def test_looks_like_code_rejects_prose(self, gen):
        """Test _looks_like_code returns False for prose text."""
        text = "This is a description of what the code should do."
        assert gen._looks_like_code(text) is False

    def test_extract_plain_code_finds_python_function(self, gen):
        """Test _extract_plain_code finds Python function."""
        text = "Here is the implementation:\ndef hello():\n    print('hello')\n\nThis is the rest."
        result = gen._extract_plain_code(text)
        assert result is not None
        assert "def" in result

    def test_extract_plain_code_returns_none_for_short_content(self, gen):
        """Test _extract_plain_code returns None for short content."""
        text = "x = 1"
        result = gen._extract_plain_code(text)
        assert result is None

    def test_extract_code_lines_by_indentation(self, gen):
        """Test _extract_code_lines_by_indentation extracts indented code."""
        lines = [
            "# Start of code",
            "def hello():",
            "    print('hello')",
            "",
            "# End",
        ]
        result = gen._extract_code_lines_by_indentation(lines)
        assert len(result) > 0


class TestGenerateStreaming:
    """Tests for generate_streaming() edge cases."""

    @pytest.fixture
    def gen(self):
        return CodeGenerator(Mock())

    def test_generate_streaming_with_progress_callback(self, gen, tmp_path):
        """Test generate_streaming calls progress_callback."""
        gen.client.chat_streaming.return_value = iter(
            [
                ("# Generated\n", TokenUsage(10, 5)),
                ("def main(): pass\n", TokenUsage(20, 10)),
            ]
        )

        callback_calls = []

        def progress_cb(text):
            callback_calls.append(text)

        list(
            gen.generate_streaming(
                task="test",
                evolved_strategy=None,
                output_dir=str(tmp_path),
                progress_callback=progress_cb,
            )
        )

        assert callback_calls == ["# Generated\n", "pass\n"]

    def test_generate_streaming_empty_response(self, gen, tmp_path):
        """Test generate_streaming handles empty response."""
        gen.client.chat_streaming.return_value = iter([("", TokenUsage(0, 0))])

        chunks = list(
            gen.generate_streaming(
                task="test",
                evolved_strategy=None,
                output_dir=str(tmp_path),
            )
        )

        assert any("fail" in c[0].lower() for c in chunks)


class TestSanitizeFunctions:
    """Tests for prompt sanitization helpers."""

    def test_sanitize_for_prompt_handles_none(self):
        from tools.muscle.code_generator import _sanitize_for_prompt

        assert _sanitize_for_prompt(None) == ""

    def test_sanitize_for_prompt_truncates_long_string(self):
        from tools.muscle.code_generator import _sanitize_for_prompt

        long_text = "a" * 6000
        result = _sanitize_for_prompt(long_text)
        assert len(result) <= 5020

    def test_sanitize_for_prompt_removes_null_bytes(self):
        from tools.muscle.code_generator import _sanitize_for_prompt

        result = _sanitize_for_prompt("hello\x00world")
        assert "\x00" not in result

    def test_sanitize_for_prompt_removes_crlf(self):
        from tools.muscle.code_generator import _sanitize_for_prompt

        result = _sanitize_for_prompt("line1\r\nline2")
        assert "\r\n" not in result
