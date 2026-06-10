"""Tests for the tool-output crusher and its reversible (CCR) store."""

from __future__ import annotations

import json
import multiprocessing
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from muscle.optimization.structured_compactor import expand_records
from muscle.optimization.tool_output_crusher import (
    DEFAULT_RECORD_CAP,
    CcrStore,
    CcrStoreError,
    _crush_records,
    crush_text,
)


def _make_records(n: int) -> list[dict[str, object]]:
    return [
        {"file": f"src/module_{i}.py", "line": i * 10, "rule": "E501", "message": f"detail {i}"}
        for i in range(n)
    ]


def _save_worker(root: str, max_entries: int, count: int, proc_id: int) -> None:
    """Module-level worker (spawn-picklable) that hammers CcrStore.save."""
    store = CcrStore(Path(root), max_entries=max_entries)
    for i in range(count):
        store.save(f"proc {proc_id} payload {i} " * 200)


class TestJsonRecordsStrategy:
    def test_record_payload_becomes_table(self) -> None:
        text = json.dumps(_make_records(20), indent=2)
        result = crush_text(text)
        assert result.applied
        assert result.strategy == "json_records"
        assert result.compact_chars < result.original_chars
        assert expand_records(result.text)[0]["file"] == "src/module_0.py"

    def test_wrapped_single_list_payload_is_unwrapped(self) -> None:
        text = json.dumps({"results": _make_records(20)}, indent=2)
        result = crush_text(text)
        assert result.applied
        assert result.strategy == "json_records"

    def test_over_cap_records_keep_head_tail_and_anomalies_with_note(self) -> None:
        records = _make_records(150)
        records[75]["message"] = "fatal error: connection refused"
        result = crush_text(json.dumps(records), record_cap=50)
        assert result.applied
        assert "omitted" in result.text
        assert "connection refused" in result.text  # anomaly row survives the cap
        assert "module_0.py" in result.text  # head
        assert "module_149.py" in result.text  # tail

    def test_non_record_json_falls_through(self) -> None:
        result = crush_text(json.dumps([1, 2, 3]))
        assert result.strategy != "json_records"

    def test_smaller_dedupe_window_candidate_wins_over_table(self) -> None:
        # Wide records with identical values: the indented JSON has long runs of
        # identical consecutive lines (dedupe + window crushes hard), while the
        # table keeps every wide row. The dedupe/window candidate is the smaller
        # one, so the table candidate must NOT short-circuit it.
        records = [{f"col{k}": "value" for k in range(15)} for _ in range(60)]
        text = json.dumps(records, indent=2)
        result = crush_text(text)
        assert result.applied
        # The smaller candidate (dedupe/window) wins, not json_records.
        assert result.strategy != "json_records"
        assert "window" in result.strategy or "dedupe" in result.strategy
        table = _crush_records(records, "records", DEFAULT_RECORD_CAP)
        assert table is not None
        assert result.compact_chars < len(table)


class TestLineStrategies:
    def test_consecutive_duplicates_collapse_with_count(self) -> None:
        text = "\n".join(["retrying request"] * 40 + ["done"])
        result = crush_text(text)
        assert result.applied
        assert "dedupe" in result.strategy
        assert "retrying request  [x40]" in result.text
        assert "done" in result.text

    def test_anomaly_lines_are_never_collapsed(self) -> None:
        text = "\n".join(["ERROR: disk full"] * 5)
        result = crush_text(text)
        assert result.text.count("ERROR: disk full") == 5 or not result.applied

    def test_windowing_keeps_anomalies_and_marks_elisions(self) -> None:
        lines = [f"info line {i}" for i in range(500)]
        lines[250] = "Traceback (most recent call last):"
        result = crush_text("\n".join(lines), line_budget=100)
        assert result.applied
        assert "window" in result.strategy
        assert "Traceback" in result.text
        assert "lines omitted]" in result.text
        # All elision markers account for every omitted line.
        omitted = sum(
            int(line.split("[crush: ")[1].split(" ")[0])
            for line in result.text.split("\n")
            if line.startswith("[crush: ")
        )
        kept = sum(1 for line in result.text.split("\n") if not line.startswith("[crush: "))
        assert omitted + kept == 500

    def test_small_input_returns_unchanged(self) -> None:
        text = "short output\nno compression needed"
        result = crush_text(text)
        assert not result.applied
        assert result.text == text
        assert result.strategy == "none"
        assert result.estimated_tokens_saved == 0

    def test_output_is_deterministic(self) -> None:
        text = "\n".join([f"line {i % 7}" for i in range(400)])
        assert crush_text(text, line_budget=50).text == crush_text(text, line_budget=50).text


class TestCcrStore:
    def test_save_load_roundtrip_and_handle_format(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        original = "x" * 10_000
        handle = store.save(original)
        assert handle.startswith("ccr:") and len(handle) == 4 + 16
        assert store.load(handle) == original

    def test_crush_with_store_yields_recoverable_handle(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        text = "\n".join(["dup"] * 300)
        result = crush_text(text, store=store)
        assert result.applied and result.handle is not None
        assert store.load(result.handle) == text

    def test_unapplied_crush_stores_nothing(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        result = crush_text("tiny", store=store)
        assert not result.applied
        assert result.handle is None
        assert not list((tmp_path / "ccr").glob("*.txt"))

    def test_load_fails_closed_on_tampered_content(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        handle = store.save("authentic content")
        path = next((tmp_path / "ccr").glob("*.txt"))
        path.write_text("tampered content")
        with pytest.raises(CcrStoreError, match="integrity"):
            store.load(handle)

    def test_load_rejects_malformed_handles(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        for bad in ("ccr:../../etc/passwd", "nothandle", "ccr:SHORT", ""):
            with pytest.raises(CcrStoreError):
                store.load(bad)

    def test_missing_entry_raises(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        with pytest.raises(CcrStoreError, match="pruned"):
            store.load("ccr:" + "0" * 16)

    def test_prune_bounds_entry_count(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr", max_entries=3)
        for i in range(6):
            store.save(f"payload number {i} " * 100)
        assert len(list((tmp_path / "ccr").glob("*.txt"))) <= 3

    def test_save_is_idempotent_for_same_content(self, tmp_path: Path) -> None:
        store = CcrStore(tmp_path / "ccr")
        assert store.save("same") == store.save("same")
        assert len(list((tmp_path / "ccr").glob("*.txt"))) == 1

    def test_save_acquires_store_lock_around_prune(self, tmp_path: Path) -> None:
        """The save+prune unit must run under the store-wide advisory lock.

        Locking contract test: fcntl locks are per-process and do not exclude
        sibling threads, so rather than race threads we assert the lock is taken
        on the store sentinel for the duration of save (which contains prune).
        """
        import muscle.optimization.tool_output_crusher as toc

        store = CcrStore(tmp_path / "ccr")
        locked_paths: list[Path] = []
        real_lock = toc.advisory_file_lock

        @contextmanager
        def spy_lock(path: Path):  # type: ignore[no-untyped-def]
            locked_paths.append(path)
            with real_lock(path):
                yield

        with patch.object(toc, "advisory_file_lock", spy_lock):
            store.save("x" * 5000)

        assert locked_paths == [store._lock_target()]
        assert store._lock_target() == (tmp_path / "ccr" / ".prune")

    def test_concurrent_processes_keep_store_bounded_and_uncorrupted(self, tmp_path: Path) -> None:
        """Concurrent cross-process saves keep the store bounded and intact.

        fcntl advisory locks are per-process, so this drives the real contract:
        three processes hammer save() (each of which prunes) at once. Without the
        store-wide lock, two prunes can interleave their glob+delete and either
        over-evict below the bound or unlink a half-written entry. With it, the
        store stays at or under ``max_entries`` and every surviving file still
        passes its integrity check (``load`` re-hashes and fails closed).
        """
        ctx = multiprocessing.get_context("spawn")
        root = tmp_path / "ccr"
        n_per_proc = 12
        max_entries = 5
        procs = [
            ctx.Process(target=_save_worker, args=(str(root), max_entries, n_per_proc, pid))
            for pid in range(3)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
            assert p.exitcode == 0

        # Prune still enforces the bound under concurrency.
        survivors = list(root.glob("*.txt"))
        assert len(survivors) <= max_entries
        # Every survivor is intact: load re-hashes and raises on mismatch/partial.
        store = CcrStore(root, max_entries=max_entries)
        for path in survivors:
            handle = "ccr:" + path.stem
            assert store.load(handle)  # raises CcrStoreError if corrupted
