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

    def test_sanitize_filename(self, generator):
        assert generator._sanitize_filename("normal.py") == "normal.py"
        assert generator._sanitize_filename("../etc/passwd") == "file_/etc/passwd"
        assert generator._sanitize_filename("file with spaces.py") == "filewithspaces.py"
        assert generator._sanitize_filename("" + "a" * 300 + ".py") == ("a" * 255)

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
