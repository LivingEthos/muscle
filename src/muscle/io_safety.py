"""
Shared filesystem safety helpers for MUSCLE-managed files.

Architecture Decision Record (ADR):
- Use advisory sidecar locks for macOS/Linux multi-process coordination
- Commit writes atomically with temp-file + os.replace in the destination directory
- Keep helpers small and reusable so session, memory, and artifact writers share behavior
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


@contextmanager
def advisory_file_lock(path: Path) -> Iterator[None]:
    """Acquire an advisory lock for the given target path."""
    lock_path = _lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write text atomically by replacing the destination from a temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> None:
    """Serialize JSON and write it atomically."""
    atomic_write_text(
        path,
        json.dumps(
            payload,
            ensure_ascii=ensure_ascii,
            indent=indent,
            sort_keys=sort_keys,
        ),
    )


def locked_jsonl_append(path: Path, line: str, *, encoding: str = "utf-8") -> None:
    """Append one JSONL line while holding an advisory lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with advisory_file_lock(path):
        with open(path, "a", encoding=encoding) as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def update_text_file_locked(
    path: Path,
    update_fn: Callable[[str], str],
    *,
    default_content: str = "",
    encoding: str = "utf-8",
) -> str:
    """Apply a read-modify-write update under an advisory lock."""
    with advisory_file_lock(path):
        current = default_content
        if path.exists():
            current = path.read_text(encoding=encoding)
        updated = update_fn(current)
        atomic_write_text(path, updated, encoding=encoding)
        return updated


def update_json_file_locked(
    path: Path,
    update_fn: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    default_factory: Callable[[], dict[str, Any]] | None = None,
    ensure_ascii: bool = False,
    indent: int | None = 2,
    sort_keys: bool = False,
) -> dict[str, Any]:
    """Apply a JSON object update under an advisory lock."""
    default_factory = default_factory or dict

    def wrapped(current_text: str) -> str:
        payload = default_factory()
        if current_text.strip():
            loaded = json.loads(current_text)
            if not isinstance(loaded, dict):
                msg = "Expected JSON object"
                raise json.JSONDecodeError(msg, current_text, 0)
            payload = loaded
        updated = update_fn(dict(payload))
        return json.dumps(
            updated,
            ensure_ascii=ensure_ascii,
            indent=indent,
            sort_keys=sort_keys,
        )

    updated_text = update_text_file_locked(path, wrapped, default_content="")
    loaded = json.loads(updated_text) if updated_text.strip() else {}
    return loaded if isinstance(loaded, dict) else {}
