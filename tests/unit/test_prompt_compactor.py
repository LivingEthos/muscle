"""
Unit tests for prompt compaction.
"""

from __future__ import annotations

from tools.muscle.optimization.prompt_compactor import compact_prompt_text, should_compact_stage


def test_compact_prompt_text_preserves_protected_content_verbatim() -> None:
    prompt = """Your task is to:

Please investigate this thoroughly and provide your findings and proposed solutions.

```python
print("hello")
```

uv run pytest tests/unit/test_loop_controller.py -q
/Users/example/project/tools/muscle/cli.py
https://example.com/docs
{"status": "ok"}
Traceback (most recent call last):
  File "/tmp/app.py", line 7, in <module>
ValueError: boom
"""

    compacted, metrics = compact_prompt_text(prompt)

    assert 'print("hello")' in compacted
    assert "uv run pytest tests/unit/test_loop_controller.py -q" in compacted
    assert "/Users/example/project/tools/muscle/cli.py" in compacted
    assert "https://example.com/docs" in compacted
    assert '{"status": "ok"}' in compacted
    assert 'File "/tmp/app.py", line 7, in <module>' in compacted
    assert "ValueError: boom" in compacted
    assert metrics.original_chars == len(prompt)
    assert metrics.compacted_chars <= metrics.original_chars


def test_compact_prompt_text_rewrites_only_prose_lines() -> None:
    prompt = """Your task is to:
Please investigate this thoroughly and provide your findings and proposed solutions.
"""

    compacted, metrics = compact_prompt_text(prompt)

    assert compacted == "Task:\nInvestigate thoroughly and propose validated fixes."
    assert metrics.applied is True
    assert metrics.estimated_tokens_saved >= 1


def test_should_compact_stage_only_enables_benchmark_gated_stages() -> None:
    assert should_compact_stage("generate") is True
    assert should_compact_stage("handoff") is True
    assert should_compact_stage("semantic_review") is False
    assert should_compact_stage("pressure_review") is False
